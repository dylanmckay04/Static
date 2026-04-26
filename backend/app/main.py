import logging
import os
import time
import sqlalchemy
from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter
from app.database import engine
from app.routers import auth, rooms, debug

logger = logging.getLogger(__name__)

def wait_for_db(retries=10, delay=3):
    for attempt in range(retries):
        try:
            with engine.connect():
                logger.info("Database is ready")
                return
        except sqlalchemy.exc.OperationalError:
            logger.warning("Database not ready, retrying in %ds... (attempt %d/%d)", delay, attempt + 1, retries)
            time.sleep(delay)
    raise Exception("Could not connect to database after multiple retries")         

if not os.getenv("TESTING"):
    wait_for_db()   

app = FastAPI(title="Ouija API", version="0.1.0")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
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
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception:: %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred"}
    )
    

@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(debug.router)