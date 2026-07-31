"""Main page routes (dashboard, enroll)."""

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)


@bp.route("/enroll")
@login_required
def enroll_page():
    return render_template("enroll.html", user=current_user)
