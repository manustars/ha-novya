"""Data update coordinator for Novya."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NovyaApiClient, NovyaApiError, NovyaAuthError
from .const import (
    DOMAIN,
    ISSUE_RESTART_REQUIRED,
    RUNNING_VERSION,
    UPDATE_INTERVAL,
    read_manifest_version,
)

_LOGGER = logging.getLogger(__name__)


class NovyaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch account status (profile, usage, subscription, generations)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: NovyaApiClient
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest data from Novya."""
        try:
            profile = await self.api.async_get_profile()
            usage = await self.api.async_get_usage_today()
            subscription = await self.api.async_get_subscription()
            generations = await self.api.async_list_generations()
        except NovyaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NovyaApiError as err:
            raise UpdateFailed(str(err)) from err

        await self._async_check_restart_required()

        return {
            "profile": profile,
            "usage": usage,
            "subscription": subscription,
            "latest_generation": generations[0] if generations else None,
        }

    async def _async_check_restart_required(self) -> None:
        """Raise a repair issue if HACS updated the files but HA wasn't restarted.

        Python keeps the previously-imported code in memory, so a version
        mismatch between disk and RUNNING_VERSION means we're still serving
        the old code until the user restarts Home Assistant.
        """
        disk_version = await self.hass.async_add_executor_job(read_manifest_version)
        if disk_version and disk_version != RUNNING_VERSION:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_RESTART_REQUIRED,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_RESTART_REQUIRED,
                translation_placeholders={
                    "current_version": RUNNING_VERSION or "?",
                    "new_version": disk_version,
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_RESTART_REQUIRED)
