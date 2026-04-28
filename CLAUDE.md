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
| `Seeker` | An authenticated user account |
| `Seance` | A chat room; can be public or `is_sealed` (private) |
| `Presence` | A Seeker's membership in a Seance; has an anonymous `sigil` |
| `Sigil` | The randomly-generated in-room pseudonym (e.g. "The Pale Lantern") |
| `Warden` | The Seeker who created the Seance; a Presence with `role=warden` |
| `Whisper` | A message posted in a Seance |

**Layer structure:**

```
routers/      HTTP boundary — thin, delegates to services
services/     Business logic (seance_service, auth_service, presence_service)
models/       SQLAlchemy ORM models
schemas/      Pydantic request/response models
core/         Cross-cutting: config, security (JWT/bcrypt), sigil generator, rate limiter, DI dependencies
```

**Auth flow:** Two token types in `core/security.py`:
- `access` token (24h, JWT) — used for all HTTP endpoints via `HTTPBearer` in `core/dependencies.py`
- `socket` token (60s, JWT, one-time-use) — minted via `POST /auth/socket-token`, JTI stored in Redis so the WebSocket endpoint can consume it atomically

**WebSocket event protocol:** Endpoint is `GET /ws/seances/{seance_id}?token=<socket_token>`. Before connecting, the client mints a one-shot socket token via `POST /auth/socket-token`. Auth/presence failures arrive as WebSocket close codes (`4001` unauthorised, `4003` forbidden) — not JSON frames. All other unexpected closes trigger exponential-backoff reconnect (500 ms × 2ⁿ, cap 30 s, 8 retries).

*Client → Server:*

| `op` | Fields | Notes |
|------|--------|-------|
| `whisper` | `content: string` | 1–4 000 chars after strip; rate-limited (10 burst, 1 token/s per seeker+seance) |

*Server → Client — broadcast to all present (`routers/ws.py`, `routers/seances.py`, `routers/whispers.py`, `routers/invites.py`):*

| `op` | Payload fields | Trigger |
|------|---------------|---------|
| `whisper` | `id`, `seance_id`, `sigil`, `content`, `is_deleted`, `created_at` | New whisper posted via WS or `POST /seances/{id}/whispers` |
| `enter` | `sigil` | Seeker enters via `POST /seances/{id}/enter` or joins via invite (`POST /seances/join`) |
| `depart` | `sigil` | WS disconnect, `DELETE /seances/{id}/depart`, or warden kick |
| `dissolve` | — | Warden deletes the seance (`DELETE /seances/{id}`) |
| `redact` | `whisper_id` | Warden/moderator soft-deletes a whisper (`DELETE /seances/{id}/whispers/{id}`) |

*Server → Client — unicast to sender only:*

| `op` | Fields | Conditions |
|------|--------|-----------|
| `error` | `detail: string` | Validation failure, rate limit exceeded, unknown op, or service error |

Note: after a `redact` the matching whisper's `content` becomes `"⸻ withdrawn ⸻"` and `is_deleted` flips to `true` when next fetched — no additional frame is sent. The `WsMessage` TypeScript union in `frontend/src/api/types.ts` is the canonical client-side type reference.

**Identity isolation:** `Seeker.id`/`email` is never exposed inside a Seance. The `sigil` on a `Presence` (and snapshotted onto `Whisper.sigil`) is the only visible identity. Leaving and re-entering a Seance yields a new sigil.

**Sigil generation:** `core/sigils.py` produces one of three patterns ("The {Adj} {Noun}", "{Noun}-and-{Noun}", "{Number} {Noun}s"). Uniqueness within a Seance is enforced by `uq_presence_seance_sigil`; `presence_service.assign_presence()` retries up to 8 times on `IntegrityError`.

**Access control for sealed Seances:** `seance_service._require_visibility()` gates all read/enter operations. Sealed Seances are visible only to Seekers who already have a Presence (invitation flow is not yet built).

**Whisper hot path index:** `ix_whispers_seance_id_id` composite index on `(seance_id, id)` for paginated chat history queries.

**Rate limiting:** `slowapi` wraps every route; limits are set per-endpoint in `routers/`.

**Debug router:** `GET /debug/token-inspect` decodes a JWT and returns the payload — local dev only, not guarded from production.
