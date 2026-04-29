# Static

**Anonymous, real-time messaging through ephemeral callsigns.**

Static is a full-stack chat platform where operators communicate over named channels under randomly-generated callsigns. No usernames appear inside a channel — only the callsign assigned when you tuned in. Leave and re-enter, and you broadcast under a new identity entirely.

Built to demonstrate production-grade backend patterns: WebSocket fan-out over Redis pub/sub, dual-token JWT authentication, per-user rate limiting via Redis Lua scripts, one-time-use socket tokens, and a soft-deleted audit trail — all behind a purpose-built shortwave-radio UI.

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
  - [Callsign Renderer](#callsign-renderer)
  - [Sound Engine](#sound-engine)
- [Database Schema](#database-schema)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)

---

## Features

| Feature | Description |
|---------|-------------|
| **Channels** | Public or encrypted (cipher-key-only) chat rooms |
| **Ephemeral Callsigns** | Random pseudonyms per channel entry — identity resets on re-entry |
| **Real-time Messaging** | WebSocket with exponential backoff reconnection and backfill |
| **Encrypted Channels** | Controller-issued, single-use JWT cipher keys for private channels |
| **Controller Controls** | Role system (controller / relay / listener), kick, promote, transfer control |
| **Transmission Redaction** | Controller/relay soft-delete with content sentinel; audit trail preserved |
| **Transmission TTL** | Per-channel message expiration with a background pruning task |
| **Sound Design** | Ambient carrier tone + event sounds synthesised entirely via Web Audio API |
| **Identity Isolation** | Operator ID and email are never exposed inside a channel — callsign only |

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
- Web Audio API - synthesised ambient carrier tone, no audio files
- Custom WebSocket hook - reconnection, backfill, token lifecycle

**Infrastructure**
- Docker Compose - Postgres 16, Redis 7, API, Frontend
- [testcontainers](https://testcontainers.com/) + [fakeredis](https://github.com/cunla/fakeredis-py) - isolated integration tests

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Client (React)                         │
│  LobbyPage  ──►  RoomPage ──► useChannelSocket ──► WebSocket    │
│                       │                                         │
│               POST /channels/{id}/transmissions                 │
│               GET  /channels/{id}/transmissions (paginated)     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP + WebSocket
┌───────────────────────────▼─────────────────────────────────────┐
│                      FastAPI (port 8000)                        │
│                                                                 │
│  routers/auth.py          POST /auth/register, /login           │
│  routers/channels.py      CRUD + controller controls            │
│  routers/transmissions.py POST, GET, DELETE /transmissions      │
│  routers/cipher_keys.py   POST /cipher-keys, POST /channels/join│
│  routers/ws.py            WS  /ws/channels/{id}?token=...       │
│                                                                 │
│  services/                Business logic layer                  │
│  core/security.py         JWT (access / socket / cipher tokens) │
│  realtime/hub.py          WebSocket registry + Redis fan-out    │
└──────┬────────────────────────────┬─────────────────────────────┘
       │ SQL (psycopg2)             │ redis.asyncio
┌──────▼──────────┐        ┌───────▼──────────────────────────────┐
│  PostgreSQL 16  │        │             Redis 7                  │
│                 │        │                                      │
│  operators      │        │  socket_jti:{jti}   (60s TTL)        │
│  channels       │        │  channel:{id}       (pub/sub channel)│
│  contacts       │        │  wsbucket:{c}:{o}   (token bucket)   │
│  transmissions  │        └──────────────────────────────────────┘
│  cipher_keys    │
└─────────────────┘
```

**Multi-worker fan-out:** The hub publishes every broadcast to a Redis channel (`channel:{id}`). A background subscriber task on each worker re-fans published messages to its locally-registered WebSockets. This means the application scales horizontally — a transmission sent through worker A reaches clients connected to worker B.

---

## Backend

### Domain Model

The codebase uses a consistent vocabulary throughout:

| Term | Meaning |
|------|---------|
| `Operator` | Authenticated user account |
| `Channel` | A chat room; can be public or `is_encrypted` (cipher-key-only) |
| `Contact` | An Operator's current membership in a Channel; carries an anonymous `callsign` |
| `Callsign` | Randomly-generated in-channel pseudonym (e.g. *"Ghost Station"*, *"Signal-and-Null"*) |
| `Controller` | The Channel creator; a Contact with `role=controller` |
| `Transmission` | A message posted in a Channel |
| `Cipher Key` | A single-use JWT granting entry to an encrypted Channel |

**Layer structure:**

```
routers/     HTTP boundary — thin, delegates to services
services/    Business logic; all access control decisions live here
models/      SQLAlchemy ORM (Operator, Channel, Contact, Transmission, CipherKey)
schemas/     Pydantic request/response models
core/        Cross-cutting: config, JWT security, callsign generator, rate limiter, DI
realtime/    WebSocket hub (local registry + Redis pub/sub)
```

### Authentication & Security

Static uses **three distinct JWT token types**, each with different lifetimes and purposes:

#### Access Token (24h)
Standard Bearer token for all HTTP endpoints. Issued on login, stored in `localStorage`. The `type` claim is validated on every decode — a cipher or socket token cannot be replayed as an access token.

```
POST /auth/login  →  { access_token: "eyJ..." }
Authorization: Bearer <access_token>
```

#### Socket Token (60s, one-time-use)
Before opening a WebSocket, the client mints a short-lived socket token:

```
POST /auth/socket-token  →  { socket_token: "eyJ...", jti: "uuid" }
WS  /ws/channels/{id}?token=<socket_token>
```

On connection, the server atomically consumes the JTI from Redis using `GETDEL`. If the key is absent (already used or expired), the connection is rejected with close code `4001`. This prevents token replay attacks even within the 60-second window.

#### Cipher Key Token (configurable, default 24h, one-time-use)
Encrypted-channel cipher keys embed a JWT. A matching `CipherKey` row in PostgreSQL tracks the JTI; `used_at` is set on first consumption and the token cannot be reused.

```
POST /channels/{id}/cipher-keys?expires_in_seconds=86400
  →  { token: "eyJ...", expires_at: "..." }

POST /channels/join?token=<cipher_key_token>
  →  OwnContactResponse
```

#### Password Hashing
Passwords are **SHA-256 pre-hashed** before bcrypt to neutralise bcrypt's 72-byte truncation vulnerability — a long passphrase will never silently collide with a shorter one.

```python
def hash_password(password: str) -> str:
    pre = hashlib.sha256(password.encode()).hexdigest()
    return bcrypt.hashpw(pre.encode(), bcrypt.gensalt()).decode()
```

### WebSocket Protocol

**Endpoint:** `GET /ws/channels/{channel_id}?token=<socket_token>`

Authentication and contact are verified before the connection is accepted. Auth/contact failures arrive as WebSocket close codes, never as JSON frames:

| Code | Meaning |
|------|---------|
| `4001` | Unauthorized (bad/expired/used token, operator not found) |
| `4003` | Forbidden (no Contact in this channel) |

**Client → Server frames:**

```jsonc
{ "op": "transmission", "content": "..." }   // 1–4000 chars after strip
```

**Server → All connected clients:**

```jsonc
{ "op": "transmission", "id": 42, "channel_id": 1, "callsign": "Ghost Station",
  "content": "...", "is_deleted": false, "created_at": "..." }

{ "op": "enter",   "callsign": "Signal-and-Null" }
{ "op": "depart",  "callsign": "Signal-and-Null" }
{ "op": "dissolve" }
{ "op": "redact",  "transmission_id": 42 }
{ "op": "promote", "callsign": "...", "role": "relay" }
```

**Server → Sender only (error):**

```jsonc
{ "op": "error", "detail": "Transmitting too quickly. Slow down." }
```

**Reconnection strategy (client):** Exponential backoff — `500ms × 2ⁿ`, capped at 30 seconds, maximum 8 retries. On each reconnect the client requests a new socket token and backfills missed transmissions using the highest transmission ID seen before disconnect. Close codes `4001`/`4003` suppress reconnection entirely.

### Rate Limiting

Two independent layers of rate limiting:

**HTTP (slowapi)** — per-IP, per-endpoint limits enforced at the router layer. Examples:
- `POST /auth/login` — 20/minute
- `POST /channels/{id}/enter` — 30/minute
- `GET /channels` — 60/minute

**WebSocket (Redis token bucket)** — per-Operator per-Channel, implemented as a Lua script executed atomically in Redis:

```lua
-- KEYS[1] = wsbucket:{channel_id}:{operator_id}
-- Capacity: 10 tokens, Refill: 1 token/second
local tokens = math.min(capacity, tokens + elapsed * refill_rate)
if tokens < 1 then return 0 end
tokens = tokens - 1
-- store updated state, set 120s expiry
return 1
```

Rate-limited transmissions receive an `error` frame; the WebSocket is not closed. The Lua script executes atomically — no race conditions across concurrent requests.

### Real-time Hub

`app/realtime/hub.py` bridges WebSocket connections and Redis pub/sub:

```python
# Register/unregister WebSocket connections (per worker, in-memory)
hub.register(channel_id, websocket)
hub.unregister(channel_id, websocket)

# Broadcast to all clients across all workers
await hub.broadcast(channel_id, {"op": "transmission", ...})
```

`broadcast()` serialises the payload and publishes to `channel:{id}` on Redis. A background task (started during application lifespan) subscribes to `channel:*` and fans each message out to locally-registered WebSocket connections. Dead sockets (those that raise on send) are pruned automatically.

### API Reference

<details>
<summary><strong>Authentication</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | — | Create a new Operator account |
| `POST` | `/auth/login` | — | Authenticate and receive an access token |
| `POST` | `/auth/socket-token` | Bearer | Mint a one-time 60s WebSocket token |

</details>

<details>
<summary><strong>Channels</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/channels` | Bearer | Create a channel (public or encrypted) |
| `GET` | `/channels` | Bearer | List visible channels (public + operator's encrypted) |
| `GET` | `/channels/{id}` | Bearer | Get channel detail + contact count |
| `POST` | `/channels/{id}/enter` | Bearer | Enter a public channel (creates Contact + callsign) |
| `DELETE` | `/channels/{id}/depart` | Bearer | Depart a channel (deletes Contact; controllers cannot depart) |
| `DELETE` | `/channels/{id}` | Bearer | Dissolve channel (controller only; broadcasts `dissolve`) |

</details>

<details>
<summary><strong>Contacts</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/channels/{id}/contacts` | Bearer | List all current contacts |
| `GET` | `/channels/{id}/contacts/me` | Bearer | Get own contact (callsign, role) |
| `DELETE` | `/channels/{id}/contacts/callsign/{callsign}` | Bearer | Kick by callsign (controller/relay) |
| `POST` | `/channels/{id}/transfer/callsign` | Bearer | Transfer control by callsign |
| `PATCH` | `/channels/{id}/contacts/callsign/{callsign}/role` | Bearer | Promote/demote by callsign (controller only) |

</details>

<details>
<summary><strong>Transmissions</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/channels/{id}/transmissions` | Bearer | Post a transmission (also available via WebSocket) |
| `GET` | `/channels/{id}/transmissions` | Bearer | Paginated history (`?limit=50&before_id=...`) |
| `DELETE` | `/channels/{id}/transmissions/{transmission_id}` | Bearer | Redact a transmission (controller/relay) |

</details>

<details>
<summary><strong>Cipher Keys</strong></summary>

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/channels/{id}/cipher-keys` | Bearer | Create cipher key (controller only; `?expires_in_seconds=86400`) |
| `POST` | `/channels/join` | Bearer | Consume a cipher key (`?token=...`); creates Contact |

</details>

<details>
<summary><strong>Real-time</strong></summary>

| Protocol | Path | Description |
|----------|------|-------------|
| `WebSocket` | `/ws/channels/{id}?token=...` | Persistent connection for live transmissions and contact events |

</details>

---

## Frontend

### State Management

Authentication state is held in a **React Context** backed by `localStorage`, with no external state library. The pattern is intentionally minimal — the only global state is the JWT access token.

```typescript
// src/store/auth.tsx
interface AuthState {
  token: string | null
  setToken: (t: string) => void
  clearToken: () => void
}
```

Token is persisted under the key `static:token`. All API calls thread the token as a parameter rather than pulling from a global store, making data flow explicit and testable.

### WebSocket Hook

`src/lib/useChannelSocket.ts` encapsulates the full WebSocket lifecycle:

1. **Token acquisition** — fetches a one-shot socket token via `POST /auth/socket-token`
2. **Connection** — opens `ws://…/ws/channels/{id}?token=<socket_token>`
3. **Message dispatch** — calls `onMessage(msg: WsMessage)` for each valid frame
4. **Reconnection** — on unexpected close, schedules reconnect with exponential backoff (`500ms × 2ⁿ`, cap 30s, max 8 retries); `4001`/`4003` close codes suppress reconnection
5. **Backfill** — on reconnect, calls `onReconnect(lastSeenTransmissionId)` so the page can fetch missed transmissions
6. **Cleanup** — closes the socket with code `1000` on unmount

```typescript
const { wsStatus, sendTransmission } = useChannelSocket({
  channelId,
  token,
  enabled: wsReady,
  onMessage: handleWsMessage,
  onReconnect: fetchMissedTransmissions,
})
```

`wsStatus` surfaces as `'connecting' | 'connected' | 'reconnecting' | 'dead'` — the UI reflects each state visually.

### Callsign Renderer

`src/lib/callsign.ts` generates deterministic SVG stamps client-side with no server round-trip. Given the same callsign string, it always produces the same visual.

**Algorithm:**
1. Hash the callsign string with FNV-1a to produce a seed
2. Run a seeded LCG (linear congruential generator) for reproducible randomness
3. Pick a shape (circle, triangle, pentagon, hexagon), 1–2 signal-pattern glyphs from a 20-glyph alphabet, 3–6 perimeter accent dots, and one of 5 amber colour shades — all deterministically from the seed

The same callsign always renders identically across sessions and devices with no database lookup or image storage.

### Sound Engine

`src/lib/sounds.ts` synthesises all audio at runtime using the Web Audio API — no audio files are bundled or fetched.

| Sound | Implementation |
|-------|---------------|
| Carrier tone | Filtered carrier oscillator with 0.28 Hz amplitude flutter |
| Transmission received | Bandpass-filtered noise burst (radio squelch) |
| Transmission sent | Short square-wave morse-key click (700 → 400 Hz, 80ms) |
| Signal loss | Sawtooth sweep (320 → 80 Hz, 700ms) with noise burst prefix |
| Signal acquired | Three ascending morse-key pulses (400 → 600 → 800 Hz) |

All sound is off by default and toggled per-session. The approach eliminates CDN dependencies and avoids browser autoplay restrictions (sounds only play after the first user interaction).

---

## Database Schema

```
operators
  id              SERIAL PK
  email           VARCHAR(255) UNIQUE NOT NULL
  hashed_password VARCHAR(255) NOT NULL
  created_at      TIMESTAMP (server default)

channels
  id                        SERIAL PK
  name                      VARCHAR(100) UNIQUE NOT NULL
  description               VARCHAR(300)
  is_encrypted              BOOLEAN NOT NULL DEFAULT FALSE
  transmission_ttl_seconds  INTEGER  -- NULL = no expiration
  created_by                FK → operators.id
  created_at                TIMESTAMP

contacts
  operator_id  FK → operators.id  ─┐
  channel_id   FK → channels.id   ─┴─ composite PK
  callsign     VARCHAR(80) NOT NULL
  role         ENUM(controller, relay, listener) NOT NULL
  entered_at   TIMESTAMP
  UNIQUE (channel_id, callsign)  -- prevents callsign collision within a channel

transmissions
  id          SERIAL PK
  channel_id  FK → channels.id
  operator_id FK → operators.id  -- nullable; never exposed in API responses
  callsign    VARCHAR(80) NOT NULL  -- snapshotted at post time
  content     TEXT NOT NULL
  deleted_at  TIMESTAMP  -- NULL = visible; set = soft-deleted
  created_at  TIMESTAMP
  INDEX (channel_id, id)  -- efficient cursor-based pagination

cipher_keys
  id          SERIAL PK
  channel_id  FK → channels.id
  created_by  FK → operators.id
  used_by     FK → operators.id  -- NULL until consumed
  jti         VARCHAR(64) UNIQUE NOT NULL
  expires_at  TIMESTAMP NOT NULL
  used_at     TIMESTAMP  -- NULL until consumed
  created_at  TIMESTAMP
```

**Key design decisions:**
- **Composite PK on contacts** — `(operator_id, channel_id)` enforces one active contact per operator per channel at the database level
- **Callsign snapshotted on transmissions** — preserves message attribution even after a contact is deleted (operator departs)
- **Soft-delete on transmissions** — `deleted_at` instead of hard `DELETE`; content is replaced with a sentinel string in API responses but the row is retained for audit
- **Unique `(channel_id, callsign)`** — collision resistance enforced by the database; `assign_contact()` retries up to 8 times on `IntegrityError` before failing with `503`

---

## Getting Started

### Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/static-API.git
cd static-API

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
| `DATABASE_URL` | Yes | PostgreSQL DSN — `postgresql://user:pass@host:port/db` |
| `REDIS_URL` | Yes | Redis DSN — `redis://host:port` |
| `SECRET_KEY` | Yes | JWT signing key — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

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

Tests use `pytest` with **testcontainers** (a real Postgres container) and **fakeredis** for complete isolation — no mocking of database behaviour.

```bash
cd backend

# Run all tests
TESTING=1 uv run pytest

# Run a specific file
TESTING=1 uv run pytest tests/test_channels.py

# Run a single test
TESTING=1 uv run pytest tests/test_ws.py::test_transmission_rate_limit
```

Test coverage spans:
- **Auth** (`test_auth.py`) — registration, login, duplicate email, bad credentials, socket token lifecycle
- **Channels** (`test_channels.py`) — CRUD, encrypted access control, controller operations, cipher key flow
- **Transmissions** (`test_transmissions.py`) — pagination, soft-delete, redaction permissions
- **WebSocket** (`test_ws.py`) — connection auth, message protocol, rate limiting, contact broadcasting

---

## Project Structure

```
static-API/
├── docker-compose.yml
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       ├── 0002_phase4.py
│   │       └── 0003_rebrand.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_channels.py
│   │   ├── test_transmissions.py
│   │   └── test_ws.py
│   └── app/
│       ├── main.py              # App factory, lifespan, CORS, startup
│       ├── database.py          # SQLAlchemy engine + session factory
│       ├── core/
│       │   ├── config.py        # Pydantic settings (env vars)
│       │   ├── security.py      # JWT creation/validation, bcrypt
│       │   ├── dependencies.py  # FastAPI DI: get_db, get_current_operator
│       │   ├── callsigns.py     # Callsign generator
│       │   └── limiter.py       # slowapi instance
│       ├── models/
│       │   ├── operator.py
│       │   ├── channel.py
│       │   ├── contact.py
│       │   ├── transmission.py
│       │   └── cipher_key.py
│       ├── schemas/
│       │   ├── auth.py
│       │   ├── operator.py
│       │   ├── channel.py
│       │   ├── contact.py
│       │   └── transmission.py
│       ├── services/
│       │   ├── auth_service.py
│       │   ├── channel_service.py
│       │   ├── contact_service.py
│       │   ├── transmission_service.py
│       │   ├── cipher_key_service.py
│       │   └── redis.py
│       ├── routers/
│       │   ├── auth.py
│       │   ├── channels.py
│       │   ├── transmissions.py
│       │   ├── cipher_keys.py
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
        │   ├── channels.ts
        │   └── types.ts         # TypeScript interfaces + WsMessage discriminated union
        ├── store/
        │   └── auth.tsx         # AuthContext, useAuth hook, localStorage
        ├── lib/
        │   ├── useChannelSocket.ts  # WS lifecycle, reconnection, backfill
        │   ├── callsign.ts          # Deterministic SVG callsign renderer
        │   └── sounds.ts            # Web Audio API synthesis
        ├── components/
        │   └── Toast.tsx
        └── pages/
            ├── LoginPage.tsx
            ├── RegisterPage.tsx
            ├── LobbyPage.tsx
            ├── RoomPage.tsx
            └── InvitePage.tsx
```