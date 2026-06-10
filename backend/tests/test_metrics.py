"""Tests for the Prometheus /metrics endpoint and custom metric registration."""
from __future__ import annotations

from prometheus_client import REGISTRY


async def test_metrics_endpoint_returns_prometheus_text(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]


async def test_custom_metrics_are_registered(client):
    r = await client.get("/metrics")
    body = r.text
    # Domain metrics declared in app/core/metrics.py
    assert "static_ws_connections_active" in body
    assert "static_ws_connects_total" in body
    assert "static_transmissions_total" in body
    assert "static_ws_rate_limited_total" in body
    assert "static_broadcast_duration_seconds" in body
    # HTTP metrics from prometheus-fastapi-instrumentator
    assert "http_request_duration_seconds" in body


async def test_http_requests_are_counted(client):
    # Hit a real endpoint, then confirm the counter moved.
    before = REGISTRY.get_sample_value(
        "http_requests_total",
        {"handler": "/channels", "method": "GET", "status": "4xx"},
    ) or 0.0

    await client.get("/channels")  # no auth header -> 403/401 -> 4xx bucket

    after = REGISTRY.get_sample_value(
        "http_requests_total",
        {"handler": "/channels", "method": "GET", "status": "4xx"},
    ) or 0.0

    assert after == before + 1


async def test_metrics_endpoint_is_not_instrumented(client):
    """/metrics must be excluded from instrumentation so it doesn't count itself."""
    await client.get("/metrics")
    sample = REGISTRY.get_sample_value(
        "http_requests_total",
        {"handler": "/metrics", "method": "GET", "status": "2xx"},
    )
    assert sample is None
