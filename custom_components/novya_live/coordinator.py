"""Data update coordinator for Novya."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NovyaApiClient, NovyaApiError, NovyaAuthError
from .const import DOMAIN, UPDATE_INTERVAL

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

        return {
            "profile": profile,
            "usage": usage,
            "subscription": subscription,
            "latest_generation": generations[0] if generations else None,
        }
