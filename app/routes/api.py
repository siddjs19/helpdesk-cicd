"""JSON API (v1) used by the test suite, the smoke test and future clients."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..models import CATEGORIES, PRIORITIES, STATUSES
from ..security import current_user, login_required, role_required
from ..store import (
    ConflictError,
    InMemoryStore,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _store() -> InMemoryStore:
    return current_app.extensions["store"]


def _error(code: int, message: str, field: str | None = None):
    payload = {"error": {"code": code, "message": message}}
    if field:
        payload["error"]["field"] = field
    return jsonify(payload), code


def _serialise(ticket):
    return ticket.to_dict(_store().users)


@bp.get("/meta")
def meta():
    """Public metadata: useful for clients and for smoke tests."""
    return jsonify(
        {
            "service": "campus-it-helpdesk",
            "version": current_app.config["APP_VERSION"],
            "categories": list(CATEGORIES),
            "priorities": list(PRIORITIES),
            "statuses": list(STATUSES),
        }
    )


@bp.get("/tickets")
@login_required
def list_tickets():
    user = current_user()
    try:
        rows = _store().list_tickets(
            user,
            status=request.args.get("status"),
            category=request.args.get("category"),
            priority=request.args.get("priority"),
            search=request.args.get("q"),
            assigned_to_me=request.args.get("mine") == "1",
        )
    except ValidationError as exc:
        return _error(400, str(exc), exc.field)
    return jsonify({"data": [_serialise(t) for t in rows], "meta": {"count": len(rows)}})


@bp.get("/tickets/<ticket_id>")
@login_required
def get_ticket(ticket_id: str):
    user = current_user()
    try:
        ticket = _store().get_ticket(ticket_id)
    except NotFoundError:
        return _error(404, f"Ticket {ticket_id} not found")
    if user.role not in ("admin", "technician") and ticket.requester_id != user.id:
        return _error(403, "You cannot view this ticket")
    return jsonify({"data": _serialise(ticket)})


@bp.post("/tickets")
@login_required
def create_ticket():
    user = current_user()
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        ticket = _store().create_ticket(user, payload)
    except ValidationError as exc:
        return _error(400, str(exc), exc.field)
    current_app.logger.info(
        "ticket_created", extra={"event": "ticket_created", "ticket_id": ticket.id, "user": user.email}
    )
    return jsonify({"data": _serialise(ticket)}), 201


@bp.patch("/tickets/<ticket_id>")
@login_required
def patch_ticket(ticket_id: str):
    user = current_user()
    payload = request.get_json(silent=True) or {}
    store = _store()
    try:
        ticket = store.get_ticket(ticket_id)
        if "status" in payload:
            ticket = store.update_status(ticket_id, payload["status"], user)
        if "assignee_id" in payload:
            raw = payload["assignee_id"]
            ticket = store.assign(ticket_id, int(raw) if raw is not None else None, user)
    except NotFoundError:
        return _error(404, f"Ticket {ticket_id} not found")
    except PermissionDeniedError as exc:
        return _error(403, str(exc))
    except ConflictError as exc:
        return _error(409, str(exc))
    except ValidationError as exc:
        return _error(400, str(exc), exc.field)
    return jsonify({"data": _serialise(ticket)})


@bp.post("/tickets/<ticket_id>/comments")
@login_required
def add_comment(ticket_id: str):
    user = current_user()
    payload = request.get_json(silent=True) or {}
    try:
        _store().add_comment(ticket_id, user, payload.get("body", ""), bool(payload.get("internal")))
    except NotFoundError:
        return _error(404, f"Ticket {ticket_id} not found")
    except PermissionDeniedError as exc:
        return _error(403, str(exc))
    except ConflictError as exc:
        return _error(409, str(exc))
    except ValidationError as exc:
        return _error(400, str(exc), exc.field)
    return jsonify({"data": _serialise(_store().get_ticket(ticket_id))}), 201


@bp.get("/analytics")
@role_required("admin", "technician")
def analytics():
    return jsonify({"data": _store().analytics()})
