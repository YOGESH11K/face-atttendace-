"""API routes: stats, attendance, weekly trend, recognition."""

import csv
import io
import logging
from datetime import datetime

import cv2
import numpy as np
from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import current_user

from .. import limiter, recognition_service
from ..utils import ValidationError

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")

WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _login_required_api(fn):
    from functools import wraps

    from flask_login import login_required

    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def _decode_image(data):
    """Decode a base64 image payload into a BGR ndarray."""
    import base64

    if not data:
        raise ValidationError("Missing image data")
    raw = data.split(",")[1] if "," in data else data
    try:
        nparr = np.frombuffer(base64.b64decode(raw, validate=True), np.uint8)
    except Exception:
        raise ValidationError("Invalid image encoding")
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValidationError("Could not decode image")
    return img


def _clamp_int(value, default, minimum, maximum):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, v))


@bp.get("/stats")
@_login_required_api
def api_stats():
    db = current_app.db
    today = datetime.now().strftime("%Y-%m-%d")
    from .. import models

    total, today_count, today_list = models.attendance_stats(db, current_user.id, today)
    photo_counts = models.student_photo_counts(db, current_user.id)
    return jsonify({
        "students": sorted(photo_counts.keys()),
        "student_count": len(photo_counts),
        "today_attendance": today_count,
        "total_records": total,
        "today_list": today_list,
        "username": current_user.display_name,
        "school": current_user.school,
    })


@bp.get("/attendance")
@_login_required_api
def api_attendance():
    db = current_app.db
    limit = _clamp_int(request.args.get("limit"), 500, 1, 5000)
    offset = _clamp_int(request.args.get("offset"), 0, 0, 10_000_000)
    from .. import models

    records = models.list_attendance(db, current_user.id, limit=limit, offset=offset)
    return jsonify({"records": records, "limit": limit, "offset": offset})


@bp.get("/attendance/export.csv")
@_login_required_api
def api_attendance_export():
    db = current_app.db
    from .. import models

    records = models.list_attendance(db, current_user.id, limit=50_000, offset=0)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "Date", "Time"])
    for r in records:
        writer.writerow([r["Name"], r["Date"], r["Time"]])
    csv_data = buffer.getvalue()
    filename = f"attendance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.get("/attendance/weekly")
@_login_required_api
def api_weekly():
    db = current_app.db
    from .. import models

    counts = models.weekly_counts(db, current_user.id)
    weekly = {day: 0 for day in WEEKDAY_ORDER}
    for date_str, n in counts.items():
        try:
            day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
        except ValueError:
            continue
        weekly[day_name] += n
    return jsonify({"weekly": weekly})


@bp.post("/attendance/clear_today")
@_login_required_api
def api_clear_today():
    db = current_app.db
    from .. import models

    today = datetime.now().strftime("%Y-%m-%d")
    models.clear_attendance_on(db, current_user.id, today)
    logger.info("user=%s cleared attendance for %s", current_user.username, today)
    return jsonify({"status": "cleared"})


@bp.post("/recognize")
@_login_required_api
@limiter.limit("120/minute")
def api_recognize():
    db = current_app.db
    data = request.get_json(silent=True) or {}
    try:
        img = _decode_image(data.get("image"))
        max_dim = current_app.config["MAX_IMAGE_DIMENSION"]
        if max(img.shape[0], img.shape[1]) > max_dim:
            scale = max_dim / max(img.shape[0], img.shape[1])
            img = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)))
    except ValidationError as exc:
        return jsonify({"error": str(exc), "faces": []}), 400

    try:
        from .. import recognition

        results, marked = recognition.recognize_frame(
            service=recognition_service,
            db=db,
            user_id=current_user.id,
            img=img,
            tolerance=current_app.config["FACE_TOLERANCE"],
            consistency_frames=current_app.config["CONSISTENCY_FRAMES"],
            consistency_window=current_app.config["CONSISTENCY_WINDOW_SECONDS"],
        )
    except Exception:
        logger.exception("recognition failed for user=%s", current_user.username)
        return jsonify({"error": "recognition error", "faces": []}), 500
    for name in marked:
        logger.info("user=%s attendance marked for %s", current_user.username, name)
    return jsonify({"faces": results, "marked": marked})
