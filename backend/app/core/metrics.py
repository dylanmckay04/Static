"""Prometheus metric definitions for Static.

All custom metrics live here so the rest of the codebase imports names,
not prometheus_client directly. HTTP-level metrics (request rate, latency,
status codes) are handled separately by prometheus-fastapi-instrumentator
in app/main.py — this module covers the domain-level signals the
instrumentator can't see: WebSocket lifecycle, transmissions, rate
limiting, Redis fan-out, and the background pruner.

Naming follows Prometheus conventions:
  - `static_` prefix namespaces everything to this app
  - `_total` suffix for counters
  - `_seconds` suffix + base units for histograms

Cardinality note
----------------
None of these metrics carry a `channel_id` label on purpose. Channels are
user-created and unbounded, so labelling by channel would create one time
series per channel per worker — a classic cardinality blow-up. Aggregate
counts answer the operational questions ("is the system healthy?"); if
per-channel introspection is ever needed, that's a job for logs or traces,
not metrics.

Multi-worker note
-----------------
The default prometheus_client registry is per-process. This is correct for
the current single-process uvicorn deployment (and for `--reload` dev).
If the app is ever run with `uvicorn --workers N`, switch to
prometheus_client.multiprocess mode (PROMETHEUS_MULTIPROC_DIR) and declare
gauges with multiprocess_mode="livesum" — otherwise each worker would
serve only its own slice of the numbers on whichever process happens to
answer the /metrics scrape.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── WebSocket lifecycle ──────────────────────────────────────────────────────

WS_CONNECTIONS_ACTIVE = Gauge(
    "static_ws_connections_active",
    "WebSocket connections currently registered in this worker's hub",
)

WS_CONNECTS_TOTAL = Counter(
    "static_ws_connects_total",
    "WebSocket connection attempts by outcome",
    ["result"],  # accepted | unauthorized | forbidden
)

# Pre-register the label values so all three series exist from boot.
# Without this, a series only appears after its first increment, which
# makes rate() queries and Grafana legends flicker into existence.
for _result in ("accepted", "unauthorized", "forbidden"):
    WS_CONNECTS_TOTAL.labels(result=_result)

# ── Transmissions ────────────────────────────────────────────────────────────

TRANSMISSIONS_TOTAL = Counter(
    "static_transmissions_total",
    "Transmissions successfully created, by ingress path",
    ["source"],  # websocket | http
)

for _source in ("websocket", "http"):
    TRANSMISSIONS_TOTAL.labels(source=_source)

TRANSMISSIONS_PRUNED_TOTAL = Counter(
    "static_transmissions_pruned_total",
    "Transmissions soft-deleted by the TTL pruning background task",
)

# ── Rate limiting ────────────────────────────────────────────────────────────

WS_RATE_LIMITED_TOTAL = Counter(
    "static_ws_rate_limited_total",
    "Transmission frames rejected by the Redis token bucket",
)

# ── Redis fan-out ────────────────────────────────────────────────────────────

BROADCAST_DURATION_SECONDS = Histogram(
    "static_broadcast_duration_seconds",
    "Time to serialise a payload and publish it to Redis pub/sub",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# ── Socket tokens ────────────────────────────────────────────────────────────

SOCKET_TOKENS_TOTAL = Counter(
    "static_socket_tokens_total",
    "One-time socket token lifecycle events",
    ["event"],  # minted | consumed | rejected
)

for _event in ("minted", "consumed", "rejected"):
    SOCKET_TOKENS_TOTAL.labels(event=_event)
