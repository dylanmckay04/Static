import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sqlalchemy
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.limiter import limiter
from app.database import SessionLocal, engine
from app.realtime.hub import start_subscriber
from app.routers import auth, debug, channels, transmissions, ws
from app.routers import cipher_keys

logger = logging.getLogger(__name__)


def wait_for_db(retries: int = 10, delay: int = 3) -> None:
    for attempt in range(retries):
        try:
            with engine.connect():
                logger.info("Database is ready")
                return
        except sqlalchemy.exc.OperationalError:
            logger.warning(
                "Database not ready, retrying in %ds... (attempt %d/%d)",
                delay, attempt + 1, retries,
            )
            time.sleep(delay)
    raise Exception("Could not connect to database after multiple retries")


if not os.getenv("TESTING"):
    wait_for_db()


async def _prune_expired_transmissions() -> None:
    """Background task: soft-delete transmissions older than their channel's TTL.

    Runs every 60 seconds. Only touches channels with transmission_ttl_seconds set.
    Each pruning pass is wrapped in its own DB session so failures don't leak.
    """
    from backend.app.models.channel import Channel
    from backend.app.models.transmission import Transmission
    import sqlalchemy as sa

    while True:
        try:
            await asyncio.sleep(60)
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                ttl_channels = (
                    db.query(Channel)
                    .filter(Channel.transmission_ttl_seconds.isnot(None))
                    .all()
                )
                total_pruned = 0
                for channel in ttl_channels:
                    cutoff = sa.func.now() - sa.text(
                        f"interval '{channel.transmission_ttl_seconds} seconds'"
                    )
                    result = (
                        db.query(Transmission)
                        .filter(
                            Transmission.channel_id == channel.id,
                            Transmission.deleted_at.is_(None),
                            Transmission.created_at < cutoff,
                        )
                        .update(
                            {"deleted_at": now},
                            synchronize_session=False,
                        )
                    )
                    total_pruned += result
                if total_pruned:
                    db.commit()
                    logger.info("Pruned %d expired transmissions", total_pruned)
            except Exception:
                logger.exception("Error during transmission pruning pass")
                db.rollback()
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Whisper pruning task cancelled")
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks on boot; cancel them on shutdown."""
    subscriber_task = asyncio.create_task(start_subscriber())
    pruner_task     = asyncio.create_task(_prune_expired_transmissions())
    try:
        yield
    finally:
        for task in (subscriber_task, pruner_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Static API",
    description=(
        "A real-time platform for anonymous shortwave channels. Operators open Channels, "
        "connect as Contacts with ephemeral callsigns, and exchange Transmissions "
        "across the static."
    ),
    version="0.5.0",
    lifespan=lifespan,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version,
        description=app.description, routes=app.routes,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict) and "security" in operation:
                operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://veil-phi.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred"})


@app.get("/health", tags=["meta"])
def health_check():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(channels.router)
app.include_router(cipher_keys.router)
app.include_router(transmissions.router)
app.include_router(ws.router)
app.include_router(debug.router)
