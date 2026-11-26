"""Domain model for the helpdesk.

The project intentionally runs without a database: every record lives in an
in-memory store seeded with realistic demo data. The model layer is kept
separate so it can be swapped for SQLAlchemy later without touching routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CATEGORIES = (
    "Wi-Fi / Network",
    "Computer / Lab",
    "Projector / AV",
    "Software / License",
    "Printer / Scanner",
    "Account / Access",
)

PRIORITIES = ("Low", "Medium", "High", "Critical")

STATUSES = ("Open", "In Progress", "Resolved", "Closed")

ROLES = ("student", "faculty", "technician", "admin")

# Service-level target, in hours, measured from ticket creation to resolution.
SLA_HOURS = {"Critical": 4, "High": 8, "Medium": 24, "Low": 72}

# Allowed status moves. Anything else is rejected by the store.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "Open": ("In Progress", "Closed"),
    "In Progress": ("Resolved", "Open"),
    "Resolved": ("Closed", "Open"),
    "Closed": ("Open",),
}

STATUS_ORDER = {"Open": 0, "In Progress": 1, "Resolved": 2, "Closed": 3}
PRIORITY_WEIGHT = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def utcnow() -> datetime:
    """Timezone-aware 'now' used everywhere in the app."""
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


@dataclass
class User:
    id: int
    name: str
    email: str
    role: str
    department: str
    password_hash: str = ""

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "department": self.department,
            "initials": self.initials,
        }


@dataclass
class Comment:
    id: int
    author_id: int
    body: str
    created_at: datetime
    internal: bool = False

    def to_dict(self, users: dict[int, User]) -> dict[str, Any]:
        author = users.get(self.author_id)
        return {
            "id": self.id,
            "author": author.name if author else "Unknown",
            "author_role": author.role if author else "unknown",
            "body": self.body,
            "internal": self.internal,
            "created_at": iso(self.created_at),
        }


@dataclass
class Ticket:
    id: str
    title: str
    description: str
    category: str
    priority: str
    status: str
    requester_id: int
    location: str = ""
    assignee_id: int | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    resolved_at: datetime | None = None
    comments: list[Comment] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    # -- derived values ---------------------------------------------------
    @property
    def sla_hours(self) -> int:
        return SLA_HOURS[self.priority]

    def age_hours(self, now: datetime | None = None) -> float:
        now = now or utcnow()
        return round((now - self.created_at).total_seconds() / 3600, 1)

    def resolution_hours(self) -> float | None:
        if not self.resolved_at:
            return None
        return round((self.resolved_at - self.created_at).total_seconds() / 3600, 1)

    def is_open(self) -> bool:
        return self.status in ("Open", "In Progress")

    def sla_breached(self, now: datetime | None = None) -> bool:
        """True when the ticket is unresolved past its SLA target."""
        if self.resolved_at:
            return (self.resolved_at - self.created_at).total_seconds() / 3600 > self.sla_hours
        return self.is_open() and self.age_hours(now) > self.sla_hours

    def sla_state(self, now: datetime | None = None) -> str:
        """One of: met, breached, at-risk, on-track, n/a."""
        if self.resolved_at:
            return "breached" if self.sla_breached(now) else "met"
        if not self.is_open():
            return "n/a"
        age = self.age_hours(now)
        if age > self.sla_hours:
            return "breached"
        if age > self.sla_hours * 0.75:
            return "at-risk"
        return "on-track"

    def to_dict(self, users: dict[int, User] | None = None, now: datetime | None = None) -> dict[str, Any]:
        users = users or {}
        now = now or utcnow()
        requester = users.get(self.requester_id)
        assignee = users.get(self.assignee_id) if self.assignee_id else None
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "location": self.location,
            "requester": requester.to_dict() if requester else None,
            "assignee": assignee.to_dict() if assignee else None,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "resolved_at": iso(self.resolved_at),
            "age_hours": self.age_hours(now),
            "sla_hours": self.sla_hours,
            "sla_state": self.sla_state(now),
            "resolution_hours": self.resolution_hours(),
            "comment_count": len(self.comments),
            "comments": [c.to_dict(users) for c in self.comments],
            "history": self.history,
        }
