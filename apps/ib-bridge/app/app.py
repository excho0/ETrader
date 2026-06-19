from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import TradingAPIError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.mcp_server import build_secure_http_mcp_app, set_active_trading_service
from app.models.error import ErrorResponse
from app.services.trading import trading_service_lifespan

logger = logging.getLogger("uvicorn.app.lifecycle")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        settings.log_level,
        log_path=settings.resolved_log_path(),
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    mcp_app = build_secure_http_mcp_app()
    mcp_session_manager = mcp_app.state.mcp_session_manager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "Starting ib-bridge env=%s api=%s:%s gateway=%s[%s/%s] tws=%s[%s/%s] auto_connect=%s",
            settings.env,
            settings.api_host,
            settings.api_port,
            settings.ib_gateway_host,
            settings.ib_gateway_paper_port,
            settings.ib_gateway_live_port,
            settings.ib_tws_host,
            settings.ib_tws_paper_port,
            settings.ib_tws_live_port,
            settings.auto_connect_on_startup,
        )
        async with mcp_session_manager.run():
            async with trading_service_lifespan(settings) as trading_service:
                app.state.settings = settings
                app.state.trading_service = trading_service
                set_active_trading_service(trading_service)
                logger.info("Trading service initialized")
                yield
                set_active_trading_service(None)
        logger.info("Trading service shutdown complete")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Async trading bridge between AI agents and IB Gateway.",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router)
    app.mount("/mcp", mcp_app)

    @app.exception_handler(TradingAPIError)
    async def handle_trading_api_error(request: Request, exc: TradingAPIError) -> JSONResponse:
        payload = ErrorResponse(
            error=exc.message,
            code=exc.code,
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=400, content=payload.model_dump())

    return app
