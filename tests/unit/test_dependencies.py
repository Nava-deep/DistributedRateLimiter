from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.core.dependencies import (
    enforce_rate_limit,
    get_db_session,
    get_health_service,
    get_policy_service,
    get_rate_limiter,
)
from app.services.rate_limiter import RateLimitDecision


def build_request() -> Request:
    app_state = SimpleNamespace(
        db=SimpleNamespace(session=lambda: None),
        redis=object(),
        settings=Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        ),
        policy_snapshot=object(),
        logger=object(),
        local_fallback_limiter=object(),
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/demo/protected",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "path_params": {},
        "route": SimpleNamespace(path="/demo/protected"),
        "state": {},
        "app": SimpleNamespace(state=app_state),
    }
    request = Request(scope)
    return request


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_db_session_yields_session_from_manager() -> None:
    yielded_session = object()

    @asynccontextmanager
    async def session_manager():
        yield yielded_session

    request = build_request()
    request.app.state.db = SimpleNamespace(session=session_manager)

    generator = get_db_session(request)
    session = await generator.__anext__()

    assert session is yielded_session
    with pytest.raises(StopAsyncIteration):
        await generator.__anext__()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_policy_service_uses_request_state_objects() -> None:
    request = build_request()
    session = object()

    service = await get_policy_service(request, session)

    assert service.session is session
    assert service.redis_client is request.app.state.redis
    assert service.snapshot_store is request.app.state.policy_snapshot


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_rate_limiter_uses_request_state_objects() -> None:
    request = build_request()
    policy_service = object()

    service = await get_rate_limiter(request, policy_service)

    assert service.policy_service is policy_service
    assert service.redis_client is request.app.state.redis
    assert service.local_fallback_limiter is request.app.state.local_fallback_limiter


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_health_service_uses_request_state_objects() -> None:
    request = build_request()

    service = await get_health_service(request)

    assert service.settings is request.app.state.settings
    assert service.db_manager is request.app.state.db
    assert service.redis_client is request.app.state.redis


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enforce_rate_limit_returns_without_headers_when_no_policy() -> None:
    request = build_request()
    response = Response()
    rate_limiter = AsyncMock()
    rate_limiter.evaluate.return_value = (None, None)

    await enforce_rate_limit(request, response, rate_limiter)

    assert response.headers.get("X-RateLimit-Limit") is None
    assert not hasattr(request.state, "rate_limit_decision")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enforce_rate_limit_sets_headers_and_state_for_allowed_request() -> None:
    request = build_request()
    response = Response()
    decision = RateLimitDecision(
        allowed=True,
        limit=10,
        remaining=9,
        reset_at_epoch_seconds=100,
        retry_after_seconds=0,
    )
    policy = SimpleNamespace(name="allowed-policy")
    rate_limiter = AsyncMock()
    rate_limiter.evaluate.return_value = (decision, policy)

    await enforce_rate_limit(request, response, rate_limiter)

    assert response.headers["X-RateLimit-Limit"] == "10"
    assert request.state.rate_limit_decision == decision
    assert request.state.effective_policy == policy


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enforce_rate_limit_raises_fail_closed_detail_when_degraded() -> None:
    request = build_request()
    response = Response()
    decision = RateLimitDecision(
        allowed=False,
        limit=10,
        remaining=0,
        reset_at_epoch_seconds=100,
        retry_after_seconds=1,
        degraded=True,
        local_fallback=False,
    )
    rate_limiter = AsyncMock()
    rate_limiter.evaluate.return_value = (decision, SimpleNamespace(name="blocked"))

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(request, response, rate_limiter)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Rate limiter unavailable in fail-closed mode."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enforce_rate_limit_raises_rate_limit_exceeded_for_local_fallback_block() -> None:
    request = build_request()
    response = Response()
    decision = RateLimitDecision(
        allowed=False,
        limit=2,
        remaining=0,
        reset_at_epoch_seconds=100,
        retry_after_seconds=5,
        degraded=True,
        local_fallback=True,
    )
    rate_limiter = AsyncMock()
    rate_limiter.evaluate.return_value = (decision, SimpleNamespace(name="blocked"))

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(request, response, rate_limiter)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Rate limit exceeded."
