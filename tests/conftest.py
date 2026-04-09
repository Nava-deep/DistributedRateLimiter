from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

from alembic import command
from app.core.config import Settings, clear_settings_cache
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def to_async_postgres_url(sync_url: str) -> str:
    _, remainder = sync_url.split("://", 1)
    return f"postgresql+asyncpg://{remainder}"


@pytest.fixture(scope="session")
def postgres_container() -> PostgresContainer:
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_container() -> DockerContainer:
    container = DockerContainer("redis:7-alpine").with_exposed_ports(6379)
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def integration_urls(
    postgres_container: PostgresContainer,
    redis_container: DockerContainer,
) -> dict[str, str]:
    postgres_url = to_async_postgres_url(postgres_container.get_connection_url())
    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    return {
        "database_url": postgres_url,
        "redis_url": f"redis://{redis_host}:{redis_port}/0",
    }


@pytest.fixture(scope="session")
def run_migrations(integration_urls: dict[str, str]) -> None:
    os.environ["DATABASE_URL"] = integration_urls["database_url"]
    clear_settings_cache()
    alembic_config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")


@pytest_asyncio.fixture
async def clean_datastores(run_migrations, integration_urls: dict[str, str]):
    engine = create_async_engine(integration_urls["database_url"])
    redis_client = Redis.from_url(
        integration_urls["redis_url"],
        encoding="utf-8",
        decode_responses=True,
    )

    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE rate_limit_policies CASCADE"))
    await redis_client.flushdb()

    try:
        yield
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE rate_limit_policies CASCADE"))
        await redis_client.flushdb()
        close_method = getattr(redis_client, "aclose", None)
        if close_method is not None:
            await close_method()
        else:
            await redis_client.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def app(clean_datastores, integration_urls: dict[str, str]):
    settings = Settings(
        project_name="distributed-rate-limiter-test",
        environment="test",
        app_instance_name="test-instance",
        database_url=integration_urls["database_url"],
        redis_url=integration_urls["redis_url"],
        admin_token="integration-admin-token",
        strict_startup_checks=True,
        enable_policy_pubsub=True,
        log_level="INFO",
    )
    yield create_app(settings)


@pytest_asyncio.fixture
async def client(app):
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "integration-admin-token"}
