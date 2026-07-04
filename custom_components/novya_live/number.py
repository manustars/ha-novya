"""Number entity to steer InfinityPlay's exploration level."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NovyaConfigEntry
from .api import NovyaApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NovyaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the InfinityPlay exploration level number entity."""
    async_add_entities([NovyaExplorationLevelNumber(entry)])


class NovyaExplorationLevelNumber(NumberEntity):
    """How far InfinityPlay strays from your usual taste (0=focused, 5=explore)."""

    _attr_has_entity_name = True
    _attr_name = "InfinityPlay exploration level"
    _attr_icon = "mdi:compass-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 5
    _attr_native_step = 0.5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: NovyaConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_infinityplay_exploration_level"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }

    @property
    def native_value(self) -> float:
        return self._entry.runtime_data.vibe.exploration_level

    async def async_set_native_value(self, value: float) -> None:
        """Store the new value and, if a session is running, steer it live."""
        vibe = self._entry.runtime_data.vibe
        vibe.exploration_level = value
        self.async_write_ha_state()
        if vibe.session_active:
            try:
                await self._entry.runtime_data.api.async_update_session(
                    {"explorationLevel": value}
                )
            except NovyaApiError as err:
                _LOGGER.debug("Could not steer live session: %s", err)
