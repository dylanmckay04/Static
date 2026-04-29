# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands are run from the `backend/` directory unless noted.

```bash
# Start all services (Postgres on 5433, Redis on 6379, API on 8000)
docker compose up --build

# Run the API locally (requires .env with DATABASE_URL, REDIS_URL, SECRET_KEY)
uv run uvicorn app.main:app --reload

# Apply migrations
uv run alembic upgrade head

# Generate a new migration (after changing models)
uv run alembic revision --autogenerate -m "description"

# Run tests
TESTING=1 uv run pytest

# Run a single test file
TESTING=1 uv run pytest tests/test_auth.py

# Run a single test
TESTING=1 uv run pytest tests/test_auth.py::test_login
```

The `TESTING=1` env var skips the `wait_for_db()` startup check in `app/main.py`.

## Architecture

**Stack:** FastAPI + SQLAlchemy (sync ORM) + PostgreSQL + Redis + Alembic. No async DB layer — only Redis is async (`redis.asyncio`). Package manager is `uv`.

**Domain vocabulary** (used throughout the codebase — prefer these terms over generic ones):

| Term | Meaning |
|------|---------|
| `Operator` | An authenticated user account |
| `Channel` | A chat room; can be open or `is_encrypted` (private) |
| `Contact` | An Operator's membership in a Channel; has an anonymous `callsign` |
| `Callsign` | The randomly-generated in-channel pseudonym (e.g. "The Silent Carrier") |
| `Controller` | The Operator who created the Channel; a Contact with `role=controller` |
| `Transmission` | A message posted in a Channel |
| `Cipher Key` | A single-use invite token granting access to an encrypted Channel |

**Layer structure:**

```
routers/      HTTP boundary — thin, delegates to services
services/     Business logic (channel_service, auth_service, contact_service)
models/       SQLAlchemy ORM models
schemas/      Pydantic request/response models
core/         Cross-cutting: config, security (JWT/bcrypt), callsign generator, rate limiter, DI dependencies
```

**Auth flow:** Two token types in `core/security.py`:
- `access` token (24h, JWT) — used for all HTTP endpoints via `HTTPBearer` in `core/dependencies.py`
- `socket` token (60s, JWT, one-time-use) — minted via `POST /auth/socket-token`, JTI stored in Redis so the WebSocket endpoint can consume it atomically

**WebSocket event protocol:** Endpoint is `GET /ws/channels/{channel_id}?token=<socket_token>`. Before connecting, the client mints a one-shot socket token via `POST /auth/socket-token`. Auth/contact failures arrive as WebSocket close codes (`4001` unauthorised, `4003` forbidden) — not JSON frames. All other unexpected closes trigger exponential-backoff reconnect (500 ms × 2ⁿ, cap 30 s, 8 retries).

*Client → Server:*

| `op` | Fields | Notes |
|------|--------|-------|
| `transmission` | `content: string` | 1–4 000 chars after strip; rate-limited (10 burst, 1 token/s per operator+channel) |

*Server → Client — broadcast to all present (`routers/ws.py`, `routers/channels.py`, `routers/transmissions.py`, `routers/cipher_keys.py`):*

| `op` | Payload fields | Trigger |
|------|---------------|---------|
| `transmission` | `id`, `channel_id`, `callsign`, `content`, `is_deleted`, `created_at` | New transmission posted via WS or `POST /channels/{id}/transmissions` |
| `enter` | `callsign` | Operator enters via `POST /channels/{id}/enter` or joins via cipher key (`POST /channels/join`) |
| `depart` | `callsign` | WS disconnect, `DELETE /channels/{id}/depart`, or controller kick |
| `dissolve` | — | Controller deletes the channel (`DELETE /channels/{id}`) |
| `redact` | `transmission_id` | Controller/relay soft-deletes a transmission (`DELETE /channels/{id}/transmissions/{id}`) |

*Server → Client — unicast to sender only:*

| `op` | Fields | Conditions |
|------|--------|-----------|
| `error` | `detail: string` | Validation failure, rate limit exceeded, unknown op, or service error |

Note: after a `redact` the matching transmission's `content` becomes `"⸻ redacted ⸻"` and `is_deleted` flips to `true` when next fetched — no additional frame is sent. The `WsMessage` TypeScript union in `frontend/src/api/types.ts` is the canonical client-side type reference.

**Identity isolation:** `Operator.id`/`email` is never exposed inside a Channel. The `callsign` on a `Contact` (and snapshotted onto `Transmission.callsign`) is the only visible identity. Leaving and re-entering a Channel yields a new callsign.

**Callsign generation:** `core/callsigns.py` produces one of three patterns ("The {Adj} {Noun}", "{Noun}-and-{Noun}", "{Number} {Noun}s"). Uniqueness within a Channel is enforced by `uq_contact_channel_callsign`; `contact_service.assign_contact()` retries up to 8 times on `IntegrityError`.

**Access control for encrypted Channels:** `channel_service._require_visibility()` gates all read/enter operations. Encrypted Channels are visible only to Operators who already have a Contact (cipher key invitation flow required for new entrants).

**Transmission hot path index:** `ix_transmissions_channel_id_id` composite index on `(channel_id, id)` for paginated transmission history queries.

**Redis key patterns:** `channel:{id}` pub/sub fan-out key for multi-worker WebSocket broadcasting. Rate limiter buckets: `wsbucket:{channel_id}:{operator_id}`.

**Rate limiting:** `slowapi` wraps every route; limits are set per-endpoint in `routers/`.

**Debug router:** `GET /debug/token-inspect` decodes a JWT and returns the payload — local dev only, not guarded from production.
