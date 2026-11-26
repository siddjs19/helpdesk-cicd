"""Shared pytest fixtures.

Every test gets a fresh application (and therefore a fresh in-memory store
seeded from the demo dataset) so tests never leak state into each other.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.config import TestConfig

DEMO_PASSWORD = "helpdesk123"

ACCOUNTS = {
    "student": "aarav@campus.edu",
    "student2": "priya@campus.edu",
    "faculty": "meera@campus.edu",
    "technician": "kabir@campus.edu",
    "admin": "ananya@campus.edu",
}


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def store(app):
    return app.extensions["store"]


def login(client, email: str, password: str = DEMO_PASSWORD):
    """Log a user in and return the raw login response."""
    return client.post("/login", data={"email": email, "password": password})


@pytest.fixture()
def as_student(client):
    login(client, ACCOUNTS["student"])
    return client


@pytest.fixture()
def as_technician(client):
    login(client, ACCOUNTS["technician"])
    return client


@pytest.fixture()
def as_admin(client):
    login(client, ACCOUNTS["admin"])
    return client
