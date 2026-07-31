"""Application factory, extensions, error handlers, security headers, logging."""

import logging
import os
import time
import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from werkzeug.exceptions import (
    BadRequest,
    Forbidden,
    HTTPException,
    NotFound,
    RequestEntityTooLarge,
    Unauthorized,
)

from .config import Config
from .database import Database

# Shared per-process recognition service. Module-level so blueprints can do
# `from .. import recognition_service` (the value is also attached to the
# Flask app extensions for convenience).
from .recognition import RecognitionService  # noqa: E402

recognition_service = RecognitionService()


def _rate_key():
    """Default rate-limit key: per authenticated user, else per IP."""
    from flask_login import current_user

    if current_user and current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=_rate_key, default_limits=["120/minute"])


def _configure_logging(app):
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app.logger.setLevel(level)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def _request_logging(app):
    @app.before_request
    def start_request():
        request.environ["_start_time"] = time.perf_counter()
        request.environ["_request_id"] = uuid.uuid4().hex[:12]

    @app.after_request
    def log_request(response):
        start = request.environ.get("_start_time")
        duration_ms = (time.perf_counter() - start) * 1000 if start else 0
        rid = request.environ.get("_request_id", "-")
        app.logger.info(
            "req_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            rid, request.method, request.path, response.status_code, duration_ms,
        )
        return response


def _security_headers(app):
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["Content-Security-Policy"] = csp
        return response


def render_error_page(title, message):
    from flask import render_template

    return render_template("error.html", title=title, message=message)


def _register_error_handlers(app):
    def is_api():
        return request.path.startswith("/api/")

    def json_error(message, status):
        return jsonify({"error": message}), status

    @app.errorhandler(Unauthorized)
    @app.errorhandler(Forbidden)
    @app.errorhandler(NotFound)
    @app.errorhandler(BadRequest)
    @app.errorhandler(RequestEntityTooLarge)
    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 400
        if is_api():
            return json_error(exc.description or exc.name, status)
        if status == 404:
            return render_error_page("Page Not Found",
                                     "The page you requested does not exist."), status
        return render_error_page(exc.name, exc.description or exc.name), status

    @app.errorhandler(500)
    def handle_500(exc):
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        if is_api():
            return json_error("Internal server error", 500)
        return render_error_page("Internal Server Error",
                                 "Something went wrong. Please try again later."), 500


def create_app(config_object=None):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )
    app.config.from_object(config_object or Config)

    if not os.path.isabs(app.config["DATA_DIR"]):
        app.config["DATA_DIR"] = os.path.join(project_root, app.config["DATA_DIR"])

    _configure_logging(app)

    db = Database(app.config["DATABASE_URL"])
    db.init_schema()
    app.db = db

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "error"

    csrf.init_app(app)
    limiter.init_app(app)

    app.extensions["recognition_service"] = recognition_service

    from .auth import register_auth
    from .routes.auth import bp as auth_bp
    from .routes.enroll import bp as enroll_bp
    from .routes.main import bp as main_bp
    from .routes.api import bp as api_bp

    register_auth(app, db)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(enroll_bp)

    _request_logging(app)
    _security_headers(app)
    _register_error_handlers(app)

    @app.before_request
    def _open_db_session():
        # create the request-scoped session (lazily on first access)
        _ = db.session

    @app.teardown_appcontext
    def _close_db_session(exc=None):
        db.close_session()

    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.route("/favicon.ico")
    def favicon():
        return app.response_class("", status=204)

    return app
