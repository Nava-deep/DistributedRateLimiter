from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.security import require_admin_token, require_service_token


def build_request(
    provided_token: str | None,
    *,
    header_name: str = "X-Admin-Token",
    expected_admin_token: str = "secret-token",
    expected_service_token: str = "service-secret",
):
    headers = {}
    if provided_token is not None:
        headers[header_name] = provided_token
    return SimpleNamespace(
        headers=headers,
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    admin_token=expected_admin_token,
                    service_token=expected_service_token,
                )
            )
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_admin_token_accepts_matching_token() -> None:
    request = build_request("secret-token")

    assert await require_admin_token(request) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_admin_token_rejects_missing_token() -> None:
    request = build_request(None)

    with pytest.raises(HTTPException) as exc_info:
        await require_admin_token(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing or invalid admin token."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_admin_token_rejects_invalid_token() -> None:
    request = build_request("wrong-token")

    with pytest.raises(HTTPException) as exc_info:
        await require_admin_token(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing or invalid admin token."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_admin_token_uses_constant_time_compare() -> None:
    request = build_request("secret-token")

    with patch("app.core.security.compare_digest", return_value=True) as compare_digest:
        await require_admin_token(request)

    compare_digest.assert_called_once_with("secret-token", "secret-token")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_admin_token_rejects_case_mismatched_token() -> None:
    request = build_request("Secret-Token")

    with pytest.raises(HTTPException) as exc_info:
        await require_admin_token(request)

    assert exc_info.value.status_code == 401


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_service_token_accepts_matching_token() -> None:
    request = build_request(
        "service-secret",
        header_name="X-Service-Token",
    )

    assert await require_service_token(request) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_service_token_rejects_invalid_token() -> None:
    request = build_request(
        "wrong-secret",
        header_name="X-Service-Token",
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_service_token(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing or invalid service token."
