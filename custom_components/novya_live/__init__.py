"""The Novya integration (AI music generation platform)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NovyaApiClient, NovyaApiError, NovyaAuthError
from .const import (
    CONF_BASE_URL,
    CONF_EMAIL,
    CONF_PASSWORD,
    DEFAULT_BASE_URL,
    DOMAIN,
    EVENT_GENERATION_STARTED,
    PLATFORMS,
    SERVICE_GENERATE_SONG,
    SERVICE_PLAY_RADIO,
    SERVICE_RADIO_NEXT,
    SERVICE_RATE_SONG,
    SERVICE_SET_VIBE,
)
from .coordinator import NovyaCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class NovyaRuntimeData:
    """Objects kept alive for the lifetime of a config entry."""

    api: NovyaApiClient
    coordinator: NovyaCoordinator


type NovyaConfigEntry = ConfigEntry[NovyaRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: NovyaConfigEntry) -> bool:
    """Set up Novya from a config entry."""
    session = async_get_clientsession(hass)
    api = NovyaApiClient(
        session,
        entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )

    coordinator = NovyaCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = NovyaRuntimeData(api=api, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _async_register_services(hass)

    return True


async def _async_options_updated(hass: HomeAssistant, entry: NovyaConfigEntry) -> None:
    """Reload the entry when options change (e.g. radio target)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NovyaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove services once the last entry is gone.
    if unloaded and not _other_loaded_entries(hass, entry):
        for service in (
            SERVICE_GENERATE_SONG,
            SERVICE_RATE_SONG,
            SERVICE_PLAY_RADIO,
            SERVICE_RADIO_NEXT,
            SERVICE_SET_VIBE,
        ):
            hass.services.async_remove(DOMAIN, service)

    return unloaded


def _other_loaded_entries(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return True if another loaded Novya entry exists."""
    return any(
        e.entry_id != entry.entry_id and e.state is ConfigEntryState.LOADED
        for e in hass.config_entries.async_entries(DOMAIN)
    )


def _first_api(hass: HomeAssistant) -> NovyaApiClient:
    """Return the API client of the first loaded entry (services are global)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if isinstance(getattr(entry, "runtime_data", None), NovyaRuntimeData):
            return entry.runtime_data.api
    raise HomeAssistantError("No configured Novya account is available")


def _first_coordinator(hass: HomeAssistant) -> NovyaCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if isinstance(getattr(entry, "runtime_data", None), NovyaRuntimeData):
            return entry.runtime_data.coordinator
    return None


def _track_stream_url(api: NovyaApiClient, track: dict[str, Any]) -> str:
    """Resolve a playable URL from a PlaylistTrackDto."""
    ttype = track.get("type")
    if ttype == "song":
        song = track.get("song") or {}
        song_id = song.get("id")
        if not song_id:
            raise HomeAssistantError("Track has no song id")
        return api.stream_url(song_id)
    if ttype == "ad":
        ad = track.get("ad") or {}
        url = ad.get("streamUrl")
        if not url:
            raise HomeAssistantError("Ad has no stream URL")
        return url if url.startswith("http") else f"{api.base_url}{url}"
    raise HomeAssistantError(
        "Next track is still being generated; try again in a moment"
    )


def _async_register_services(hass: HomeAssistant) -> None:
    """Register Novya services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_GENERATE_SONG):
        return

    async def _play_on_target(target: str, url: str) -> None:
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                ATTR_ENTITY_ID: target,
                "media_content_id": url,
                "media_content_type": "music",
            },
            blocking=True,
        )

    async def handle_generate(call: ServiceCall) -> ServiceResponse:
        api = _first_api(hass)
        payload = {
            "prompt": call.data["prompt"],
            "lyrics": call.data.get("lyrics"),
            "genre": call.data.get("genre"),
            "mood": call.data.get("mood"),
            "duration": call.data.get("duration"),
            "bpm": call.data.get("bpm"),
            "vocalLanguage": call.data.get("vocal_language"),
        }
        try:
            task = await api.async_create_generation(payload)
        except (NovyaApiError, NovyaAuthError) as err:
            raise HomeAssistantError(f"Generation failed: {err}") from err

        task_id = task.get("jobId") if isinstance(task, dict) else None
        hass.bus.async_fire(EVENT_GENERATION_STARTED, {"task_id": task_id, "task": task})
        if (coordinator := _first_coordinator(hass)) is not None:
            await coordinator.async_request_refresh()
        return task if isinstance(task, dict) else {"result": task}

    async def handle_rate(call: ServiceCall) -> None:
        api = _first_api(hass)
        try:
            await api.async_rate_song(call.data["song_id"], call.data["rating"])
        except (NovyaApiError, NovyaAuthError) as err:
            raise HomeAssistantError(f"Rating failed: {err}") from err

    async def handle_play_radio(call: ServiceCall) -> None:
        api = _first_api(hass)
        target = call.data[ATTR_ENTITY_ID]
        payload = {
            "prompt": call.data.get("prompt"),
            "genres": call.data.get("genres"),
            "mood": call.data.get("mood"),
            "languages": call.data.get("languages"),
            "explorationLevel": call.data.get("exploration_level"),
        }
        try:
            session = await api.async_start_session(payload)
        except (NovyaApiError, NovyaAuthError) as err:
            raise HomeAssistantError(f"Could not start radio: {err}") from err

        url: str | None = None
        for track in session.get("initialQueue") or []:
            try:
                url = _track_stream_url(api, track)
                break
            except HomeAssistantError:
                continue
        if url is None and (current := session.get("currentSong")):
            if current.get("id"):
                url = api.stream_url(current["id"])
        if url is None:
            raise HomeAssistantError("Radio session returned no playable track yet")

        await _play_on_target(target, url)

    async def handle_radio_next(call: ServiceCall) -> None:
        api = _first_api(hass)
        target = call.data[ATTR_ENTITY_ID]
        try:
            track = await api.async_next_track()
        except (NovyaApiError, NovyaAuthError) as err:
            raise HomeAssistantError(f"Could not get next track: {err}") from err
        url = _track_stream_url(api, track)
        await _play_on_target(target, url)

    async def handle_set_vibe(call: ServiceCall) -> None:
        api = _first_api(hass)
        payload = {
            "genres": call.data.get("genres"),
            "mood": call.data.get("mood"),
            "prompt": call.data.get("prompt"),
            "explorationLevel": call.data.get("exploration_level"),
        }
        if not any(v is not None for v in payload.values()):
            raise HomeAssistantError("Provide at least one of: genres, mood, prompt")
        try:
            await api.async_update_session(payload)
        except (NovyaApiError, NovyaAuthError) as err:
            raise HomeAssistantError(f"Could not update the playlist vibe: {err}") from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_SONG,
        handle_generate,
        schema=vol.Schema(
            {
                vol.Required("prompt"): cv.string,
                vol.Optional("lyrics"): cv.string,
                vol.Optional("genre"): cv.string,
                vol.Optional("mood"): cv.string,
                vol.Optional("duration"): vol.Coerce(int),
                vol.Optional("bpm"): vol.Coerce(int),
                vol.Optional("vocal_language"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RATE_SONG,
        handle_rate,
        schema=vol.Schema(
            {
                vol.Required("song_id"): cv.string,
                vol.Required("rating"): vol.In(["like", "dislike", "skip"]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_RADIO,
        handle_play_radio,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): cv.entity_id,
                vol.Optional("prompt"): cv.string,
                vol.Optional("genres"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("mood"): cv.string,
                vol.Optional("languages"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("exploration_level"): vol.Coerce(float),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RADIO_NEXT,
        handle_radio_next,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_VIBE,
        handle_set_vibe,
        schema=vol.Schema(
            {
                vol.Optional("genres"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("mood"): cv.string,
                vol.Optional("prompt"): cv.string,
                vol.Optional("exploration_level"): vol.Coerce(float),
            }
        ),
    )
