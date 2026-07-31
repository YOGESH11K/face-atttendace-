"""Face encoding, quality assessment and matching (thread-safe)."""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

import cv2
import face_recognition
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

# Cap on how long a face list may be (per frame) to bound CPU usage.
MAX_FACES_PER_FRAME = 8


@dataclass
class EncodeResult:
    encoding: np.ndarray | None = None
    box: tuple | None = None  # (top, right, bottom, left) at full resolution
    ok: bool = False
    reason: str = ""
    blur_variance: float = 0.0


@dataclass
class FaceMatch:
    name: str
    distance: float
    confidence: float
    box: tuple


def face_box_size(box):
    top, right, bottom, left = box
    return right - left, bottom - top


def _laplacian_variance(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _encode_from_image(img):
    """Detect + encode the first face at full resolution.

    Returns (encoding, box). Raises ValueError when no face is present.
    """
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    boxes = face_recognition.face_locations(rgb, model="hog")
    if not boxes:
        raise ValueError("No face detected")
    box = boxes[0]
    encodings = face_recognition.face_encodings(rgb, [box])
    if not encodings:
        raise ValueError("No face detected")
    return encodings[0], box


def assess_enrollment_quality(img, box, min_face_size, min_blur_variance):
    """Return list of issue strings for an enrollment photo (or empty list)."""
    issues = []
    top, right, bottom, left = box
    w = right - left
    h = bottom - top
    if min(w, h) < min_face_size:
        issues.append(
            f"Face too small ({w}x{h}px). Get closer to the camera (min ~{min_face_size}px)."
        )
    blur = _laplacian_variance(img)
    if blur < min_blur_variance:
        issues.append("Photo is blurry. Use a sharper image with steady hands.")
    return issues


def encode_enrollment_image(img, min_face_size, min_blur_variance):
    """Encode an enrollment image, returning EncodeResult."""
    try:
        if img is None:
            return EncodeResult(reason="Could not decode image")
        encoding, box = _encode_from_image(img)
    except ValueError as exc:
        return EncodeResult(reason=str(exc))
    issues = assess_enrollment_quality(img, box, min_face_size, min_blur_variance)
    if issues:
        return EncodeResult(reason="; ".join(issues), blur_variance=_laplacian_variance(img))
    return EncodeResult(encoding=encoding, box=box, ok=True)


class RecognitionService:
    """Holds per-user encodings in a thread-safe cache and provides matching.

    The cache is invalidated whenever a user's enrollments change.
    """

    def __init__(self):
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._history = defaultdict(list)
        self._history_lock = threading.Lock()

    def invalidate(self, user_id):
        with self._cache_lock:
            self._cache.pop(user_id, None)

    def get_students(self, db, user_id):
        """Return {student_name: [encoding, ...]} loading from DB on cache miss."""
        with self._cache_lock:
            cached = self._cache.get(user_id)
        if cached is not None:
            return cached
        from .models import load_encodings

        data = load_encodings(db, user_id)
        with self._cache_lock:
            self._cache[user_id] = data
        return data

    def match(self, db, user_id, encoding, tolerance):
        """Return FaceMatch (best known student) or None."""
        students_data = self.get_students(db, user_id)
        if not students_data:
            return None
        best = None
        for name, encs in students_data.items():
            if not encs:
                continue
            dists = face_recognition.face_distance(encs, encoding)
            d = float(np.min(dists))
            if d <= tolerance and (best is None or d < best[1]):
                best = (name, d)
        if best is None:
            return None
        name, distance = best
        return FaceMatch(
            name=name,
            distance=round(distance, 4),
            confidence=round(max(0.0, min(1.0, 1.0 - distance)), 3),
            box=None,
        )

    def check_consistency(self, user_id, name, required, window):
        """Record a detection and return True when the student is considered
        'consistently present' (required detections within the window)."""
        now = time.time()
        with self._history_lock:
            key = (user_id, name)
            recent = [t for t in self._history[key] if now - t < window]
            recent.append(now)
            # Bound memory: keep at most the last `required * 2` timestamps.
            del recent[: -required * 2]
            self._history[key] = recent
            consistent = len(recent) >= required
        if consistent:
            with self._history_lock:
                self._history.pop(key, None)
        return consistent

    def reset_history(self, user_id):
        with self._history_lock:
            for key in list(self._history.keys()):
                if key[0] == user_id:
                    del self._history[key]


def recognize_frame(service, db, user_id, img, tolerance, consistency_frames,
                    consistency_window, max_faces=MAX_FACES_PER_FRAME):
    """Detect faces in `img` (BGR), match against the user's encodings.

    Returns a list of dicts:
      {name, top, right, bottom, left, confidence, distance}
    and a list of names whose attendance was newly marked.
    """
    from . import models

    h, w = img.shape[:2]
    scale = 1.0
    work_img = img
    if max(h, w) > 1280:
        scale = 1280.0 / max(h, w)
        work_img = cv2.resize(img, (int(w * scale), int(h * scale)))

    rgb_small = cv2.cvtColor(work_img, cv2.COLOR_BGR2RGB)
    boxes = face_recognition.face_locations(rgb_small, model="hog")[:max_faces]
    if not boxes:
        return [], []

    # Encode at full resolution for accuracy.
    rgb_full = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    full_boxes = [(int(b[0] / scale), int(b[1] / scale), int(b[2] / scale), int(b[3] / scale))
                  for b in boxes]
    try:
        encodings = face_recognition.face_encodings(rgb_full, full_boxes)
    except Exception:
        # A malformed box can make encoding fail for the whole frame; skip it
        # rather than failing the request.
        logger.exception("face encoding failed for user=%s", user_id)
        return [], []

    results = []
    marked = []
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    time_str = today.strftime("%H:%M:%S")

    for box, encoding in zip(full_boxes, encodings):
        match = service.match(db, user_id, encoding, tolerance)
        if match is None:
            results.append({
                "name": "UNKNOWN",
                "top": box[0], "right": box[1], "bottom": box[2], "left": box[3],
                "confidence": 0.0, "distance": None,
            })
            continue
        consistent = service.check_consistency(
            user_id, match.name, consistency_frames, consistency_window
        )
        if consistent:
            inserted = models.mark_attendance(
                db, user_id, match.name, date_str, time_str, source="camera"
            )
            if inserted:
                marked.append(match.name)
        results.append({
            "name": match.name,
            "top": box[0], "right": box[1], "bottom": box[2], "left": box[3],
            "confidence": match.confidence, "distance": match.distance,
        })
    return results, marked
