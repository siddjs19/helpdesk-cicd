"""Server-rendered page tests: dashboard, ticket pages, RBAC, error pages."""

from __future__ import annotations

from .conftest import ACCOUNTS, login


def test_dashboard_shows_stats_for_student(as_student):
    html = as_student.get("/dashboard").get_data(as_text=True)
    assert "Avg. resolution" in html
    assert "How it works" in html


def test_dashboard_shows_technician_queue(as_technician):
    html = as_technician.get("/dashboard").get_data(as_text=True)
    assert "My queue" in html
    assert "Unassigned" in html


def test_ticket_list_renders_and_filters(as_admin):
    html = as_admin.get("/tickets").get_data(as_text=True)
    assert "HD-1001" in html
    filtered = as_admin.get("/tickets?status=Closed").get_data(as_text=True)
    assert "HD-1009" in filtered
    assert "HD-1002" not in filtered


def test_ticket_detail_page(as_student):
    html = as_student.get("/tickets/HD-1001").get_data(as_text=True)
    assert "Wi-Fi keeps disconnecting" in html
    assert "Change status" not in html  # students cannot progress tickets
    assert "Assign technician" not in html


def test_technician_sees_assignment_controls(as_technician):
    html = as_technician.get("/tickets/HD-1002").get_data(as_text=True)
    assert "Assign technician" in html
    assert "Mark In Progress" in html


def test_student_cannot_view_someone_elses_ticket(as_student):
    response = as_student.get("/tickets/HD-1003")
    assert response.status_code == 403


def test_missing_ticket_renders_404_page(as_admin):
    response = as_admin.get("/tickets/HD-4242")
    assert response.status_code == 404
    assert "not found" in response.get_data(as_text=True).lower()


def test_create_ticket_through_the_form(as_student):
    response = as_student.post(
        "/tickets",
        data={
            "title": "Projector in EC-101 shows a blue screen",
            "description": "The projector shows a blue screen for every input source.",
            "category": "Projector / AV",
            "priority": "High",
            "location": "EC-101",
        },
    )
    assert response.status_code == 302
    detail = as_student.get(response.headers["Location"]).get_data(as_text=True)
    assert "Projector in EC-101 shows a blue screen" in detail


def test_invalid_form_submission_reports_error(as_student):
    response = as_student.post(
        "/tickets",
        data={"title": "hi", "description": "too short", "category": "Projector / AV", "priority": "Low"},
    )
    assert response.status_code == 400
    assert "at least 5 characters" in response.get_data(as_text=True)


def test_status_change_through_the_form(as_technician):
    response = as_technician.post("/tickets/HD-1002/status", data={"status": "In Progress"})
    assert response.status_code == 302
    detail = as_technician.get("/tickets/HD-1002").get_data(as_text=True)
    assert "moved to In Progress" in detail


def test_invalid_status_change_flashes_error(as_technician):
    response = as_technician.post("/tickets/HD-1002/status", data={"status": "Resolved"})
    assert response.status_code == 302
    detail = as_technician.get("/tickets/HD-1002").get_data(as_text=True)
    assert "Cannot move ticket" in detail


def test_comment_through_the_form(as_technician):
    as_technician.post("/tickets/HD-1002/comments", data={"body": "On my way to the classroom."})
    detail = as_technician.get("/tickets/HD-1002").get_data(as_text=True)
    assert "On my way to the classroom." in detail


def test_analytics_page_is_staff_only(as_student):
    assert as_student.get("/analytics").status_code == 403


def test_analytics_page_renders_for_technician(as_technician):
    html = as_technician.get("/analytics").get_data(as_text=True)
    assert "Most frequent problems" in html
    assert "Technician workload" in html


def test_index_redirects_to_login_when_anonymous(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_index_redirects_to_dashboard_when_logged_in(client):
    login(client, ACCOUNTS["student"])
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
