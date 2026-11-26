"""Operational endpoints: liveness, readiness, metrics, version, headers."""

from __future__ import annotations


def test_healthz_is_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_readyz_reports_seeded_store(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ready"
    assert body["tickets"] == 22
    assert body["users"] == 8


def test_metrics_exposes_prometheus_gauges(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "# TYPE helpdesk_tickets_total gauge" in text
    assert 'helpdesk_tickets_total{status="Open"}' in text
    assert "helpdesk_sla_compliance_ratio" in text
    assert "helpdesk_build_info" in text


def test_version_endpoint(client):
    body = client.get("/version").get_json()
    assert body["service"] == "campus-it-helpdesk"
    assert "version" in body and "git_sha" in body


def test_security_headers_are_set(client):
    response = client.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Request-ID"]
    assert "X-Response-Time-ms" in response.headers


def test_request_id_is_propagated(client):
    response = client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"
