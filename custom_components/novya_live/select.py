"""Select entities to steer the InfinityPlay radio (genre, mood)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NovyaConfigEntry
from .api import NovyaApiError
from .const import DOMAIN, INFINITYPLAY_MOODS

_LOGGER = logging.getLogger(__name__)


def _genre_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        # GET /api/genres returns {"displayName": ..., "slug": ..., ...};
        # other shapes are covered defensively since the response isn't
        # documented in the spec.
        for key in ("displayName", "genre", "name", "slug", "tag", "value"):
            if item.get(key):
                return item[key]
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NovyaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the InfinityPlay genre/mood selectors."""
    api = entry.runtime_data.api
    genres: list[str] = []
    try:
        raw = await api.async_get_all_genres()
    except NovyaApiError as err:
        _LOGGER.debug("GET /api/genres failed: %s", err)
        raw = []
    if not raw:
        try:
            raw = await api.async_get_popular_genres()
        except NovyaApiError as err:
            _LOGGER.debug("GET /api/songs/popular-genres failed: %s", err)
            raw = []
    seen: set[str] = set()
    for item in raw:
        name = _genre_name(item)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            genres.append(name)

    if not genres:
        _LOGGER.warning(
            "Could not extract any genre names from the Novya API; raw response was: %s",
            raw,
        )

    # Make sure a genre already seeded from the (legacy) options is always a
    # valid choice, even if it's missing from the fetched catalogue.
    seeded = entry.runtime_data.vibe.genre
    if seeded and seeded.lower() not in seen:
        genres.insert(0, seeded)

    async_add_entities([NovyaGenreSelect(entry, genres), NovyaMoodSelect(entry)])


class _NovyaVibeSelect(SelectEntity):
    """Common base: writes to the shared vibe and steers a live session."""

    _attr_has_entity_name = True

    def __init__(self, entry: NovyaConfigEntry) -> None:
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }

    async def _async_apply(self, field: str, value: str, session_payload: dict) -> None:
        """Store the new value and, if a session is running, steer it live."""
        setattr(self._entry.runtime_data.vibe, field, value)
        self.async_write_ha_state()
        if self._entry.runtime_data.vibe.session_active:
            try:
                await self._entry.runtime_data.api.async_update_session(session_payload)
            except NovyaApiError as err:
                _LOGGER.debug("Could not steer live session: %s", err)


class NovyaGenreSelect(_NovyaVibeSelect):
    """Pick the genre InfinityPlay uses."""

    _attr_name = "InfinityPlay genre"
    _attr_icon = "mdi:guitar-acoustic"

    def __init__(self, entry: NovyaConfigEntry, genres: list[str]) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_infinityplay_genre"
        self._attr_options = genres

    @property
    def current_option(self) -> str | None:
        return self._entry.runtime_data.vibe.genre

    async def async_select_option(self, option: str) -> None:
        await self._async_apply("genre", option, {"genres": [option]})


class NovyaMoodSelect(_NovyaVibeSelect):
    """Pick the mood InfinityPlay uses."""

    _attr_name = "InfinityPlay mood"
    _attr_icon = "mdi:emoticon-outline"

    def __init__(self, entry: NovyaConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_infinityplay_mood"
        # Make sure a mood already seeded from the (legacy) options is always
        # a valid choice, even if it's missing from the curated list.
        seeded = entry.runtime_data.vibe.mood
        options = list(INFINITYPLAY_MOODS)
        if seeded and seeded.lower() not in (m.lower() for m in options):
            options.insert(0, seeded)
        self._attr_options = options

    @property
    def current_option(self) -> str | None:
        return self._entry.runtime_data.vibe.mood

    async def async_select_option(self, option: str) -> None:
        await self._async_apply("mood", option, {"mood": option})
