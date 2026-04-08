from __future__ import annotations

import pytest


def sample_policy_payload(**overrides):
    payload = {
        "name": "protected-default",
        "description": "Default protected policy",
        "algorithm": "token_bucket",
        "rate": 10,
        "window_seconds": 60,
        "burst_capacity": 15,
        "route": "/demo/protected",
        "failure_mode": "fail_closed",
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_policy(client, admin_headers) -> None:
    response = await client.post("/admin/policies", json=sample_policy_payload(), headers=admin_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "protected-default"
    assert body["version"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_policies_filters_inactive_records(client, admin_headers) -> None:
    await client.post("/admin/policies", json=sample_policy_payload(name="active-one"), headers=admin_headers)
    await client.post(
        "/admin/policies",
        json=sample_policy_payload(name="inactive-one", active=False),
        headers=admin_headers,
    )

    response = await client.get("/admin/policies?active_only=true", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["name"] == "active-one"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_policy_by_id(client, admin_headers) -> None:
    create_response = await client.post(
        "/admin/policies",
        json=sample_policy_payload(name="fetch-me"),
        headers=admin_headers,
    )
    policy_id = create_response.json()["id"]

    response = await client.get(f"/admin/policies/{policy_id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["name"] == "fetch-me"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_policy_increments_version(client, admin_headers) -> None:
    create_response = await client.post(
        "/admin/policies",
        json=sample_policy_payload(name="update-me"),
        headers=admin_headers,
    )
    policy_id = create_response.json()["id"]

    response = await client.put(
        f"/admin/policies/{policy_id}",
        json={"rate": 25, "burst_capacity": 30},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rate"] == 25
    assert body["version"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_policy_removes_it(client, admin_headers) -> None:
    create_response = await client.post(
        "/admin/policies",
        json=sample_policy_payload(name="delete-me"),
        headers=admin_headers,
    )
    policy_id = create_response.json()["id"]

    delete_response = await client.delete(f"/admin/policies/{policy_id}", headers=admin_headers)
    get_response = await client.get(f"/admin/policies/{policy_id}", headers=admin_headers)

    assert delete_response.status_code == 204
    assert get_response.status_code == 404

