"""Store-level unit tests: SLA maths, transitions, validation, analytics.

These use an injected clock so time-dependent behaviour is deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import SLA_HOURS, Ticket
from app.store import (
    ConflictError,
    InMemoryStore,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

NOW = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)


def build_store(tmp_path, clock_now=NOW, tickets=None):
    seed = {
        "users": [
            {
                "id": 1,
                "name": "Test Student",
                "email": "s@campus.edu",
                "role": "student",
                "department": "CSE",
            },
            {"id": 2, "name": "Test Tech", "email": "t@campus.edu", "role": "technician", "department": "IT"},
            {"id": 3, "name": "Test Admin", "email": "a@campus.edu", "role": "admin", "department": "IT"},
        ],
        "tickets": tickets or [],
    }
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(seed), encoding="utf-8")
    return InMemoryStore(seed_path=str(path), clock=lambda: clock_now)


def test_seeded_ticket_gets_id_and_history(tmp_path):
    store = build_store(
        tmp_path,
        tickets=[
            {
                "title": "Projector dead",
                "description": "No signal at all in room 12.",
                "category": "Projector / AV",
                "priority": "High",
                "status": "Open",
                "requester_id": 1,
                "age_hours": 2,
            }
        ],
    )
    ticket = store.tickets["HD-1001"]
    assert ticket.status == "Open"
    assert ticket.history[0]["event"] == "created"


def test_age_and_sla_breach_with_injected_clock(tmp_path):
    store = build_store(
        tmp_path,
        tickets=[
            {
                "title": "Wi-Fi down",
                "description": "No connectivity on the whole floor.",
                "category": "Wi-Fi / Network",
                "priority": "Critical",
                "status": "Open",
                "requester_id": 1,
                "age_hours": 5,
            }
        ],
    )
    ticket = store.tickets["HD-1001"]
    assert ticket.age_hours(NOW) == 5.0
    assert ticket.sla_hours == SLA_HOURS["Critical"] == 4
    assert ticket.sla_breached(NOW) is True
    assert ticket.sla_state(NOW) == "breached"


def test_sla_at_risk_window(tmp_path):
    ticket = Ticket(
        id="HD-2000",
        title="Sluggish lab PC",
        description="Takes ten minutes to boot.",
        category="Computer / Lab",
        priority="High",
        status="Open",
        requester_id=1,
        created_at=NOW - timedelta(hours=7),
        updated_at=NOW - timedelta(hours=7),
    )
    assert ticket.sla_hours == 8
    assert ticket.sla_state(NOW) == "at-risk"


def test_resolved_ticket_reports_met_sla(tmp_path):
    store = build_store(
        tmp_path,
        tickets=[
            {
                "title": "Printer jam",
                "description": "Paper jams on every job.",
                "category": "Printer / Scanner",
                "priority": "Medium",
                "status": "Resolved",
                "requester_id": 1,
                "age_hours": 30,
                "resolved_age_hours": 20,
            }
        ],
    )
    ticket = store.tickets["HD-1001"]
    assert ticket.resolution_hours() == 10.0
    assert ticket.sla_state(NOW) == "met"


def test_full_lifecycle_open_to_closed(tmp_path):
    store = build_store(tmp_path)
    student = store.get_user(1)
    tech = store.get_user(2)

    ticket = store.create_ticket(
        student,
        {
            "title": "Cannot print from laptop",
            "description": "Print queue stays paused on the lab printer.",
            "category": "Printer / Scanner",
            "priority": "Medium",
        },
    )
    assert ticket.status == "Open"

    store.update_status(ticket.id, "In Progress", tech)
    store.update_status(ticket.id, "Resolved", tech)
    assert store.get_ticket(ticket.id).resolved_at is not None

    store.update_status(ticket.id, "Closed", tech)
    assert store.get_ticket(ticket.id).status == "Closed"

    # Reopening clears the resolution timestamp again.
    store.update_status(ticket.id, "Open", tech)
    reopened = store.get_ticket(ticket.id)
    assert reopened.status == "Open"
    assert reopened.resolved_at is None
    assert len(reopened.history) == 5


def test_illegal_transition_is_rejected(tmp_path):
    store = build_store(tmp_path)
    tech = store.get_user(2)
    ticket = store.create_ticket(
        store.get_user(1),
        {
            "title": "Screen flickers",
            "description": "Monitor flickers after ten minutes.",
            "category": "Computer / Lab",
            "priority": "Low",
        },
    )
    with pytest.raises(ConflictError):
        store.update_status(ticket.id, "Resolved", tech)


def test_student_cannot_progress_a_ticket(tmp_path):
    store = build_store(tmp_path)
    student = store.get_user(1)
    ticket = store.create_ticket(
        student,
        {
            "title": "Need Python installed",
            "description": "Python is missing on lab machine 9.",
            "category": "Software / License",
            "priority": "Low",
        },
    )
    with pytest.raises(PermissionDeniedError):
        store.update_status(ticket.id, "In Progress", student)


def test_create_ticket_validation(tmp_path):
    store = build_store(tmp_path)
    student = store.get_user(1)
    with pytest.raises(ValidationError):
        store.create_ticket(student, {"title": "no", "description": "x" * 20, "category": "Wi-Fi / Network"})
    with pytest.raises(ValidationError):
        store.create_ticket(
            student, {"title": "Valid title", "description": "too short", "category": "Wi-Fi / Network"}
        )
    with pytest.raises(ValidationError):
        store.create_ticket(
            student,
            {"title": "Valid title", "description": "x" * 20, "category": "Astrology"},
        )


def test_assignment_moves_open_ticket_to_in_progress(tmp_path):
    store = build_store(tmp_path)
    admin = store.get_user(3)
    ticket = store.create_ticket(
        store.get_user(1),
        {
            "title": "Mouse not detected",
            "description": "USB mouse is not recognised on PC-4.",
            "category": "Computer / Lab",
            "priority": "Low",
        },
    )
    updated = store.assign(ticket.id, 2, admin)
    assert updated.assignee_id == 2
    assert updated.status == "In Progress"
    assert any(event["event"] == "assigned" for event in updated.history)


def test_assignment_rejects_non_technician(tmp_path):
    store = build_store(tmp_path)
    admin = store.get_user(3)
    ticket = store.create_ticket(
        store.get_user(1),
        {
            "title": "Keyboard keys stuck",
            "description": "Three keys do not respond on PC-6.",
            "category": "Computer / Lab",
            "priority": "Low",
        },
    )
    with pytest.raises(ValidationError):
        store.assign(ticket.id, 1, admin)


def test_comments_are_locked_on_closed_tickets(tmp_path):
    store = build_store(tmp_path)
    tech = store.get_user(2)
    ticket = store.create_ticket(
        store.get_user(1),
        {
            "title": "Printer offline",
            "description": "Printer shows offline in the queue.",
            "category": "Printer / Scanner",
            "priority": "Low",
        },
    )
    store.update_status(ticket.id, "Closed", tech)
    with pytest.raises(ConflictError):
        store.add_comment(ticket.id, tech, "Trying again")


def test_unknown_ticket_raises_not_found(tmp_path):
    store = build_store(tmp_path)
    with pytest.raises(NotFoundError):
        store.get_ticket("HD-0000")


def test_analytics_totals_match_ticket_count(tmp_path):
    store = build_store(
        tmp_path,
        tickets=[
            {
                "title": f"Issue {i}",
                "description": "Something is broken in the lab.",
                "category": "Computer / Lab",
                "priority": ["Low", "Medium", "High", "Critical"][i % 4],
                "status": ["Open", "In Progress", "Resolved", "Closed"][i % 4],
                "requester_id": 1,
                "age_hours": 10 + i,
                "resolved_age_hours": 2 if i % 4 >= 2 else None,
            }
            for i in range(8)
        ],
    )
    stats = store.analytics()
    assert stats["totals"]["all"] == 8
    assert sum(row["count"] for row in stats["by_status"]) == 8
    assert stats["resolution"]["resolved_count"] == 4
    assert stats["by_category"][0]["label"] == "Computer / Lab"
