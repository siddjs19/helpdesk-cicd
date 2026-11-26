"""Login and logout routes (session based)."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from ..security import current_user
from ..store import InMemoryStore

bp = Blueprint("auth", __name__)


def _store() -> InMemoryStore:
    return current_app.extensions["store"]


@bp.get("/login")
def login():
    if current_user() is not None:
        return redirect(url_for("views.dashboard"))
    store = _store()
    return render_template(
        "login.html",
        demo_users=sorted(store.users.values(), key=lambda u: u.id),
        demo_password=current_app.config["DEMO_PASSWORD"],
    )


@bp.post("/login")
def login_submit():
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    user = _store().authenticate(email, password)
    if user is None:
        current_app.logger.info("login_failed", extra={"event": "login_failed", "user": email, "status": 401})
        flash("Invalid email or password. Try one of the demo accounts below.", "error")
        return render_template(
            "login.html",
            demo_users=sorted(_store().users.values(), key=lambda u: u.id),
            demo_password=current_app.config["DEMO_PASSWORD"],
            email=email,
        ), 401

    session.clear()
    session["user_id"] = user.id
    current_app.logger.info("login_success", extra={"event": "login_success", "user": user.email})
    target = request.args.get("next") or url_for("views.dashboard")
    if not target.startswith("/"):
        target = url_for("views.dashboard")
    return redirect(target)


@bp.post("/logout")
def logout():
    user = current_user()
    session.clear()
    if user is not None:
        current_app.logger.info("logout", extra={"event": "logout", "user": user.email})
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
