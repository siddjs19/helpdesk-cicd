"""Authentication, session handling and CSRF protection."""

from __future__ import annotations

from app import create_app
from app.config import TestConfig

from .conftest import ACCOUNTS, login


def test_login_page_lists_demo_accounts(client):
    response = client.get("/login")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "aarav@campus.edu" in html
    assert "helpdesk123" in html


def test_login_with_valid_credentials_redirects_to_dashboard(client):
    response = login(client, ACCOUNTS["admin"])
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_dashboard_renders_after_login(client):
    login(client, ACCOUNTS["technician"])
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Recent tickets" in response.get_data(as_text=True)


def test_login_with_wrong_password_is_rejected(client):
    response = client.post("/login", data={"email": ACCOUNTS["admin"], "password": "wrong"})
    assert response.status_code == 401
    assert "Invalid email or password" in response.get_data(as_text=True)


def test_protected_page_redirects_anonymous_user(client):
    response = client.get("/tickets")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logout_clears_the_session(client):
    login(client, ACCOUNTS["admin"])
    assert client.get("/dashboard").status_code == 200
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302


def test_open_redirect_target_is_ignored(client):
    response = client.post(
        "/login?next=https://evil.example.com",
        data={"email": ACCOUNTS["admin"], "password": "helpdesk123"},
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]


def test_csrf_token_is_required_when_enabled():
    app = create_app(TestConfig, CSRF_ENABLED=True)
    client = app.test_client()
    response = client.post("/login", data={"email": ACCOUNTS["admin"], "password": "helpdesk123"})
    assert response.status_code == 400
    assert "CSRF" in response.get_data(as_text=True)


def test_csrf_token_from_form_is_accepted():
    app = create_app(TestConfig, CSRF_ENABLED=True)
    client = app.test_client()
    page = client.get("/login").get_data(as_text=True)
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    response = client.post(
        "/login",
        data={"email": ACCOUNTS["admin"], "password": "helpdesk123", "csrf_token": token},
    )
    assert response.status_code == 302
