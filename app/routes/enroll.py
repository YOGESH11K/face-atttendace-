"""Enrollment routes: capture, upload, list, view and delete photos."""

import logging
import os
import uuid
from datetime import datetime
from functools import wraps

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_login import current_user, login_required

from .. import limiter, recognition_service
from ..models import (
    add_encoding,
    count_photos_for_student,
    delete_photo,
    list_photos,
    upsert_student,
    user_enroll_dir,
)
from ..utils import ValidationError, allowed_file, sanitize_dir_name, validate_student_name

logger = logging.getLogger(__name__)

bp = Blueprint("enroll", __name__, url_prefix="/api/enroll")


def _login_required_api(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def _photo_path(user_dir, student_name, filename):
    """Resolve a photo file path safely within the user's enrollment dir."""
    from ..utils import safe_path_join

    name = sanitize_dir_name(student_name)
    return safe_path_join(user_dir, name, filename)


def _save_photo(user_dir, student_name, img):
    """Save a BGR image for a student. Returns (relative_path, photo_id)."""
    name = sanitize_dir_name(student_name)
    sub = os.path.join(user_dir, name)
    os.makedirs(sub, exist_ok=True)
    photo_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
    path = os.path.join(sub, photo_id)
    cv2.imwrite(path, img)
    rel = os.path.join(name, photo_id)
    return rel, photo_id


def _process_enrollment(db, user_id, student_name, img, user_dir):
    """Encode, quality-check and persist a new enrollment photo.

    Returns (message, count) or raises ValidationError.
    """
    cfg = current_app.config
    result = _encode_for_enrollment(img, cfg)
    if not result["ok"]:
        raise ValidationError(result["reason"])

    existing = count_photos_for_student(db, user_id, student_name)
    if existing >= cfg["MAX_PHOTOS_PER_STUDENT"]:
        raise ValidationError(
            f"Maximum of {cfg['MAX_PHOTOS_PER_STUDENT']} photos per student reached."
        )

    upsert_student(db, user_id, student_name)
    rel_path, photo_id = _save_photo(user_dir, student_name, img)
    add_encoding(db, user_id, student_name, result["encoding"], rel_path)
    recognition_service.invalidate(user_id)
    return f"{student_name}: photo {existing + 1} added", existing + 1


def _encode_for_enrollment(img, cfg):
    from ..recognition import encode_enrollment_image

    result = encode_enrollment_image(
        img,
        min_face_size=cfg["MIN_FACE_SIZE"],
        min_blur_variance=cfg["MIN_BLUR_VARIANCE"],
    )
    if not result.ok:
        return {"ok": False, "reason": result.reason}
    return {"ok": True, "encoding": result.encoding}


def _decode_uploaded(file_storage):
    img_bytes = file_storage.read()
    nparr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    return nparr


@bp.post("/capture")
@_login_required_api
@limiter.limit("30/minute")
def api_enroll_capture():
    db = current_app.db
    data = request.get_json(silent=True) or {}
    try:
        student_name = validate_student_name(data.get("student_name"))
        from .api import _decode_image

        img = _decode_image(data.get("image"))
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    user_dir = user_enroll_dir(current_app.config["DATA_DIR"], current_user.id)
    try:
        message, count = _process_enrollment(db, current_user.id, student_name, img, user_dir)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "success", "message": message, "total": count})


@bp.post("/upload")
@_login_required_api
@limiter.limit("30/minute")
def api_enroll_upload():
    db = current_app.db
    try:
        student_name = validate_student_name(request.form.get("student_name"))
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "No file provided"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    img = _decode_uploaded(file)
    if img is None:
        return jsonify({"error": "Could not decode image"}), 400

    user_dir = user_enroll_dir(current_app.config["DATA_DIR"], current_user.id)
    try:
        message, count = _process_enrollment(db, current_user.id, student_name, img, user_dir)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "success", "message": message, "total": count})


@bp.get("/status")
@_login_required_api
def api_enroll_status():
    db = current_app.db
    photos = list_photos(db, current_user.id)
    students = {}
    for p in photos:
        students[p["student"]] = students.get(p["student"], 0) + 1
    return jsonify({
        "enrolled": len(photos) > 0,
        "photos": len(photos),
        "students": students,
    })


@bp.get("/photos")
@_login_required_api
def api_enroll_photos():
    db = current_app.db
    photos = list_photos(db, current_user.id)
    items = [
        {
            "id": os.path.basename(p["photo_path"]),
            "student": p["student"],
            "url": f"/api/enroll/photo/{p['student']}/{os.path.basename(p['photo_path'])}",
        }
        for p in photos
    ]
    return jsonify({"photos": items})


@bp.get("/photo/<student>/<photo_id>")
@login_required
def api_enroll_photo(student, photo_id):
    user_dir = user_enroll_dir(current_app.config["DATA_DIR"], current_user.id)
    try:
        name = sanitize_dir_name(student)
        path = _photo_path(user_dir, name, photo_id)
    except ValidationError:
        return jsonify({"error": "invalid path"}), 400
    if not os.path.exists(path):
        return jsonify({"error": "not found"}), 404
    return send_file(path, mimetype="image/jpeg")


@bp.delete("/photo/<student>/<photo_id>")
@_login_required_api
def api_enroll_delete(student, photo_id):
    db = current_app.db
    user_dir = user_enroll_dir(current_app.config["DATA_DIR"], current_user.id)
    try:
        name = sanitize_dir_name(student)
        path = _photo_path(user_dir, name, photo_id)
    except ValidationError:
        return jsonify({"error": "invalid path"}), 400
    rel = os.path.join(name, photo_id)
    removed = delete_photo(db, current_user.id, rel)
    if removed and os.path.exists(path):
        os.remove(path)
        recognition_service.invalidate(current_user.id)
    return jsonify({"status": "deleted" if removed else "not found"})
