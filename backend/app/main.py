"""Secure Tokens - Webhook Automation prototype API.

PROTOTYPE: demonstrates the proposed webhook/event layer. Execution, evaluation, settlement and
reserve values are simulated; this is not the full Secure Tokens platform.
"""
import logging
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.api import claims, deliveries, events, stats, subscriptions, tasks
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.ids import new_id
from app.logging_config import configure_logging, correlation_id_var
from app.models import Developer, ReserveAccount
from app.security.authentication import hash_api_key

log = logging.getLogger(__name__)


def seed_demo() -> None:
    s = get_settings()
    db = SessionLocal()
    try:
        h = hash_api_key(s.demo_api_key)
        if db.scalar(select(Developer).where(Developer.api_key_hash == h)) is None:
            db.add(Developer(id=new_id("dev"), name="Demo Developer", api_key_hash=h))
        if db.get(ReserveAccount, "default") is None:
            db.add(ReserveAccount(id="default", balance=s.reserve_initial_balance))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    s = get_settings()
    stop = threading.Event()
    if s.run_mode == "lite":
        init_db()
        from app.workers.run import start_background
        start_background(stop)  # publisher + delivery worker run in-process in lite mode
    if s.seed_demo:
        seed_demo()
    if s.is_production and not s.secret_encryption_key:
        raise RuntimeError("SECRET_ENCRYPTION_KEY must be set in production")
    yield
    stop.set()


app = FastAPI(title="Secure Tokens - Webhook Automation Prototype", version="0.1.0", lifespan=lifespan,
              description="Prototype of the proposed webhook automation layer. Simulated execution, evaluation "
                          "and settlement; demo data only.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Correlation-ID"])


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex[:12]
    token = correlation_id_var.set(cid)
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
    response.headers["X-Correlation-ID"] = cid
    return response


def _err(status: int, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": status, "message": message, "details": details}})


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):
    return _err(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exc(_: Request, exc: RequestValidationError):
    return _err(422, "Validation error", [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()])


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready():
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        return _err(503, "Database unavailable", str(type(exc).__name__))
    return {"status": "ready", "run_mode": get_settings().run_mode}


for r in (tasks.router, claims.router, subscriptions.router, events.router, deliveries.router, stats.router):
    app.include_router(r)
