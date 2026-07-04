"""Sensor platform for Novya."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NovyaConfigEntry
from .const import DOMAIN
from .coordinator import NovyaCoordinator


def _dig(data: dict[str, Any] | None, *keys: str) -> Any:
    """Return the first present (non-None) value among the given keys."""
    if not isinstance(data, dict):
        return None
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _usage_used(data: dict[str, Any]) -> Any:
    usage = data.get("usage") or {}
    return _dig(usage, "used", "generationsUsed", "generations", "count", "usedToday")


def _usage_limit(data: dict[str, Any]) -> Any:
    usage = data.get("usage") or {}
    val = _dig(usage, "limit", "dailyLimit", "dailyGenerationLimit", "quota", "max")
    if val is not None:
        return val
    plan = (data.get("subscription") or {}).get("plan") or {}
    return plan.get("dailyGenerationLimit")


def _usage_remaining(data: dict[str, Any]) -> Any:
    usage = data.get("usage") or {}
    val = _dig(usage, "remaining", "left", "remainingToday", "creditsRemaining")
    if val is not None:
        return val
    used = _usage_used(data)
    limit = _usage_limit(data)
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)):
        return max(limit - used, 0)
    return None


@dataclass(frozen=True, kw_only=True)
class NovyaSensorDescription(SensorEntityDescription):
    """Describe a Novya sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[NovyaSensorDescription, ...] = (
    NovyaSensorDescription(
        key="generations_used_today",
        translation_key="generations_used_today",
        icon="mdi:music-note-plus",
        state_class="measurement",
        value_fn=_usage_used,
        attr_fn=lambda d: {"raw_usage": d.get("usage")},
    ),
    NovyaSensorDescription(
        key="generations_remaining_today",
        translation_key="generations_remaining_today",
        icon="mdi:music-note",
        state_class="measurement",
        value_fn=_usage_remaining,
    ),
    NovyaSensorDescription(
        key="daily_generation_limit",
        translation_key="daily_generation_limit",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_usage_limit,
    ),
    NovyaSensorDescription(
        key="subscription_status",
        translation_key="subscription_status",
        icon="mdi:card-account-details",
        value_fn=lambda d: (d.get("subscription") or {}).get("status"),
        attr_fn=lambda d: {
            "plan": ((d.get("subscription") or {}).get("plan") or {}).get("name"),
            "plan_slug": ((d.get("subscription") or {}).get("plan") or {}).get("slug"),
            "started_at": (d.get("subscription") or {}).get("startedAt"),
            "current_period_end": (d.get("subscription") or {}).get("currentPeriodEnd"),
        },
    ),
    NovyaSensorDescription(
        key="latest_generation_status",
        translation_key="latest_generation_status",
        icon="mdi:robot",
        value_fn=lambda d: (d.get("latest_generation") or {}).get("status"),
        attr_fn=lambda d: {
            "prompt": (d.get("latest_generation") or {}).get("prompt"),
            "result_song_id": (d.get("latest_generation") or {}).get("resultSongId"),
            "updated_at": (d.get("latest_generation") or {}).get("updatedAt"),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NovyaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Novya sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        NovyaSensor(coordinator, entry, description) for description in SENSORS
    )


class NovyaSensor(CoordinatorEntity[NovyaCoordinator], SensorEntity):
    """A Novya account/status sensor."""

    entity_description: NovyaSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NovyaCoordinator,
        entry: NovyaConfigEntry,
        description: NovyaSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Novya.live",
            "model": "AI Music Platform",
            "configuration_url": coordinator.api.base_url,
        }

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data)
