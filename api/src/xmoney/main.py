"""HTTP application. Sandbox mode is checked before the process serves traffic."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from xmoney import __version__
from xmoney.auth.routes import router as auth_router
from xmoney.config import get_settings
from xmoney.errors import XMoneyError
from xmoney.identity.routes import router as identity_router
from xmoney.inbox.routes import router as inbox_router
from xmoney.ledger.routes import router as ledger_router
from xmoney.payments.daraja_mock import DarajaMockState, build_daraja_router
from xmoney.payments.routes import router as payments_router
from xmoney.transfers.routes import router as transfers_router

logger = logging.getLogger("xmoney")

_NOTICE = (
    "Sandbox prototype. Not a Central Bank of Kenya licensed payment service. "
    "Not affiliated with X Corp. This process cannot move real money."
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.warning("X Money for Kenya is running in SANDBOX mode. It cannot move real money.")
    yield


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(
        title="X Money for Kenya",
        version=__version__,
        summary="Sandbox-only pay-by-@handle wallet.",
        description=(
            "Sandbox-only prototype of a pay-by-@handle wallet for Kenya.\n\n"
            "This process refuses to run unless sandbox mode is on. It is not a "
            "Central Bank of Kenya licensed payment service, it is not affiliated "
            "with X Corp., and it cannot move real money."
        ),
        lifespan=_lifespan,
    )
    app.state.daraja = DarajaMockState()

    @app.middleware("http")
    async def mark_sandbox(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Sandbox"] = "true"
        response.headers["X-Moves-Real-Money"] = "false"
        return response

    @app.exception_handler(XMoneyError)
    def handle_domain_error(_request: Request, exc: XMoneyError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": str(exc)},
        )

    @app.get("/", tags=["meta"])
    def root() -> dict[str, object]:
        return {
            "service": "X Money for Kenya",
            "version": __version__,
            "mode": "sandbox",
            "moves_real_money": False,
            "docs": "/docs",
            "notice": _NOTICE,
        }

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "xmoney-kenya",
            "mode": "sandbox",
            "moves_real_money": False,
        }

    app.include_router(identity_router, prefix="/v1")
    app.include_router(auth_router, prefix="/v1")
    app.include_router(inbox_router, prefix="/v1")
    app.include_router(payments_router, prefix="/v1")
    app.include_router(transfers_router, prefix="/v1")
    app.include_router(ledger_router, prefix="/v1")
    app.include_router(build_daraja_router(), prefix="/sandbox/daraja")
    return app


app = create_app()


def main() -> None:
    uvicorn.run("xmoney.main:app", host="0.0.0.0", port=8000)
