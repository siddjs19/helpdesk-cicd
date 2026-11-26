"""Server-rendered pages: dashboard, ticket list, ticket detail, analytics."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..models import CATEGORIES, PRIORITIES, STATUSES, TRANSITIONS, Ticket
from ..security import current_user, login_required, role_required
from ..store import (
    ConflictError,
    InMemoryStore,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

bp = Blueprint("views", __name__)


def _store() -> InMemoryStore:
    return current_app.extensions["store"]


def _get_visible_ticket(ticket_id: str) -> Ticket:
    """Fetch a ticket, enforcing that the current user may see it."""
    user = current_user()
    store = _store()
    try:
        ticket = store.get_ticket(ticket_id)
    except NotFoundError:
        abort(404)
    if user.role not in ("admin", "technician") and ticket.requester_id != user.id:
        abort(403)
    return ticket


def _form_context(form: dict | None = None) -> dict:
    return {
        "categories": CATEGORIES,
        "priorities": PRIORITIES,
        "statuses": STATUSES,
        "technicians": sorted(_store().technicians(), key=lambda u: u.name),
        "form": form or {},
    }


@bp.get("/")
def index():
    if current_user() is None:
        return redirect(url_for("auth.login"))
    return redirect(url_for("views.dashboard"))


@bp.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    store = _store()
    stats = store.analytics()
    visible = store.list_tickets(user)
    recent = visible[:8]
    my_queue = [t for t in visible if t.assignee_id == user.id and t.is_open()]
    unassigned = [t for t in visible if t.assignee_id is None and t.is_open()]
    return render_template(
        "dashboard.html",
        stats=stats,
        recent=recent,
        my_queue=my_queue,
        unassigned=unassigned,
        user=user,
    )


@bp.get("/tickets")
@login_required
def tickets():
    user = current_user()
    filters = {
        "status": request.args.get("status", ""),
        "category": request.args.get("category", ""),
        "priority": request.args.get("priority", ""),
        "search": request.args.get("q", ""),
        "assigned_to_me": request.args.get("mine") == "1",
    }
    try:
        rows = _store().list_tickets(
            user,
            status=filters["status"] or None,
            category=filters["category"] or None,
            priority=filters["priority"] or None,
            search=filters["search"] or None,
            assigned_to_me=filters["assigned_to_me"],
        )
    except ValidationError as exc:
        flash(str(exc), "error")
        rows = _store().list_tickets(user)
    return render_template(
        "tickets.html",
        tickets=rows,
        filters=filters,
        categories=CATEGORIES,
        priorities=PRIORITIES,
        statuses=STATUSES,
        total=len(_store().visible_tickets(user)),
    )


@bp.get("/tickets/new")
@login_required
def new_ticket():
    return render_template("new_ticket.html", **_form_context())


@bp.post("/tickets")
@login_required
def create_ticket():
    user = current_user()
    payload = {
        "title": request.form.get("title", ""),
        "description": request.form.get("description", ""),
        "category": request.form.get("category", ""),
        "priority": request.form.get("priority", "Medium"),
        "location": request.form.get("location", ""),
    }
    try:
        ticket = _store().create_ticket(user, payload)
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("new_ticket.html", **_form_context(form=payload)), 400

    current_app.logger.info(
        "ticket_created",
        extra={"event": "ticket_created", "ticket_id": ticket.id, "user": user.email},
    )
    flash(f"Ticket {ticket.id} created. The IT team has been notified.", "success")
    return redirect(url_for("views.ticket_detail", ticket_id=ticket.id))


@bp.get("/tickets/<ticket_id>")
@login_required
def ticket_detail(ticket_id: str):
    ticket = _get_visible_ticket(ticket_id)
    user = current_user()
    if user.role in ("admin", "technician"):
        allowed = TRANSITIONS.get(ticket.status, ())
    elif ticket.status in ("Resolved", "Closed"):
        # A requester may only reopen their own resolved/closed ticket.
        allowed = ("Open",)
    else:
        allowed = ()
    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        payload=ticket.to_dict(_store().users),
        allowed=allowed,
        **_form_context(),
    )


@bp.post("/tickets/<ticket_id>/status")
@login_required
def change_status(ticket_id: str):
    user = current_user()
    new_status = request.form.get("status", "")
    try:
        ticket = _store().update_status(ticket_id, new_status, user)
    except NotFoundError:
        abort(404)
    except PermissionDeniedError:
        abort(403)
    except (ConflictError, ValidationError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("views.ticket_detail", ticket_id=ticket_id))
    flash(f"{ticket.id} moved to {ticket.status}.", "success")
    return redirect(url_for("views.ticket_detail", ticket_id=ticket_id))


@bp.post("/tickets/<ticket_id>/assign")
@role_required("admin", "technician")
def assign_ticket(ticket_id: str):
    user = current_user()
    raw = request.form.get("assignee_id", "")
    assignee_id = int(raw) if raw.isdigit() else None
    try:
        ticket = _store().assign(ticket_id, assignee_id, user)
    except NotFoundError:
        abort(404)
    except PermissionDeniedError:
        abort(403)
    except (ConflictError, ValidationError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("views.ticket_detail", ticket_id=ticket_id))
    target = _store().get_user(ticket.assignee_id)
    flash(f"{ticket.id} assigned to {target.name if target else 'nobody'}.", "success")
    return redirect(url_for("views.ticket_detail", ticket_id=ticket_id))


@bp.post("/tickets/<ticket_id>/comments")
@login_required
def add_comment(ticket_id: str):
    user = current_user()
    body = request.form.get("body", "")
    internal = request.form.get("internal") == "1" and user.role in ("admin", "technician")
    try:
        _store().add_comment(ticket_id, user, body, internal=internal)
    except NotFoundError:
        abort(404)
    except PermissionDeniedError:
        abort(403)
    except (ConflictError, ValidationError) as exc:
        flash(str(exc), "error")
    else:
        flash("Comment added.", "success")
    return redirect(url_for("views.ticket_detail", ticket_id=ticket_id))


@bp.get("/analytics")
@role_required("admin", "technician")
def analytics():
    return render_template("analytics.html", stats=_store().analytics())
