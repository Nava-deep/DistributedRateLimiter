from __future__ import annotations

import pytest


def policy_payload(**overrides) -> dict[str, object]:
    payload = {
        "name": "judge-vortex-submission-limit",
        "algorithm": "token_bucket",
        "rate": 1,
        "window_seconds": 60,
        "burst_capacity": 1,
        "route": "/api/submissions/submit/",
        "failure_mode": "fail_closed",
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_internal_evaluate_returns_allow_then_block(
    client,
    admin_headers,
    service_headers,
) -> None:
    create_response = await client.post(
        "/admin/policies",
        json=policy_payload(),
        headers=admin_headers,
    )
    assert create_response.status_code == 201

    request_payload = {
        "route": "/api/submissions/submit/",
        "user_id": "student-42",
        "tenant_id": "room-7",
        "ip_address": "203.0.113.10",
    }

    first = await client.post("/internal/evaluate", json=request_payload, headers=service_headers)
    second = await client.post("/internal/evaluate", json=request_payload, headers=service_headers)

    assert first.status_code == 200
    assert first.json()["allowed"] is True
    assert first.json()["applied"] is True
    assert first.json()["policy"]["name"] == "judge-vortex-submission-limit"

    assert second.status_code == 200
    assert second.json()["allowed"] is False
    assert second.json()["applied"] is True
    assert second.json()["retry_after_seconds"] >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_internal_evaluate_requires_service_token(client) -> None:
    response = await client.post(
        "/internal/evaluate",
        json={"route": "/api/submissions/submit/"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid service token."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_endpoint_pulls_policy_from_config_control(
    app_factory,
    service_headers,
    monkeypatch,
) -> None:
    app = app_factory(
        app_instance_name="sync-test-instance",
        config_control_base_url="http://config-control.local",
    )

    async def fake_fetch_config(self, *, config_name: str, environment: str, target: str):
        assert config_name == "judge-vortex.submission-rate-limit-policy"
        assert environment == "prod"
        assert target == "judge-vortex"
        return {
            "name": config_name,
            "environment": environment,
            "target": target,
            "version": 4,
            "value": policy_payload(
                name="judge-vortex-submission-limit",
                rate=6,
                burst_capacity=8,
            ),
        }

    monkeypatch.setattr(
        "app.services.config_control_sync.ConfigControlSyncService._fetch_config",
        fake_fetch_config,
    )

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as scoped_client:
            response = await scoped_client.post(
                "/internal/sync/config-control",
                json={},
                headers=service_headers,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["config_version"] == 4
            assert body["action"] == "created"
            assert body["policy"]["rate"] == 6

            evaluation = await scoped_client.post(
                "/internal/evaluate",
                json={"route": "/api/submissions/submit/", "user_id": "student-2"},
                headers=service_headers,
            )
            assert evaluation.status_code == 200
            assert evaluation.json()["applied"] is True
