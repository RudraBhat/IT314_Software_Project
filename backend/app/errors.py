"""Consistent error responses: {"error": {"code", "message", "details"}} (SRS s.15.7)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("drch.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{entity} not found")


def database_unavailable() -> ApiError:
    """503 for routes that need the database when DATABASE_URL is not configured.

    Never answer such a request with invented demo data: the operator must see
    that the system is offline.
    """
    return ApiError(503, "DATABASE_UNAVAILABLE", "Database connection required")


def conflict(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(409, code, message, details)


def _body(code: str, message: str, details: Any = None) -> dict:
    # Details may hold UUIDs, dates or Decimals from database rows.
    return {"error": {"code": code, "message": message, "details": jsonable_encoder(details)}}


_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status, content=_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        # EH-25: an unsupported scenario value has its own stable code.
        if any("scenario" in err["loc"] for err in errors):
            return JSONResponse(
                status_code=422,
                content=_body(
                    "UNSUPPORTED_SCENARIO",
                    "Scenario must be one of: cyclone, industrial_fire, urban_flooding",
                    errors,
                ),
            )
        return JSONResponse(
            status_code=422,
            content=_body("VALIDATION_FAILED", "Request validation failed", errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(code, str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        import psycopg

        from app.config import ConfigError

        if isinstance(exc, ConfigError):
            logger.warning(f"Configuration error: {exc}")
            return JSONResponse(
                status_code=503,
                content=_body("CONFIG_ERROR", f"Service configuration error: {exc}"),
            )
        if isinstance(exc, psycopg.Error):
            logger.warning(f"Database error: {exc}")
            return JSONResponse(
                status_code=503,
                content=_body("DATABASE_UNAVAILABLE", "The database is temporarily unavailable or offline."),
            )

        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_body("INTERNAL_ERROR", "An unexpected server error occurred"),
        )
