from __future__ import annotations

import pytest

from app.core.config import Settings
from app.redis.client import create_pubsub_redis_client, create_redis_client


@pytest.mark.unit
def test_request_redis_client_uses_short_socket_timeout() -> None:
    settings = Settings(redis_url="redis://localhost:6379/0")

    client = create_redis_client(settings)

    assert client.connection_pool.connection_kwargs["socket_timeout"] == (
        settings.redis_socket_timeout_seconds
    )


@pytest.mark.unit
def test_pubsub_redis_client_disables_read_timeout() -> None:
    settings = Settings(redis_url="redis://localhost:6379/0")

    pubsub_client = create_pubsub_redis_client(settings)

    assert pubsub_client.connection_pool.connection_kwargs["socket_timeout"] is None
    assert pubsub_client.connection_pool.connection_kwargs["socket_connect_timeout"] == (
        settings.redis_socket_timeout_seconds
    )
