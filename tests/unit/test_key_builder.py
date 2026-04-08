from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from starlette.datastructures import Headers

from app.services.key_builder import build_rate_limit_key, build_request_identity, extract_client_ip


def build_request(
    *,
    path: str,
    route_path: str,
    headers: dict[str, str] | None = None,
    path_params: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> Request:
    scope = {
        "type": "http",
        "app": FastAPI(),
        "method": "GET",
        "path": path,
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": Headers(headers or {}).raw,
        "client": (client_host, 1234),
        "server": ("testserver", 80),
        "path_params": path_params or {},
        "route": SimpleNamespace(path=route_path),
    }
    return Request(scope)


@pytest.mark.unit
def test_extract_client_ip_prefers_forwarded_for() -> None:
    request = build_request(
        path="/demo/public",
        route_path="/demo/public",
        headers={"X-Forwarded-For": "203.0.113.10, 198.51.100.1"},
        client_host="10.0.0.5",
    )

    assert extract_client_ip(request) == "203.0.113.10"


@pytest.mark.unit
def test_build_request_identity_uses_path_user_id() -> None:
    request = build_request(
        path="/demo/user/alice",
        route_path="/demo/user/{user_id}",
        path_params={"user_id": "alice"},
        headers={"X-Tenant-Id": "tenant-a"},
    )

    identity = build_request_identity(request)

    assert identity.route == "/demo/user/{user_id}"
    assert identity.user_id == "alice"
    assert identity.tenant_id == "tenant-a"


@pytest.mark.unit
def test_build_rate_limit_key_includes_policy_version_and_selectors() -> None:
    policy = SimpleNamespace(
        id="policy-1",
        version=3,
        algorithm="token_bucket",
        route="/demo/user/{user_id}",
        user_id="alice",
        ip_address=None,
        tenant_id="tenant-a",
        api_key=None,
    )
    request = build_request(
        path="/demo/user/alice",
        route_path="/demo/user/{user_id}",
        path_params={"user_id": "alice"},
        headers={"X-Tenant-Id": "tenant-a"},
    )
    identity = build_request_identity(request)

    key = build_rate_limit_key(policy, identity)

    assert key == (
        "rl:token_bucket:policy-1:v3:route=/demo/user/{user_id}:user=alice:tenant=tenant-a"
    )


@pytest.mark.unit
def test_build_rate_limit_key_omits_unused_selectors() -> None:
    policy = SimpleNamespace(
        id="policy-2",
        version=1,
        algorithm="fixed_window",
        route=None,
        user_id=None,
        ip_address="127.0.0.1",
        tenant_id=None,
        api_key=None,
    )
    request = build_request(path="/demo/public", route_path="/demo/public")
    identity = build_request_identity(request)

    key = build_rate_limit_key(policy, identity)

    assert key == "rl:fixed_window:policy-2:v1:ip=127.0.0.1"

