"""Auth routes: login, register, logout."""

import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from werkzeug.security import check_password_hash

from .. import limiter
from ..database import users
from ..models import create_user, get_user_by_username
from ..utils import ValidationError, validate_display_name, validate_password, validate_school, validate_username

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


def _user_password_hash(user_id):
    db = current_app.db
    return db.session.execute(
        select(users.c.password_hash).where(users.c.id == user_id)
    ).scalar()


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        db = current_app.db
        user = get_user_by_username(db, username)
        if user and check_password_hash(_user_password_hash(user.id), password):
            login_user(user, remember=False)
            # Honor PERMANENT_SESSION_LIFETIME (session cookie otherwise dies
            # with the browser).
            session.permanent = True
            logger.info("user=%s login ok", user.username)
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password", "error")
        return render_template("login.html")
    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5/hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if not current_app.config["ALLOW_REGISTRATION"]:
        flash("Self-service registration is disabled. Contact your administrator.", "error")
        return render_template("register.html")
    if request.method == "POST":
        try:
            username = validate_username(request.form.get("username"))
            display_name = validate_display_name(request.form.get("display_name"))
            school = validate_school(request.form.get("school"))
            validate_password(
                request.form.get("password") or "",
                request.form.get("confirm_password") or "",
            )
        except ValidationError as exc:
            flash(str(exc), "error")
            return render_template("register.html")

        db = current_app.db
        if get_user_by_username(db, username):
            flash("Username already exists", "error")
            return render_template("register.html")

        role = (
            "admin"
            if username in current_app.config["ADMIN_USERNAMES"]
            else "teacher"
        )
        user_id = create_user(db, username, request.form["password"], display_name, school, role=role)
        if user_id is None:
            flash("Username already exists", "error")
            return render_template("register.html")
        logger.info("user=%s registered role=%s", username, role)
        flash("Registration successful! Please login.", "success")
        return redirect(url_for("auth.login"))
    return render_template("register.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
