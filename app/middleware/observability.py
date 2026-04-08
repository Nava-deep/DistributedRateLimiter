from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import log_event
from app.core.metrics import observe_http_request


def resolve_route_label(request: Request) -> str:
    return getattr(request.scope.get("route"), "path", request.url.path)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started_at = time.perf_counter()
        logger = request.app.state.logger

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_seconds = time.perf_counter() - started_at
            route = resolve_route_label(request)
            observe_http_request(request.method, route, 500, latency_seconds)
            log_event(
                logger,
                logging.ERROR,
                "request_error",
                method=request.method,
                route=route,
                error=str(exc),
                latency_ms=round(latency_seconds * 1000, 3),
            )
            raise

        latency_seconds = time.perf_counter() - started_at
        route = resolve_route_label(request)
        observe_http_request(request.method, route, response.status_code, latency_seconds)
        response.headers.setdefault("X-Instance-Name", request.app.state.settings.app_instance_name)
        log_event(
            logger,
            logging.INFO,
            "request_complete",
            method=request.method,
            route=route,
            status_code=response.status_code,
            latency_ms=round(latency_seconds * 1000, 3),
        )
        return response

