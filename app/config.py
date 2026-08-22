"""Application configuration loaded from environment variables."""

import os
from datetime import timedelta


def _env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Base configuration. All values can be overridden via environment."""

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        # Development-only fallback. NEVER use the default in production.
        "dev-only-insecure-secret-change-me",
    )

    # -- Database --
    # SQLite by default (file), or a full DATABASE_URL (e.g. postgresql://...)
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///database.db")

    # -- Storage --
    DATA_DIR = os.environ.get("DATA_DIR", "data")
    ENROLL_DIR_NAME = "enrollments"
    MAX_PHOTOS_PER_STUDENT = int(os.environ.get("MAX_PHOTOS_PER_STUDENT", "8"))
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB request body cap

    # -- Session / cookies --
    SESSION_COOKIE_HTTPONLY = True
    # Set to "None" (with HTTPS) when a separate frontend domain calls this API.
    _samesite = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax").strip().capitalize()
    SESSION_COOKIE_SAMESITE = _samesite if _samesite in ("Lax", "Strict", "None") else "Lax"
    # Secure cookies whenever running behind HTTPS (auto-enabled on Render, or
    # set explicitly with SESSION_COOKIE_SECURE=true).
    # SameSite=None requires Secure per modern browser rules.
    SESSION_COOKIE_SECURE = _env_bool(
        "SESSION_COOKIE_SECURE",
        os.environ.get("RENDER") == "true" or SESSION_COOKIE_SAMESITE == "None",
    )
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.environ.get("SESSION_DAYS", "7")))
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    # -- Cross-origin API access (separate SPA frontend) --
    # Comma-separated list of origins allowed to call the API with credentials,
    # e.g. "https://empirerecorgination.vercel.app". Empty disables CORS.
    CORS_ALLOWED_ORIGINS = {
        o.strip().rstrip("/")
        for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    }

    # -- CSRF --
    WTF_CSRF_TIME_LIMIT = int(os.environ.get("WTF_CSRF_TIME_LIMIT", "28800"))  # 8h
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    # -- Account policy --
    # When False, self-service registration is disabled (accounts must be
    # provisioned by an admin). Usernames listed here (comma-separated) are
    # auto-promoted to the `admin` role on registration/login.
    ALLOW_REGISTRATION = _env_bool("ALLOW_REGISTRATION", True)
    ADMIN_USERNAMES = {
        u.strip().lower()
        for u in os.environ.get("ADMIN_USERNAMES", "").split(",")
        if u.strip()
    }

    # -- Recognition --
    FACE_TOLERANCE = float(os.environ.get("FACE_TOLERANCE", "0.5"))
    CONSISTENCY_FRAMES = int(os.environ.get("CONSISTENCY_FRAMES", "3"))
    CONSISTENCY_WINDOW_SECONDS = float(os.environ.get("CONSISTENCY_WINDOW_SECONDS", "6"))
    MIN_FACE_SIZE = int(os.environ.get("MIN_FACE_SIZE", "110"))  # min box width (px)
    MIN_BLUR_VARIANCE = float(os.environ.get("MIN_BLUR_VARIANCE", "40.0"))
    MAX_IMAGE_DIMENSION = int(os.environ.get("MAX_IMAGE_DIMENSION", "1600"))

    # -- Rate limiting (in-memory, per process) --
    RATELIMIT_DEFAULT = "120/minute"
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # -- Logging --
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class TestConfig(Config):
    TESTING = True
    DATABASE_URL = os.environ.get(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )
    DATA_DIR = os.environ.get("TEST_DATA_DIR", "test_data")
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SECRET_KEY = "test-secret"
