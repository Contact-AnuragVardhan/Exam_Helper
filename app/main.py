from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import config
from database.session import init_db
from services.logger import get_logger
from whatsapp.webhook import build_router


log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "Application starting environment=%s simulator=%s log_level=%s",
        config.APP_ENV,
        config.ENABLE_SIMULATOR,
        config.LOG_LEVEL,
    )
    try:
        init_db()
        log.info("Application startup complete")
        yield
    except Exception:
        log.exception("Application lifecycle failed")
        raise
    finally:
        log.info("Application shutdown complete")


app = FastAPI(title="Exam Helper", lifespan=lifespan)
app.include_router(build_router())


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex[:12]
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (perf_counter() - started) * 1000
        log.exception(
            "Request failed request_id=%s method=%s path=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = (perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    if response.status_code >= 500:
        write_log = log.error
        reason = "server_error"
    elif response.status_code == 404:
        write_log = log.warning
        reason = "route_not_found"
    elif response.status_code >= 400:
        write_log = log.warning
        reason = "client_error"
    else:
        write_log = log.info
        reason = "success"
    write_log(
        "Request complete request_id=%s method=%s path=%s status=%s reason=%s duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        reason,
        elapsed_ms,
    )
    return response

if config.ENABLE_SIMULATOR:
    from simulator.router import build_simulator_router

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_simulator_router())


@app.get("/health")
def health():
    log.debug("Health check succeeded")
    return {"status": "ok"}
