"""Data access layer: user model + repository functions."""

import logging
import os

from flask_login import UserMixin
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .database import (
    attendance_records,
    face_encodings,
    students,
    users,
)

logger = logging.getLogger(__name__)


class User(UserMixin):
    def __init__(self, id, username, display_name, school, role="teacher"):
        self.id = id
        self.username = username
        self.display_name = display_name
        self.school = school
        self.role = role

    @property
    def is_teacher(self):
        return self.role in ("teacher", "admin")

    @property
    def is_admin(self):
        return self.role == "admin"


# ──────────────────────────────────────────────────────────────────────────
# Users
# ──────────────────────────────────────────────────────────────────────────

def get_user_by_username(db, username):
    row = db.session.execute(
        select(users).where(users.c.username == username)
    ).mappings().first()
    return _user_from_row(row)


def get_user_by_id(db, user_id):
    row = db.session.execute(
        select(users).where(users.c.id == user_id)
    ).mappings().first()
    return _user_from_row(row)


def _user_from_row(row):
    if row is None:
        return None
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        school=row["school"] or "",
        role=row.get("role") or "teacher",
    )


def create_user(db, username, password, display_name, school, role="teacher"):
    user = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "display_name": display_name,
        "school": school or "",
        "role": role,
    }
    sess = db.session
    try:
        result = sess.execute(users.insert().values(**user))
        sess.commit()
        return result.lastrowid
    except IntegrityError:
        sess.rollback()
        return None


def set_user_role(db, user_id, role):
    if role not in ("teacher", "admin"):
        return
    sess = db.session
    sess.execute(
        users.update().where(users.c.id == user_id).values(role=role)
    )
    sess.commit()


def list_users(db, include_password=False):
    """Return all accounts with per-user photo/attendance counts.

    Columns: id, username, display_name, school, role, created_at,
    photo_count, attendance_count, last_attendance.
    """
    photo_counts = db.session.execute(
        select(
            face_encodings.c.user_id,
            func.count(face_encodings.c.id).label("n"),
        ).group_by(face_encodings.c.user_id)
    ).all()
    attendance_counts = db.session.execute(
        select(
            attendance_records.c.user_id,
            func.count(attendance_records.c.id).label("n"),
        ).group_by(attendance_records.c.user_id)
    ).all()
    last_attendance = db.session.execute(
        select(
            attendance_records.c.user_id,
            attendance_records.c.date,
        )
        .order_by(attendance_records.c.date.desc())
    ).all()

    photos = dict(photo_counts)
    att_total = dict(attendance_counts)
    att_last: dict = {}
    for user_id, date_str in last_attendance:
        att_last.setdefault(user_id, date_str)

    rows = db.session.execute(
        select(
            users.c.id,
            users.c.username,
            users.c.display_name,
            users.c.school,
            users.c.role,
            users.c.created_at,
        ).order_by(users.c.id)
    ).all()
    result = []
    for r in rows:
        item = {
            "id": r.id,
            "username": r.username,
            "display_name": r.display_name,
            "school": r.school or "",
            "role": r.role or "teacher",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "photo_count": int(photos.get(r.id, 0)),
            "attendance_count": int(att_total.get(r.id, 0)),
            "last_attendance": att_last.get(r.id),
        }
        result.append(item)
    return result


def get_user_role(db, user_id):
    return db.session.execute(
        select(users.c.role).where(users.c.id == user_id)
    ).scalar() or "teacher"


# ──────────────────────────────────────────────────────────────────────────
# Students + face encodings
# ──────────────────────────────────────────────────────────────────────────

def upsert_student(db, user_id, student_name):
    """Return the stable student name (uppercased) ensuring a row exists."""
    sess = db.session
    try:
        sess.execute(
            students.insert().values(user_id=user_id, name=student_name)
        )
        sess.commit()
    except IntegrityError:
        sess.rollback()
    return student_name


def list_students(db, user_id):
    rows = db.session.execute(
        select(students.c.name).where(students.c.user_id == user_id).order_by(students.c.name)
    ).scalars().all()
    return list(rows)


def student_photo_counts(db, user_id):
    """{student_name: photo_count} for a user."""
    rows = db.session.execute(
        select(
            face_encodings.c.student_name,
            func.count(face_encodings.c.id).label("n"),
        )
        .where(face_encodings.c.user_id == user_id)
        .group_by(face_encodings.c.student_name)
    ).all()
    return {name: n for name, n in rows}


def load_encodings(db, user_id):
    """Load {student_name: [np.ndarray...]} for a user."""
    import numpy as np

    rows = db.session.execute(
        select(face_encodings.c.student_name, face_encodings.c.encoding)
        .where(face_encodings.c.user_id == user_id)
    ).all()
    data = {}
    for name, blob in rows:
        enc = np.frombuffer(blob, dtype=np.float32)
        data.setdefault(name, []).append(enc)
    return data


def add_encoding(db, user_id, student_name, encoding, photo_path):
    import numpy as np

    row = {
        "user_id": user_id,
        "student_name": student_name,
        "encoding": np.asarray(encoding, dtype=np.float32).tobytes(),
        "photo_path": photo_path,
    }
    sess = db.session
    sess.execute(face_encodings.insert().values(**row))
    sess.commit()


def count_photos_for_student(db, user_id, student_name):
    n = db.session.execute(
        select(func.count(face_encodings.c.id))
        .where(face_encodings.c.user_id == user_id)
        .where(face_encodings.c.student_name == student_name)
    ).scalar()
    return int(n or 0)


def delete_photo(db, user_id, photo_path):
    """Delete an encoding row by photo path. Returns True if a row was removed."""
    sess = db.session
    result = sess.execute(
        delete(face_encodings).where(
            face_encodings.c.user_id == user_id,
            face_encodings.c.photo_path == photo_path,
        )
    )
    sess.commit()
    return result.rowcount > 0


def list_photos(db, user_id):
    """Return [{student_name, photo_path, created_at}] ordered by recency."""
    rows = db.session.execute(
        select(
            face_encodings.c.student_name,
            face_encodings.c.photo_path,
            face_encodings.c.created_at,
        )
        .where(face_encodings.c.user_id == user_id)
        .order_by(face_encodings.c.id.desc())
    ).all()
    return [
        {"student": r.student_name, "photo_path": r.photo_path, "created_at": r.created_at}
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────────────────
# Attendance
# ──────────────────────────────────────────────────────────────────────────

def mark_attendance(db, user_id, student_name, date_str, time_str, source="camera"):
    """Atomically insert an attendance row. Duplicates are ignored.

    Returns True if a NEW record was inserted, False if already present.
    """
    from sqlalchemy.exc import IntegrityError

    sess = db.session
    try:
        sess.execute(
            attendance_records.insert().values(
                user_id=user_id,
                student_name=student_name,
                date=date_str,
                time=time_str,
                source=source,
            )
        )
        sess.commit()
        return True
    except IntegrityError:
        sess.rollback()
        return False


def attendance_stats(db, user_id, today):
    total = db.session.execute(
        select(func.count(attendance_records.c.id)).where(
            attendance_records.c.user_id == user_id
        )
    ).scalar()

    today_count = db.session.execute(
        select(func.count(attendance_records.c.id)).where(
            attendance_records.c.user_id == user_id,
            attendance_records.c.date == today,
        )
    ).scalar()

    today_list = list(
        db.session.execute(
            select(attendance_records.c.student_name)
            .where(
                attendance_records.c.user_id == user_id,
                attendance_records.c.date == today,
            )
            .distinct()
            .order_by(attendance_records.c.student_name)
        ).scalars().all()
    )
    return int(total or 0), int(today_count or 0), today_list


def list_attendance(db, user_id, limit=500, offset=0):
    rows = db.session.execute(
        select(
            attendance_records.c.student_name,
            attendance_records.c.date,
            attendance_records.c.time,
            attendance_records.c.source,
        )
        .where(attendance_records.c.user_id == user_id)
        .order_by(attendance_records.c.date.desc(), attendance_records.c.time.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {"Name": r.student_name, "Date": r.date, "Time": r.time, "Source": r.source}
        for r in rows
    ]


def weekly_counts(db, user_id):
    """Return {date: unique_students} used for the weekly trend chart."""
    rows = db.session.execute(
        select(
            attendance_records.c.date,
            func.count(func.distinct(attendance_records.c.student_name)),
        )
        .where(attendance_records.c.user_id == user_id)
        .group_by(attendance_records.c.date)
    ).all()
    return {d: n for d, n in rows}


def clear_attendance_on(db, user_id, date_str):
    sess = db.session
    sess.execute(
        attendance_records.delete().where(
            attendance_records.c.user_id == user_id,
            attendance_records.c.date == date_str,
        )
    )
    sess.commit()


# ──────────────────────────────────────────────────────────────────────────
# Paths (per-user storage directories)
# ──────────────────────────────────────────────────────────────────────────

def user_enroll_dir(data_dir, user_id):
    return os.path.join(data_dir, "enrollments", str(user_id))
