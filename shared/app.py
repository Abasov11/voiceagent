import logging
import os

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from shared.db import engine
from shared.settings import get_settings


def _setup_structlog(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=True,
    )


_setup_structlog(os.environ.get("LOG_LEVEL", "INFO"))
log = structlog.get_logger("voiceagent")

settings = get_settings()
app = FastAPI(title="VoiceAgent backend", version="0.1.0")


@app.middleware("http")
async def access_log(request: Request, call_next):
    response = await call_next(request)
    log.info(
        "http",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        client=request.client.host if request.client else None,
    )
    return response


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    """Liveness — 200 если процесс жив."""
    return "ok"


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness — 200 если БД отвечает и миграции применены."""
    out: dict[str, object] = {"status": "ok"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            res = conn.execute(text("SELECT version_num FROM alembic_version"))
            row = res.first()
            out["alembic_version"] = row[0] if row else None
    except Exception as exc:
        return JSONResponse({"status": "fail", "error": str(exc)[:200]}, status_code=503)
    out["app_env"] = settings.app_env
    out["app_version"] = "0.1.0"
    return JSONResponse(out)


@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "VoiceAgent backend — see /healthz, /readyz, /docs"


# Routers
from call_analytics.router import router as call_analytics_router  # noqa: E402
from dashboard.admin import router as admin_router  # noqa: E402
from dashboard.router import router as dashboard_router  # noqa: E402
from zvonar.router import router as zvonar_router  # noqa: E402

app.include_router(call_analytics_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(zvonar_router)


@app.get("/debug/integrations", tags=["debug"])
async def debug_integrations() -> dict:
    """Smoke-проверка наличия секретов и того, что внешние API хотя бы пингуются."""
    s = get_settings()
    out: dict = {
        "alfa_crm_key": bool(s.alfa_crm_api_key),
        "onlinepbx_user": bool(s.onlinepbx_user),
        "s3_access_key": bool(s.s3_access_key),
        "s3_bucket": s.s3_bucket,
        "assemblyai_key": bool(s.assemblyai_api_key),
        "openai_key": bool(s.openai_api_key),
        "anthropic_key": bool(s.anthropic_api_key),
        "elevenlabs_key": bool(s.elevenlabs_api_key),
        "voximplant_key": bool(s.voximplant_api_key),
        "green_api_token": bool(s.green_api_token),
    }
    # Альфа CRM ping (если ключ есть)
    if s.alfa_crm_api_key:
        from shared.alfacrm import AlfaCrmClient

        client = AlfaCrmClient(
            base_url=s.alfa_crm_base_url,
            api_key=s.alfa_crm_api_key,
            email=s.alfa_crm_email,
            branch_id=s.alfa_crm_branch_id,
        )
        out["alfa_crm_login_ok"] = await client.ping()
        await client.aclose()
    return out
