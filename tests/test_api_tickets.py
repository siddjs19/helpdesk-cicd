"""JSON API contract tests: list, create, read, update, validation, RBAC."""

from __future__ import annotations

from .conftest import ACCOUNTS, login


def test_meta_endpoint_is_public(client):
    body = client.get("/api/v1/meta").get_json()
    assert "Wi-Fi / Network" in body["categories"]
    assert body["statuses"] == ["Open", "In Progress", "Resolved", "Closed"]


def test_api_requires_authentication(client):
    assert client.get("/api/v1/tickets").status_code == 401


def test_admin_sees_every_ticket(as_admin):
    body = as_admin.get("/api/v1/tickets").get_json()
    assert body["meta"]["count"] == 22
    assert len(body["data"]) == 22


def test_student_sees_only_own_tickets(as_student):
    body = as_student.get("/api/v1/tickets").get_json()
    assert body["meta"]["count"] == 6
    assert all(t["requester"]["email"] == ACCOUNTS["student"] for t in body["data"])


def test_filter_by_status(as_admin):
    body = as_admin.get("/api/v1/tickets?status=Open").get_json()
    assert body["meta"]["count"] == 8
    assert {t["status"] for t in body["data"]} == {"Open"}


def test_filter_by_category_and_priority(as_admin):
    body = as_admin.get("/api/v1/tickets?category=Wi-Fi / Network&priority=Critical").get_json()
    assert body["meta"]["count"] >= 1
    assert all(t["category"] == "Wi-Fi / Network" for t in body["data"])
    assert all(t["priority"] == "Critical" for t in body["data"])


def test_invalid_status_filter_returns_400(as_admin):
    response = as_admin.get("/api/v1/tickets?status=Nope")
    assert response.status_code == 400
    assert response.get_json()["error"]["field"] == "status"


def test_search_matches_title(as_admin):
    body = as_admin.get("/api/v1/tickets?q=projector").get_json()
    assert body["meta"]["count"] >= 2


def test_create_ticket_returns_201_and_open_status(as_student):
    payload = {
        "title": "Lab PC-22 has no network access",
        "description": "The machine cannot reach the campus network at all.",
        "category": "Computer / Lab",
        "priority": "High",
        "location": "Computer Lab 3",
    }
    response = as_student.post("/api/v1/tickets", json=payload)
    assert response.status_code == 201
    ticket = response.get_json()["data"]
    assert ticket["id"] == "HD-1023"
    assert ticket["status"] == "Open"
    assert ticket["sla_hours"] == 8
    assert ticket["requester"]["email"] == ACCOUNTS["student"]


def test_create_ticket_validation_errors(as_student):
    response = as_student.post(
        "/api/v1/tickets",
        json={"title": "Bad", "description": "short", "category": "Nope", "priority": "High"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["field"] == "title"


def test_get_single_ticket(as_admin):
    response = as_admin.get("/api/v1/tickets/HD-1001")
    assert response.status_code == 200
    assert response.get_json()["data"]["id"] == "HD-1001"


def test_get_missing_ticket_returns_404(as_admin):
    response = as_admin.get("/api/v1/tickets/HD-9999")
    assert response.status_code == 404


def test_student_cannot_read_another_students_ticket(as_student):
    response = as_student.get("/api/v1/tickets/HD-1003")
    assert response.status_code == 403


def test_patch_status_follows_allowed_transition(as_technician):
    response = as_technician.patch("/api/v1/tickets/HD-1002", json={"status": "In Progress"})
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "In Progress"


def test_patch_rejects_illegal_transition(as_technician):
    response = as_technician.patch("/api/v1/tickets/HD-1002", json={"status": "Resolved"})
    assert response.status_code == 409
    assert "Cannot move ticket" in response.get_json()["error"]["message"]


def test_patch_assigns_technician_and_starts_work(as_admin):
    response = as_admin.patch("/api/v1/tickets/HD-1002", json={"assignee_id": 6})
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["assignee"]["name"] == "Sneha Patil"
    assert data["status"] == "In Progress"


def test_patch_rejects_non_technician_assignee(as_admin):
    response = as_admin.patch("/api/v1/tickets/HD-1002", json={"assignee_id": 1})
    assert response.status_code == 400
    assert response.get_json()["error"]["field"] == "assignee_id"


def test_patch_status_requires_staff_role(as_student):
    response = as_student.patch("/api/v1/tickets/HD-1001", json={"status": "Resolved"})
    assert response.status_code == 403


def test_comment_is_appended(as_technician):
    response = as_technician.post(
        "/api/v1/tickets/HD-1002/comments", json={"body": "Replacement HDMI cable ordered."}
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["comment_count"] == 1


def test_comment_validation(as_technician):
    response = as_technician.post("/api/v1/tickets/HD-1002/comments", json={"body": " "})
    assert response.status_code == 400


def test_analytics_requires_staff_role(as_student):
    assert as_student.get("/api/v1/analytics").status_code == 403


def test_analytics_payload_shape(as_admin):
    body = as_admin.get("/api/v1/analytics").get_json()["data"]
    assert body["totals"]["all"] == 22
    assert sum(row["count"] for row in body["by_status"]) == 22
    assert body["resolution"]["resolved_count"] == 9
    assert 0 <= body["resolution"]["sla_compliance_pct"] <= 100
    assert body["workload"]


def test_logged_out_client_loses_api_access(client):
    login(client, ACCOUNTS["admin"])
    assert client.get("/api/v1/tickets").status_code == 200
    client.post("/logout")
    assert client.get("/api/v1/tickets").status_code == 401
