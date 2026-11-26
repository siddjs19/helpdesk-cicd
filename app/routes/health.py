"""Operational endpoints used by Docker, Kubernetes and CI smoke tests.

* /healthz  – liveness: is the process alive?
* /readyz   – readiness: has the store finished seeding?
* /metrics  – Prometheus text exposition (no extra dependency needed)
* /version  – build metadata injected at image build time
"""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify

from ..store import InMemoryStore

bp = Blueprint("health", __name__)


def _store() -> InMemoryStore:
    return current_app.extensions["store"]


@bp.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


@bp.get("/readyz")
def readyz():
    store = _store()
    payload = store.health()
    code = 200 if payload["ready"] else 503
    return jsonify({"status": "ready" if payload["ready"] else "starting", **payload}), code


@bp.get("/version")
def version():
    return jsonify(
        {
            "service": "campus-it-helpdesk",
            "version": current_app.config["APP_VERSION"],
            "git_sha": current_app.config["GIT_SHA"],
            "build_time": current_app.config["BUILD_TIME"],
            "environment": current_app.config["ENVIRONMENT"],
        }
    )


@bp.get("/metrics")
def metrics():
    store = _store()
    stats = store.analytics()
    lines: list[str] = []

    lines.append("# HELP helpdesk_tickets_total Number of tickets by status.")
    lines.append("# TYPE helpdesk_tickets_total gauge")
    for row in stats["by_status"]:
        lines.append(f'helpdesk_tickets_total{{status="{row["label"]}"}} {row["count"]}')

    lines.append("# HELP helpdesk_tickets_by_category Number of tickets by category.")
    lines.append("# TYPE helpdesk_tickets_by_category gauge")
    for row in stats["by_category"]:
        lines.append(f'helpdesk_tickets_by_category{{category="{row["label"]}"}} {row["count"]}')

    lines.append("# HELP helpdesk_sla_breached_open Tickets open past their SLA target.")
    lines.append("# TYPE helpdesk_sla_breached_open gauge")
    lines.append(f"helpdesk_sla_breached_open {stats['totals']['sla_breached_open']}")

    lines.append("# HELP helpdesk_resolution_hours_average Mean time to resolve.")
    lines.append("# TYPE helpdesk_resolution_hours_average gauge")
    lines.append(f"helpdesk_resolution_hours_average {stats['resolution']['avg_hours']}")

    lines.append("# HELP helpdesk_sla_compliance_ratio Share of resolved tickets inside SLA (0-1).")
    lines.append("# TYPE helpdesk_sla_compliance_ratio gauge")
    lines.append(f"helpdesk_sla_compliance_ratio {stats['resolution']['sla_compliance_pct'] / 100}")

    lines.append("# HELP helpdesk_build_info Build metadata as labels.")
    lines.append("# TYPE helpdesk_build_info gauge")
    version = current_app.config["APP_VERSION"]
    git_sha = current_app.config["GIT_SHA"]
    environment = current_app.config["ENVIRONMENT"]
    lines.append(
        f'helpdesk_build_info{{version="{version}",git_sha="{git_sha}",environment="{environment}"}} 1'
    )
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")
