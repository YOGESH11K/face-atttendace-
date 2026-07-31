"""Authentication wiring (user_loader + unauthorized handler)."""

import logging

from . import login_manager
from .models import get_user_by_id

logger = logging.getLogger(__name__)


def register_auth(app, db):
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return get_user_by_id(db, int(user_id))
        except (TypeError, ValueError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify, redirect, request, url_for

        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("auth.login", next=request.full_path))
