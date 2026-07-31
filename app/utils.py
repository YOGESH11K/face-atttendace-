"""Validation and small shared helpers."""

import re
from pathlib import Path


USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")
STUDENT_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9 .'\-]{0,49}$")
DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9 .'\-]{2,64}$")
SCHOOL_RE = re.compile(r"^[A-Za-z0-9 .,'\-&]{0,128}$")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


class ValidationError(Exception):
    """Raised when user input is invalid. Carries a user-facing message."""


def validate_username(value):
    value = (value or "").strip().lower()
    if not USERNAME_RE.match(value):
        raise ValidationError(
            "Username must be 3-32 characters (letters, digits, underscore only)."
        )
    return value


def validate_display_name(value):
    value = (value or "").strip()
    if not DISPLAY_NAME_RE.match(value):
        raise ValidationError("Display name must be 2-64 letters, digits, spaces or .'-")
    return value


def validate_school(value):
    value = (value or "").strip()
    if value and not SCHOOL_RE.match(value):
        raise ValidationError("School name contains invalid characters.")
    return value


def validate_password(password, confirm):
    if password != confirm:
        raise ValidationError("Passwords do not match.")
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        raise ValidationError("Password must contain at least one letter and one number.")
    if len(password) > 128:
        raise ValidationError("Password is too long (max 128 characters).")
    return password


def validate_student_name(value):
    value = (value or "").strip().upper()
    if not STUDENT_NAME_RE.match(value):
        raise ValidationError(
            "Student name must be 1-50 letters/numbers (letters, digits, spaces, .-' allowed)."
        )
    return value


def sanitize_dir_name(value):
    """Safe, filesystem-friendly folder name derived from a student name."""
    safe = re.sub(r"[^A-Z0-9._\- ]", "", value).strip()
    return safe or "student"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_path_join(base_dir, *parts):
    """Join parts and ensure the result stays within base_dir."""
    base = Path(base_dir).resolve()
    candidate = base.joinpath(*parts).resolve()
    if not candidate.is_relative_to(base):
        raise ValidationError("Invalid path.")
    return candidate


def parse_boolean(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")
