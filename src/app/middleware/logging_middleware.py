"""FastAPI middleware for structured request logging."""

from __future__ import annotations

import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging.context import bind_context, clear_context, ensure_trace_id
from app.logging.events import REQUEST_COMPLETED, REQUEST_FAILED, REQUEST_STARTED
from app.logging.wrapper import log_boundary, log_error


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        start_ts = time.monotonic()
        trace_id = ensure_trace_id(request.headers.get("x-trace-id"))
        bind_context(trace_id=trace_id)

        request_path = request.url.path
        request_method = request.method

        log_boundary(
            event=REQUEST_STARTED,
            status="started",
            message="Request started",
            method=request_method,
            path=request_path,
        )

        try:
            response = await call_next(request)
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            response.headers["x-trace-id"] = trace_id
            log_boundary(
                event=REQUEST_COMPLETED,
                status="completed",
                message="Request completed",
                method=request_method,
                path=request_path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            log_error(
                event=REQUEST_FAILED,
                status="failed",
                message="Request failed",
                method=request_method,
                path=request_path,
                duration_ms=duration_ms,
                error_type="internal",
                error_stage="ingest",
                severity="high",
                error_message=str(exc),
            )
            raise
        finally:
            clear_context()
