"""Session auth, role guards and CSRF protection."""

from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from .store import PermissionDeniedError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user():
    return g.get("user")


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def init_app(app) -> None:
    @app.before_request
    def _load_user():
        from .store import InMemoryStore  # local import avoids a cycle

        store: InMemoryStore = app.extensions["store"]
        g.user = store.get_user(session.get("user_id"))

    @app.before_request
    def _check_csrf():
        """Double-submit token check for browser form posts."""
        if not app.config.get("CSRF_ENABLED", True):
            return None
        if request.method in SAFE_METHODS or request.path.startswith("/api/"):
            return None
        if request.is_json:
            return None
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="CSRF token missing or invalid")
        return None

    @app.errorhandler(PermissionDeniedError)
    def _permission_denied(error):
        abort(403)
