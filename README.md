# Veil

**Anonymous, real-time messaging through ephemeral identities.**

Veil is a full-stack chat platform where users communicate under randomly-generated pseudonyms called *sigils*. No usernames appear inside a room - only the sigil you were assigned when you entered. Leave and re-enter, and you become someone else entirely.

Built to demonstrate production-grade backend patterns: WebSocket fan-out over Redis pub/sub, dual-token JWT authentication, per-user rate limiting via Redis Lua scripts, one-time-use socket tokens, and a soft-deleted audit trail - all behind a purpose-built gothic UI.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Backend](#backend)
  - [Domain Model](#domain-model)
  - [Authentication & Security](#authentication--security)
  - [WebSocket Protocol](#websocket-protocol)
  - [Rate Limiting](#rate-limiting)
  - [Real-time Hub](#real-time-hub)
  - [API Reference](#api-reference)
- [Frontend](#frontend)
  - [State Management](#state-management)
  - [WebSocket Hook](#websocket-hook)
  - [Sigil Renderer](#sigil-renderer)
  - [Sound Engine](#sound-engine)
- [Database Schema](#database-schema)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)

---

## Features

| Feature | Description |
|---------|-------------|
| **Séances** | Public or sealed (invite-only) chat rooms |
| **Ephemeral Sigils** | Random pseudonyms per room entry - identity resets on re-entry |
| **Real-time Messaging** | WebSocket with exponential backoff reconnection and backfill |
| **Sealed Rooms** | Warden-issued, single-use JWT invite links for private séances |
| **Warden Controls** | Role system (warden / moderator / attendant), kick, promote, transfer wardenship |
| **Whisper Redaction** | Warden/moderator soft-delete with content sentinel; audit trail preserved |
| **Whisper TTL** | Per-room message expiration with a background pruning task |
| **Sound Design** | Ambient drone + event sounds synthesised entirely via Web Audio API |
| **Identity Isolation** | Seeker ID and email are never exposed inside a séance - sigil only |

---

## Tech Stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) - ASGI framework, dependency injection, WebSocket support
- [SQLAlchemy 2](https://www.sqlalchemy.org/) - sync ORM (PostgreSQL via psycopg2)
- [Alembic](https://alembic.sqlalchemy.org/) - schema migrations
- [Redis 7](https://redis.io/) - pub/sub fan-out, socket token registry, rate-limit buckets
- [python-jose](https://github.com/mpdavis/python-jose) - JWT (HS256)
- [bcrypt](https://pypi.org/project/bcrypt/) - password hashing (with SHA-256 pre-hash)
- [slowapi](https://github.com/laurentS/slowapi) - HTTP rate limiting
- [uv](https://github.com/astral-sh/uv) - fast Python package manager
- Python 3.13

**Frontend**
- [React 18](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/)
- [Vite 5](https://vitejs.dev/) - build tooling
- [React Router 6](https://reactrouter.com/) - client-side routing
- Web Audio API - synthesised ambient sound, no audio files
- Custom WebSocket hook - reconnection, backfill, token lifecycle

**Infrastructure**
- Docker Compose - Postgres 16, Redis 7, API, Frontend
- [testcontainers](https://testcontainers.com/) + [fakeredis](https://github.com/cunla/fakeredis-py) - isolated integration tests

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Client (React)                         │
│  LobbyPage  ──►  RoomPage ──► useSeanceSocket ──► WebSocket     │
│                       │                                         │
│               POST /seances/{id}/whispers                       │
│               GET  /seances/{id}/whispers (paginated backfill)  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP + WebSocket
┌───────────────────────────▼─────────────────────────────────────┐
│                      FastAPI (port 8000)                        │
│                                                                 │
│  routers/auth.py        POST /auth/register, /login             │
│  routers/seances.py     CRUD + warden controls                  │
│  routers/whispers.py    POST, GET, DELETE /whispers             │
│  routers/invites.py     POST /invites, POST /seances/join       │
│  routers/ws.py          WS  /ws/seances/{id}?token=...          │
│                                                                 │
│  services/              Business logic layer                    │
│  core/security.py       JWT (access / socket / invite tokens)   │
│  realtime/hub.py        WebSocket registry + Redis fan-out      │
└──────┬────────────────────────────┬─────────────────────────────┘
       │ SQL (psycopg2)             │ redis.asyncio
┌──────▼──────────┐        ┌───────▼──────────────────────────────┐
│  PostgreSQL 16  │        │             Redis 7                  │
│                 │        │                                      │
│  seekers        │        │  socket_jti:{jti}   (60s TTL)        │
│  seances        │        │  seance:{id}        (pub/sub channel)│
│  presences      │        │  wsbucket:{s}:{u}   (token bucket)   │
│  whispers       │        └──────────────────────────────────────┘
│  invites        │
└─────────────────┘
```

**Multi-worker fan-out:** The hub publishes every broadcast to a Redis channel (`seance:{id}`). A background subscriber task on each worker re-fans published messages to its locally-registered WebSockets. This means the application scales horizontally - a whisper sent through worker A reaches clients connected to worker B.

---

## Backend

### Domain Model

The codebase uses a consistent vocabulary throughout:

| Term | Meaning |
|------|---------|
| `Seeker` | Authenticated user account |
| `Séance` | A chat room; can be public or `is_sealed` (invitation-only) |
| `Presence` | A Seeker's current membership in a Séance; carries an anonymous `sigil` |
| `Sigil` | Randomly-generated in-room pseudonym (e.g. *"The Pale Lantern"*, *"Ash-and-Iron"*) |
| `Warden` | The Séance creator; a Presence with `role=warden` |
| `Whisper` | A message posted in a Séance |
| `Invite` | A single-use JWT granting entry to a sealed Séance |

**Layer structure:**

```
routers/     HTTP boundary - thin delegates to services
services/    Business logic; all access control decisions live here
models/      SQLAlchemy ORM (Seeker, Seance, Presence, Whisper, Invite)
schemas/     Pydantic request/response models
core/        Cross-cutting: config, JWT security, sigil generator, rate limiter, DI
realtime/    WebSocket hub (local registry + Redis pub/sub)
```

### Authentication & Security

Veil uses **three distinct JWT token types**, each with different lifetimes and purposes:

#### Access Token (24h)
Standard Bearer token for all HTTP endpoints. Issued on login, stored in `localStorage`. The `type` claim is validated on every decode - an invite or socket token cannot be replayed as an access token.

```
POST /auth/login  →  { access_token: "eyJ..." }
Authorization: Bearer <access_token>
```

#### Socket Token (60s, one-time-use)
Before opening a WebSocket, the client mints a short-lived socket token:

```
POST /auth/socket-token  →  { socket_token: "eyJ...", jti: "uuid" }
WS  /ws/seances/{id}?token=<socket_token>
```

On connection, the server atomically consumes the JTI from Redis using `GETDEL`. If the key is absent (already used or expired), the connection is rejected with close code `4001`. This prevents token replay attacks even within the 60-second window.

#### Invite Token (configurable, default 24h, one-time-use)
Sealed-séance invite links embed a JWT. A matching `Invite` row in PostgreSQL tracks the JTI; `used_at` is set on first consumption and the token cannot be reused.

```
POST /seances/{id}/invites?expires_in_seconds=86400
  →  { token: "eyJ...", expires_at: "..." }

POST /seances/join?token=<invite_token>
  →  OwnPresenceResponse
```

#### Password Hashing
Passwords are **SHA-256 pre-hashed** before bcrypt to neutralise bcrypt's 72-byte truncation vulnerability - a long passphrase will never silently collide with a shorter one.

```python
def hash_password(password: str) -> str:
    pre = hashlib.sha256(password.encode()).hexdigest()
    return bcrypt.hashpw(pre.encode(), bcrypt.gensalt()).decode()
```

### WebSocket Protocol

**Endpoint:** `GET /ws/seances/{seance_id}?token=<socket_token>`

Authentication and presence are verified before the connection is accepted. Auth/presence failures arrive as WebSocket close codes, never as JSON frames:

| Code | Meaning |
|------|---------|
| `4001` | Unauthorized (bad/expired/used token, seeker not found) |
| `4003` | Forbidden (no Presence in this séance) |

**Client → Server frames:**

```jsonc
{ "op": "whisper", "content": "..." }   // 1–4000 chars after strip
```

**Server → All connected clients:**

```jsonc
{ "op": "whisper", "id": 42, "seance_id": 1, "sigil": "The Pale Lantern",
  "content": "...", "is_deleted": false, "created_at": "..." }

{ "op": "enter",   "sigil": "Ash-and-Iron" }
{ "op": "depart",  "sigil": "Ash-and-Iron" }
{ "op": "dissolve" }
{ "op": "redact",  "whisper_id": 42 }
{ "op": "promote", "sigil": "...", "role": "moderator" }
```

**Server → Sender only (error):**

```jsonc
{ "op": "error", "detail": "You are speaking too quickly. Slow down." }
```

**Reconnection strategy (client):** Exponential backoff - `500ms × 2ⁿ`, capped at 30 seconds, maximum 8 retries. On each reconnect the client requests a new socket token and backfills missed whispers using the highest whisper ID seen before disconnect. Close codes `4001`/`4003` suppress reconnection entirely.

### Rate Limiting

Two independent layers of rate limiting:

**HTTP (slowapi)** - per-IP, per-endpoint limits enforced at the router layer. Examples:
- `POST /auth/login` - 20/minute
- `POST /seances/{id}/enter` - 30/minute
- `GET /seances` - 60/minute

**WebSocket (Redis token bucket)** - per-Seeker per-Séance, implemented as a Lua script executed atomically in Redis:

```lua
-- KEYS[1] = wsbucket:{seance_id}:{seeker_id}
-- Capacity: 10 tokens, Refill: 1 token/second
local tokens = math.min(capacity, tokens + elapsed * refill_rate)
if tokens < 1 then return 0 end
tokens = tokens - 1
-- store updated state, set 120s expiry
return 1
```

Rate-limited whispers receive an `error` frame; the WebSocket is not closed. The Lua script executes atomically - no race conditions across concurrent requests.

### Real-time Hub

`app/realtime/hub.py` bridges WebSocket connections and Redis pub/sub:

```python
# Register/unregister WebSocket connections (per worker, in-memory)
hub.register(seance_id, websocket)
hub.unregister(seance_id, websocket)

# Broadcast to all clients across all workers
await hub.broadcast(seance_id, {"op": "whisper", ...})
```

`broadcast()` serialises the payload and publishes to `seance:{id}` on Redis. A background task (started during application lifespan) subscribes to `seance:*` and fans each message out to locally-registered WebSocket connections. Dead sockets (those that raise on send) are pruned automatically.

### API Reference

<details>
<summary><strong>Authentication</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | - | Create a new Seeker account |
| `POST` | `/auth/login` | - | Authenticate and receive an access token |
| `POST` | `/auth/socket-token` | Bearer | Mint a one-time 60s WebSocket token |

</details>

<details>
<summary><strong>Séances</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/seances` | Bearer | Create a séance (public or sealed) |
| `GET` | `/seances` | Bearer | List visible séances (public + user's sealed) |
| `GET` | `/seances/{id}` | Bearer | Get séance detail + presence count |
| `POST` | `/seances/{id}/enter` | Bearer | Enter a public séance (creates Presence + sigil) |
| `DELETE` | `/seances/{id}/depart` | Bearer | Depart a séance (deletes Presence; wardens cannot depart) |
| `DELETE` | `/seances/{id}` | Bearer | Dissolve séance (warden only; broadcasts `dissolve`) |

</details>

<details>
<summary><strong>Presences</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/seances/{id}/presences` | Bearer | List all current presences |
| `GET` | `/seances/{id}/presences/me` | Bearer | Get own presence (sigil, role) |
| `DELETE` | `/seances/{id}/presences/sigil/{sigil}` | Bearer | Kick by sigil (warden/moderator) |
| `POST` | `/seances/{id}/transfer/sigil` | Bearer | Transfer wardenship by sigil |
| `PATCH` | `/seances/{id}/presences/sigil/{sigil}/role` | Bearer | Promote/demote by sigil (warden only) |

</details>

<details>
<summary><strong>Whispers</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/seances/{id}/whispers` | Bearer | Post a whisper (also available via WebSocket) |
| `GET` | `/seances/{id}/whispers` | Bearer | Paginated history (`?limit=50&before_id=...`) |
| `DELETE` | `/seances/{id}/whispers/{whisper_id}` | Bearer | Redact a whisper (warden/moderator) |

</details>

<details>
<summary><strong>Invites</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/seances/{id}/invites` | Bearer | Create invite link (warden only; `?expires_in_seconds=86400`) |
| `POST` | `/seances/join` | Bearer | Consume an invite token (`?token=...`); creates Presence |

</details>

<details>
<summary><strong>Real-time</strong></summary>

| Protocol | Path | Description |
|----------|------|-------------|
| `WebSocket` | `/ws/seances/{id}?token=...` | Persistent connection for live whispers and presence events |

</details>

---

## Frontend

### State Management

Authentication state is held in a **React Context** backed by `localStorage`, with no external state library. The pattern is intentionally minimal - the only global state is the JWT access token.

```typescript
// src/store/auth.tsx
interface AuthState {
  token: string | null
  setToken: (t: string) => void
  clearToken: () => void
}
```

Token is persisted under the key `veil:token`. All API calls thread the token as a parameter rather than pulling from a global store, making data flow explicit and testable.

### WebSocket Hook

`src/lib/useSeanceSocket.ts` encapsulates the full WebSocket lifecycle:

1. **Token acquisition** - fetches a one-shot socket token via `POST /auth/socket-token`
2. **Connection** - opens `ws://…/ws/seances/{id}?token=<socket_token>`
3. **Message dispatch** - calls `onMessage(msg: WsMessage)` for each valid frame
4. **Reconnection** - on unexpected close, schedules reconnect with exponential backoff (`500ms × 2ⁿ`, cap 30s, max 8 retries); `4001`/`4003` close codes suppress reconnection
5. **Backfill** - on reconnect, calls `onReconnect(lastSeenWhisperId)` so the page can fetch missed whispers
6. **Cleanup** - closes the socket with code `1000` on unmount

```typescript
const { wsStatus, sendWhisper } = useSeanceSocket({
  seanceId,
  token,
  enabled: wsReady,
  onMessage: handleWsMessage,
  onReconnect: fetchMissedWhispers,
})
```

`wsStatus` surfaces as `'connecting' | 'connected' | 'reconnecting' | 'dead'` - the UI reflects each state visually.

### Sigil Renderer

`src/lib/sigil.ts` generates deterministic SVG seals client-side with no server round-trip. Given the same sigil string, it always produces the same visual.

**Algorithm:**
1. Hash the sigil string with FNV-1a to produce a seed
2. Run a seeded LCG (linear congruential generator) for reproducible randomness
3. Pick a shape (circle, triangle, pentagon, hexagon), 1–2 rune glyphs from a 20-glyph alphabet, 3–6 perimeter accent dots, and one of 5 gold colour shades - all deterministically from the seed

The same sigil always renders identically across sessions and devices with no database lookup or image storage.

### Sound Engine

`src/lib/sounds.ts` synthesises all audio at runtime using the Web Audio API - no audio files are bundled or fetched.

| Sound | Implementation |
|-------|---------------|
| Ambient hum | 55 Hz oscillator (organ tone) with 0.28 Hz amplitude LFO |
| Whisper received | Filtered noise burst (1800 Hz bandpass) |
| Whisper sent | Sine downward sweep (160 → 60 Hz, 120ms) |
| Connection drop | Sawtooth downward sweep (320 → 80 Hz, 700ms) |
| Reconnected | Three ascending sine chimes (220 → 330 → 440 Hz) |

All sound is off by default and toggled per-session. The approach eliminates CDN dependencies and avoids browser autoplay restrictions (sounds only play after the first user interaction).

---

## Database Schema

```
seekers
  id              SERIAL PK
  email           VARCHAR(255) UNIQUE NOT NULL
  hashed_password VARCHAR(255) NOT NULL
  created_at      TIMESTAMP (server default)

seances
  id                   SERIAL PK
  name                 VARCHAR(100) UNIQUE NOT NULL
  description          VARCHAR(300)
  is_sealed            BOOLEAN NOT NULL DEFAULT FALSE
  whisper_ttl_seconds  INTEGER  -- NULL = no expiration
  created_by           FK → seekers.id
  created_at           TIMESTAMP

presences
  seeker_id   FK → seekers.id  ─┐
  seance_id   FK → seances.id  ─┴─ composite PK
  sigil       VARCHAR(80) NOT NULL
  role        ENUM(warden, moderator, attendant) NOT NULL
  entered_at  TIMESTAMP
  UNIQUE (seance_id, sigil)  -- prevents sigil collision within a room

whispers
  id          SERIAL PK
  seance_id   FK → seances.id
  seeker_id   FK → seekers.id  -- nullable; never exposed in API responses
  sigil       VARCHAR(80) NOT NULL  -- snapshotted at post time
  content     TEXT NOT NULL
  deleted_at  TIMESTAMP  -- NULL = visible; set = soft-deleted
  created_at  TIMESTAMP
  INDEX (seance_id, id)  -- efficient cursor-based pagination

invites
  id          SERIAL PK
  seance_id   FK → seances.id
  created_by  FK → seekers.id
  used_by     FK → seekers.id  -- NULL until consumed
  jti         VARCHAR(64) UNIQUE NOT NULL
  expires_at  TIMESTAMP NOT NULL
  used_at     TIMESTAMP  -- NULL until consumed
  created_at  TIMESTAMP
```

**Key design decisions:**
- **Composite PK on presences** - `(seeker_id, seance_id)` enforces one active presence per seeker per room at the database level
- **Sigil snapshotted on whispers** - preserves message attribution even after a presence is deleted (user departs)
- **Soft-delete on whispers** - `deleted_at` instead of hard `DELETE`; content is replaced with a sentinel string in API responses but the row is retained for audit
- **Unique `(seance_id, sigil)`** - collision resistance enforced by the database; `assign_presence()` retries up to 8 times on `IntegrityError` before failing with `503`

---

## Getting Started

### Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/veil-API.git
cd veil-API

# Copy and configure environment variables
cp backend/.env.example backend/.env
# Edit backend/.env - set SECRET_KEY at minimum

# Start all services (Postgres, Redis, API, Frontend)
docker compose up --build
```

The application will be available at:
- **Frontend:** http://localhost:5173
- **API:** http://localhost:8000
- **Interactive API docs:** http://localhost:8000/docs

### Local Development

**Requirements:** Python 3.13+, Node.js 20+, uv, a running Postgres and Redis instance.

**Backend:**
```bash
cd backend

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with DATABASE_URL, REDIS_URL, SECRET_KEY

# Apply migrations
uv run alembic upgrade head

# Start the API server
uv run uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## Configuration

### Backend (`backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL DSN - `postgresql://user:pass@host:port/db` |
| `REDIS_URL` | Yes | Redis DSN - `redis://host:port` |
| `SECRET_KEY` | Yes | JWT signing key - generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### Frontend

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend API base URL |

### Runtime flags

| Variable | Effect |
|----------|--------|
| `TESTING=1` | Skips `wait_for_db()` on startup; disables HTTP rate limiting |

---

## Testing

Tests use `pytest` with **testcontainers** (a real Postgres container) and **fakeredis** for complete isolation - no mocking of database behaviour.

```bash
cd backend

# Run all tests
TESTING=1 uv run pytest

# Run a specific file
TESTING=1 uv run pytest tests/test_seances.py

# Run a single test
TESTING=1 uv run pytest tests/test_ws.py::test_whisper_rate_limit
```

Test coverage spans:
- **Auth** (`test_auth.py`) - registration, login, duplicate email, bad credentials, socket token lifecycle
- **Séances** (`test_seances.py`) - CRUD, sealed access control, warden operations, invite flow
- **Whispers** (`test_whispers.py`) - pagination, soft-delete, redaction permissions
- **WebSocket** (`test_ws.py`) - connection auth, message protocol, rate limiting, presence broadcasting

---

## Project Structure

```
veil-API/
├── docker-compose.yml
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_seances.py
│   │   ├── test_whispers.py
│   │   └── test_ws.py
│   └── app/
│       ├── main.py              # App factory, lifespan, CORS, startup
│       ├── database.py          # SQLAlchemy engine + session factory
│       ├── core/
│       │   ├── config.py        # Pydantic settings (env vars)
│       │   ├── security.py      # JWT creation/validation, bcrypt
│       │   ├── dependencies.py  # FastAPI DI: get_db, get_current_seeker
│       │   ├── sigils.py        # Pseudonym generator
│       │   └── limiter.py       # slowapi instance
│       ├── models/
│       │   ├── seeker.py
│       │   ├── seance.py
│       │   ├── presence.py
│       │   ├── whisper.py
│       │   └── invite.py
│       ├── schemas/
│       │   ├── auth.py
│       │   ├── seeker.py
│       │   ├── seance.py
│       │   ├── presence.py
│       │   └── whisper.py
│       ├── services/
│       │   ├── auth_service.py
│       │   ├── seance_service.py
│       │   ├── presence_service.py
│       │   ├── whisper_service.py
│       │   ├── invite_service.py
│       │   └── redis.py
│       ├── routers/
│       │   ├── auth.py
│       │   ├── seances.py
│       │   ├── whispers.py
│       │   ├── invites.py
│       │   ├── ws.py
│       │   └── debug.py
│       └── realtime/
│           └── hub.py           # WebSocket registry + Redis pub/sub
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx              # Router, Protected wrapper
        ├── index.css            # Design tokens, component styles
        ├── api/
        │   ├── client.ts        # fetch wrapper, ApiError class
        │   ├── auth.ts
        │   ├── seances.ts
        │   └── types.ts         # TypeScript interfaces + WsMessage discriminated union
        ├── store/
        │   └── auth.tsx         # AuthContext, useAuth hook, localStorage
        ├── lib/
        │   ├── useSeanceSocket.ts  # WS lifecycle, reconnection, backfill
        │   ├── sigil.ts            # Deterministic SVG sigil renderer
        │   └── sounds.ts           # Web Audio API synthesis
        ├── components/
        │   └── Toast.tsx
        └── pages/
            ├── LoginPage.tsx
            ├── RegisterPage.tsx
            ├── LobbyPage.tsx
            ├── RoomPage.tsx
            └── InvitePage.tsx
```
