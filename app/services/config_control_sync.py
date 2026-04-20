from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import log_event
from app.schemas.policy import PolicyCreate, PolicyRead
from app.services.policy_service import PolicyService


class ConfigControlSyncError(Exception):
    pass


class ConfigControlSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.logger = logger

    def is_configured(self) -> bool:
        return bool(self.settings.config_control_base_url)

    async def sync_policy(
        self,
        *,
        policy_service: PolicyService,
        config_name: str | None = None,
        environment: str | None = None,
        target: str | None = None,
    ) -> tuple[PolicyRead, str, dict[str, Any]]:
        if not self.is_configured():
            raise ConfigControlSyncError("ConfigControl integration is not configured.")

        resolved_config_name = config_name or self.settings.config_control_policy_name
        resolved_environment = environment or self.settings.config_control_environment
        resolved_target = target or self.settings.config_control_target
        payload = await self._fetch_config(
            config_name=resolved_config_name,
            environment=resolved_environment,
            target=resolved_target,
        )

        raw_policy = payload.get("value")
        if not isinstance(raw_policy, dict):
            raise ConfigControlSyncError("ConfigControl returned a non-object policy payload.")

        try:
            policy_payload = PolicyCreate.model_validate(raw_policy)
        except Exception as exc:
            raise ConfigControlSyncError(f"ConfigControl policy payload is invalid: {exc}") from exc

        policy, action = await policy_service.upsert_policy_by_name(policy_payload)
        log_event(
            self.logger,
            logging.INFO,
            "config_control_policy_synced",
            config_name=resolved_config_name,
            environment=resolved_environment,
            target=resolved_target,
            action=action,
            policy_name=policy.name,
            config_version=payload.get("version"),
        )
        return policy, action, payload

    async def _fetch_config(
        self,
        *,
        config_name: str,
        environment: str,
        target: str,
    ) -> dict[str, Any]:
        headers = {
            "X-User-Id": self.settings.config_control_user_id,
            "X-Role": self.settings.config_control_role,
        }
        params = {
            "version": "resolved",
            "environment": environment,
            "target": target,
            "client_id": self.settings.config_control_client_id,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.config_control_base_url.rstrip("/"),
                timeout=self.settings.request_timeout_seconds,
                headers=headers,
            ) as client:
                response = await client.get(f"/configs/{config_name}", params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise ConfigControlSyncError(
                f"Unable to fetch config '{config_name}' from ConfigControl: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ConfigControlSyncError("ConfigControl returned an invalid response body.")
        return payload
