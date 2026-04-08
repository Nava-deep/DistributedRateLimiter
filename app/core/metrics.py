from __future__ import annotations

from prometheus_client import Counter, Histogram, REGISTRY, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.responses import Response


HTTP_REQUESTS_TOTAL = Counter(
    "distributed_rate_limiter_http_requests_total",
    "Total HTTP requests handled by the service.",
    ["method", "route", "status_code"],
)

RATE_LIMIT_ALLOWED_TOTAL = Counter(
    "distributed_rate_limiter_allowed_requests_total",
    "Requests allowed by the rate limiter.",
    ["algorithm", "selector_kind"],
)

RATE_LIMIT_BLOCKED_TOTAL = Counter(
    "distributed_rate_limiter_blocked_requests_total",
    "Requests blocked by the rate limiter.",
    ["algorithm", "selector_kind"],
)

REQUEST_LATENCY_SECONDS = Histogram(
    "distributed_rate_limiter_request_latency_seconds",
    "Request latency across all HTTP handlers.",
    ["method", "route", "status_code"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0),
)

POLICY_CACHE_HITS_TOTAL = Counter(
    "distributed_rate_limiter_policy_cache_hits_total",
    "Policy cache hits served from Redis.",
)

POLICY_CACHE_MISSES_TOTAL = Counter(
    "distributed_rate_limiter_policy_cache_misses_total",
    "Policy cache misses that required PostgreSQL access.",
)

REDIS_ERRORS_TOTAL = Counter(
    "distributed_rate_limiter_redis_errors_total",
    "Redis errors encountered by the service.",
    ["operation"],
)


def observe_http_request(method: str, route: str, status_code: int, latency_seconds: float) -> None:
    labels = {"method": method, "route": route, "status_code": str(status_code)}
    HTTP_REQUESTS_TOTAL.labels(**labels).inc()
    REQUEST_LATENCY_SECONDS.labels(**labels).observe(latency_seconds)


def mark_rate_limit_allowed(algorithm: str, selector_kind: str) -> None:
    RATE_LIMIT_ALLOWED_TOTAL.labels(algorithm=algorithm, selector_kind=selector_kind).inc()


def mark_rate_limit_blocked(algorithm: str, selector_kind: str) -> None:
    RATE_LIMIT_BLOCKED_TOTAL.labels(algorithm=algorithm, selector_kind=selector_kind).inc()


def mark_policy_cache_hit() -> None:
    POLICY_CACHE_HITS_TOTAL.inc()


def mark_policy_cache_miss() -> None:
    POLICY_CACHE_MISSES_TOTAL.inc()


def mark_redis_error(operation: str) -> None:
    REDIS_ERRORS_TOTAL.labels(operation=operation).inc()


def render_metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

