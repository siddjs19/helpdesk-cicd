"""In-memory data store seeded with demo records (no database required).

A single process-wide store is attached to ``app.extensions["store"]``. All
mutating methods take a re-entrant lock so the app is safe under gunicorn
worker threads.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from .models import (
    CATEGORIES,
    PRIORITIES,
    PRIORITY_WEIGHT,
    ROLES,
    SLA_HOURS,
    STATUS_ORDER,
    STATUSES,
    TRANSITIONS,
    Comment,
    Ticket,
    User,
    utcnow,
)

# Hashing is deliberately slow, so compute one hash per distinct password.
_HASH_CACHE: dict[str, str] = {}


def hash_password(password: str) -> str:
    if password not in _HASH_CACHE:
        _HASH_CACHE[password] = generate_password_hash(password, method="pbkdf2:sha256:600000")
    return _HASH_CACHE[password]


class ValidationError(ValueError):
    """Raised when submitted data fails validation (HTTP 400)."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class NotFoundError(LookupError):
    """Raised when a record does not exist (HTTP 404)."""


class PermissionDeniedError(PermissionError):
    """Raised when a user may not perform an action (HTTP 403)."""


class ConflictError(RuntimeError):
    """Raised on an illegal state transition (HTTP 409)."""


class InMemoryStore:
    def __init__(
        self,
        seed_path: str | None = None,
        demo_password: str = "helpdesk123",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._clock = clock or utcnow
        self.users: dict[int, User] = {}
        self.tickets: dict[str, Ticket] = {}
        self._ticket_seq = 1000
        self._comment_seq = 0
        self.ready = False
        if seed_path:
            self.load_seed(seed_path, demo_password)

    # ------------------------------------------------------------------
    # seeding
    # ------------------------------------------------------------------
    def load_seed(self, path: str, demo_password: str) -> None:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        now = self._clock()
        with self._lock:
            for record in data["users"]:
                self.users[record["id"]] = User(
                    id=record["id"],
                    name=record["name"],
                    email=record["email"],
                    role=record["role"],
                    department=record.get("department", ""),
                    password_hash=hash_password(demo_password),
                )

            for record in data["tickets"]:
                created = now - timedelta(hours=record["age_hours"])
                resolved_at = None
                if record.get("resolved_age_hours") is not None:
                    resolved_at = now - timedelta(hours=record["resolved_age_hours"])
                self._ticket_seq += 1
                ticket_id = f"HD-{self._ticket_seq}"
                ticket = Ticket(
                    id=ticket_id,
                    title=record["title"],
                    description=record["description"],
                    category=record["category"],
                    priority=record["priority"],
                    status=record["status"],
                    requester_id=record["requester_id"],
                    location=record.get("location", ""),
                    assignee_id=record.get("assignee_id"),
                    created_at=created,
                    updated_at=resolved_at or created,
                    resolved_at=resolved_at,
                )
                ticket.history.append(
                    {
                        "at": ticket.created_at.isoformat().replace("+00:00", "Z"),
                        "actor": "system",
                        "event": "created",
                        "detail": f"Seeded demo ticket ({ticket.priority})",
                    }
                )
                if ticket.assignee_id:
                    ticket.history.append(
                        {
                            "at": created.isoformat().replace("+00:00", "Z"),
                            "actor": "system",
                            "event": "assigned",
                            "detail": f"Assigned to user #{ticket.assignee_id}",
                        }
                    )
                if resolved_at:
                    ticket.history.append(
                        {
                            "at": resolved_at.isoformat().replace("+00:00", "Z"),
                            "actor": "system",
                            "event": "status",
                            "detail": f"Marked {ticket.status}",
                        }
                    )
                for comment in record.get("comments", []):
                    self._comment_seq += 1
                    ticket.comments.append(
                        Comment(
                            id=self._comment_seq,
                            author_id=comment["author_id"],
                            body=comment["body"],
                            created_at=created + timedelta(hours=comment.get("after_hours", 1)),
                        )
                    )
                self.tickets[ticket_id] = ticket
        self.ready = True

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    def authenticate(self, email: str, password: str) -> User | None:
        email = (email or "").strip().lower()
        for user in self.users.values():
            if user.email.lower() == email and check_password_hash(user.password_hash, password or ""):
                return user
        return None

    def get_user(self, user_id: int | None) -> User | None:
        return self.users.get(user_id) if user_id is not None else None

    def technicians(self) -> list[User]:
        return [u for u in self.users.values() if u.role in ("technician", "admin")]

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def get_ticket(self, ticket_id: str) -> Ticket:
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        return ticket

    def visible_tickets(self, user: User) -> list[Ticket]:
        """Role-based visibility: requesters see their own, staff see the queue."""
        if user.role in ("admin", "technician"):
            return list(self.tickets.values())
        return [t for t in self.tickets.values() if t.requester_id == user.id]

    def list_tickets(
        self,
        user: User,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        assigned_to_me: bool = False,
    ) -> list[Ticket]:
        tickets = self.visible_tickets(user)
        if status:
            if status not in STATUSES:
                raise ValidationError(f"Unknown status '{status}'", "status")
            tickets = [t for t in tickets if t.status == status]
        if category:
            tickets = [t for t in tickets if t.category == category]
        if priority:
            tickets = [t for t in tickets if t.priority == priority]
        if assigned_to_me:
            tickets = [t for t in tickets if t.assignee_id == user.id]
        if search:
            needle = search.strip().lower()
            tickets = [
                t
                for t in tickets
                if needle in t.title.lower()
                or needle in t.description.lower()
                or needle in t.id.lower()
                or needle in t.location.lower()
            ]
        return sorted(
            tickets,
            key=lambda t: (STATUS_ORDER[t.status], PRIORITY_WEIGHT[t.priority], -t.created_at.timestamp()),
        )

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def create_ticket(self, requester: User, payload: dict[str, Any]) -> Ticket:
        title = (payload.get("title") or "").strip()
        description = (payload.get("description") or "").strip()
        category = payload.get("category")
        priority = payload.get("priority", "Medium")
        location = (payload.get("location") or "").strip()

        if len(title) < 5:
            raise ValidationError("Title must be at least 5 characters", "title")
        if len(title) > 120:
            raise ValidationError("Title must be 120 characters or fewer", "title")
        if len(description) < 10:
            raise ValidationError("Description must be at least 10 characters", "description")
        if category not in CATEGORIES:
            raise ValidationError("Choose a valid category", "category")
        if priority not in PRIORITIES:
            raise ValidationError("Choose a valid priority", "priority")

        now = self._clock()
        with self._lock:
            self._ticket_seq += 1
            ticket = Ticket(
                id=f"HD-{self._ticket_seq}",
                title=title,
                description=description,
                category=category,
                priority=priority,
                status="Open",
                requester_id=requester.id,
                location=location,
                created_at=now,
                updated_at=now,
            )
            ticket.history.append(
                {
                    "at": now.isoformat().replace("+00:00", "Z"),
                    "actor": requester.name,
                    "event": "created",
                    "detail": f"Ticket raised with {priority} priority",
                }
            )
            self.tickets[ticket.id] = ticket
        return ticket

    def update_status(self, ticket_id: str, new_status: str, actor: User) -> Ticket:
        if new_status not in STATUSES:
            raise ValidationError(f"Unknown status '{new_status}'", "status")
        with self._lock:
            ticket = self.get_ticket(ticket_id)
            self._assert_can_edit(ticket, actor)
            if new_status == ticket.status:
                return ticket
            allowed = TRANSITIONS.get(ticket.status, ())
            if new_status not in allowed:
                raise ConflictError(f"Cannot move ticket from '{ticket.status}' to '{new_status}'")
            now = self._clock()
            previous = ticket.status
            ticket.status = new_status
            ticket.updated_at = now
            if new_status == "Resolved":
                ticket.resolved_at = now
            elif previous == "Resolved":
                ticket.resolved_at = None
            ticket.history.append(
                {
                    "at": now.isoformat().replace("+00:00", "Z"),
                    "actor": actor.name,
                    "event": "status",
                    "detail": f"{previous} -> {new_status}",
                }
            )
            return ticket

    def assign(self, ticket_id: str, assignee_id: int | None, actor: User) -> Ticket:
        with self._lock:
            ticket = self.get_ticket(ticket_id)
            if actor.role not in ("admin", "technician"):
                raise PermissionDeniedError("Only staff can assign tickets")
            if assignee_id is not None:
                assignee = self.get_user(assignee_id)
                if assignee is None or assignee.role not in ("technician", "admin"):
                    raise ValidationError("Assignee must be a technician or admin", "assignee_id")
                if ticket.status == "Closed":
                    raise ConflictError("Closed tickets cannot be reassigned")
            now = self._clock()
            ticket.assignee_id = assignee_id
            ticket.updated_at = now
            if ticket.status == "Open" and assignee_id is not None:
                ticket.status = "In Progress"
                ticket.history.append(
                    {
                        "at": now.isoformat().replace("+00:00", "Z"),
                        "actor": actor.name,
                        "event": "status",
                        "detail": "Open -> In Progress (on assignment)",
                    }
                )
            name = self.users[assignee_id].name if assignee_id else "nobody"
            ticket.history.append(
                {
                    "at": now.isoformat().replace("+00:00", "Z"),
                    "actor": actor.name,
                    "event": "assigned",
                    "detail": f"Assigned to {name}",
                }
            )
            return ticket

    def add_comment(self, ticket_id: str, actor: User, body: str, internal: bool = False) -> Ticket:
        body = (body or "").strip()
        if len(body) < 2:
            raise ValidationError("Comment cannot be empty", "body")
        if len(body) > 1000:
            raise ValidationError("Comment must be 1000 characters or fewer", "body")
        with self._lock:
            ticket = self.get_ticket(ticket_id)
            if actor.role not in ("admin", "technician") and ticket.requester_id != actor.id:
                raise PermissionDeniedError("You cannot comment on this ticket")
            if ticket.status == "Closed":
                raise ConflictError("This ticket is closed; reopen it to comment")
            now = self._clock()
            self._comment_seq += 1
            ticket.comments.append(
                Comment(
                    id=self._comment_seq, author_id=actor.id, body=body, created_at=now, internal=internal
                )
            )
            ticket.updated_at = now
            return ticket

    def _assert_can_edit(self, ticket: Ticket, actor: User) -> None:
        if actor.role in ("admin", "technician"):
            return
        # Requesters may only reopen their own resolved ticket.
        if ticket.requester_id == actor.id and ticket.status in ("Resolved", "Closed"):
            return
        raise PermissionDeniedError("You are not allowed to change this ticket's status")

    # ------------------------------------------------------------------
    # analytics
    # ------------------------------------------------------------------
    def analytics(self) -> dict[str, Any]:
        now = self._clock()
        tickets = list(self.tickets.values())

        by_status = Counter(t.status for t in tickets)
        by_category = Counter(t.category for t in tickets)
        by_priority = Counter(t.priority for t in tickets)

        resolved = [t for t in tickets if t.resolved_at]
        resolution_hours = [t.resolution_hours() for t in resolved]
        avg_resolution = round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else 0.0

        open_tickets = [t for t in tickets if t.is_open()]
        breached_open = [t for t in open_tickets if t.sla_breached(now)]
        met = [t for t in resolved if not t.sla_breached(now)]
        sla_compliance = round(100 * len(met) / len(resolved), 1) if resolved else 100.0

        workload = []
        for user in self.technicians():
            assigned = [t for t in open_tickets if t.assignee_id == user.id]
            workload.append(
                {
                    "name": user.name,
                    "role": user.role,
                    "open": len(assigned),
                    "critical": len([t for t in assigned if t.priority == "Critical"]),
                }
            )
        workload.sort(key=lambda row: row["open"], reverse=True)

        oldest = sorted(open_tickets, key=lambda t: t.created_at)[:5]

        return {
            "totals": {
                "all": len(tickets),
                "open": by_status.get("Open", 0),
                "in_progress": by_status.get("In Progress", 0),
                "resolved": by_status.get("Resolved", 0),
                "closed": by_status.get("Closed", 0),
                "unassigned": len([t for t in open_tickets if not t.assignee_id]),
                "sla_breached_open": len(breached_open),
            },
            "by_status": [{"label": s, "count": by_status.get(s, 0)} for s in STATUSES],
            "by_category": [
                {"label": c, "count": by_category.get(c, 0)}
                for c in sorted(CATEGORIES, key=lambda c: -by_category.get(c, 0))
            ],
            "by_priority": [{"label": p, "count": by_priority.get(p, 0)} for p in PRIORITIES],
            "resolution": {
                "resolved_count": len(resolved),
                "avg_hours": avg_resolution,
                "sla_compliance_pct": sla_compliance,
                "sla_targets": SLA_HOURS,
            },
            "workload": workload,
            "oldest_open": [
                {
                    "id": t.id,
                    "title": t.title,
                    "priority": t.priority,
                    "age_hours": t.age_hours(now),
                    "status": t.status,
                }
                for t in oldest
            ],
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "users": len(self.users),
            "tickets": len(self.tickets),
            "categories": list(CATEGORIES),
            "roles": list(ROLES),
        }

    def reset(self) -> None:
        """Wipe all records — used by tests."""
        with self._lock:
            self.tickets.clear()
            self._ticket_seq = 1000
            self._comment_seq = 0
