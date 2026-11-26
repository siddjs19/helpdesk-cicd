"""Campus IT Helpdesk & Issue Management System — application factory."""

from __future__ import annotations

import time
import uuid

from flask import Flask, g, jsonify, render_template, request

from .config import Config
from .logging_setup import configure_logging
from .store import InMemoryStore

__version__ = "1.0.0"


def create_app(config_object: type | None = None, **overrides) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object or Config)
    app.config.update(overrides)

    configure_logging(app)

    app.extensions["store"] = InMemoryStore(
        seed_path=app.config["SEED_FILE"],
        demo_password=app.config["DEMO_PASSWORD"],
    )

    from . import security
    from .routes.api import bp as api_bp
    from .routes.auth import bp as auth_bp
    from .routes.health import bp as health_bp
    from .routes.views import bp as views_bp

    security.init_app(app)
    for blueprint in (auth_bp, views_bp, api_bp, health_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _start_timer():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        g.start_time = time.perf_counter()

    @app.after_request
    def _finish(response):
        started = getattr(g, "start_time", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started else 0.0
        response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        response.headers["X-Response-Time-ms"] = f"{duration_ms}"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        user = getattr(g, "user", None)
        app.logger.info(
            "request",
            extra={
                "event": "http_request",
                "request_id": getattr(g, "request_id", "-"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "user": user.email if user else "-",
            },
        )
        return response

    @app.context_processor
    def _inject_globals():
        from .security import csrf_token, current_user

        store: InMemoryStore = app.extensions["store"]
        user = current_user()
        counts = {}
        if user is not None:
            tickets = store.visible_tickets(user)
            counts = {
                "open": len([t for t in tickets if t.status == "Open"]),
                "in_progress": len([t for t in tickets if t.status == "In Progress"]),
                "mine": len([t for t in tickets if t.assignee_id == user.id and t.is_open()]),
            }
        return {
            "current_user": user,
            "csrf_token": csrf_token,
            "nav_counts": counts,
            "app_version": app.config["APP_VERSION"],
            "environment": app.config["ENVIRONMENT"],
        }

    def _wants_json() -> bool:
        return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"

    @app.errorhandler(400)
    def _bad_request(error):
        description = getattr(error, "description", "Bad request")
        if _wants_json():
            return jsonify({"error": {"code": 400, "message": description}}), 400
        return render_template("error.html", code=400, message=description), 400

    @app.errorhandler(403)
    def _forbidden(error):
        message = "You do not have permission to view this page."
        if _wants_json():
            return jsonify({"error": {"code": 403, "message": message}}), 403
        return render_template("error.html", code=403, message=message), 403

    @app.errorhandler(404)
    def _not_found(error):
        message = "The page or record you requested was not found."
        if _wants_json():
            return jsonify({"error": {"code": 404, "message": message}}), 404
        return render_template("error.html", code=404, message=message), 404

    @app.errorhandler(500)
    def _server_error(error):
        app.logger.exception("unhandled_error", extra={"event": "unhandled_error"})
        message = "Something went wrong on our side."
        if _wants_json():
            return jsonify({"error": {"code": 500, "message": message}}), 500
        return render_template("error.html", code=500, message=message), 500

    return app
