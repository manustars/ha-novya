"""Media player platform for Novya: the backend-managed 'Novya Radio'.

The entity does not output audio itself (no HA media_player can). Instead it
drives a *target* media player chosen in the integration options, turning the
Novya backend listening session into a continuous, auto-advancing radio with
now-playing metadata and artwork.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import NovyaConfigEntry
from .api import NovyaApiClient, NovyaApiError, NovyaAuthError
from .const import (
    CONF_EXPLORATION,
    CONF_GENRES,
    CONF_MOOD,
    CONF_TARGET,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Target states that mean the current track has finished.
_ENDED_STATES = {MediaPlayerState.IDLE, MediaPlayerState.OFF, "standby"}
_ACTIVE_STATES = {
    MediaPlayerState.PLAYING,
    MediaPlayerState.PAUSED,
    MediaPlayerState.BUFFERING,
}
# Max consecutive "still generating" tracks to skip before giving up.
_MAX_GENERATING_SKIPS = 6


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NovyaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Novya Radio media player."""
    async_add_entities([NovyaRadioPlayer(entry)])


class NovyaRadioPlayer(MediaPlayerEntity):
    """A continuous Novya radio that controls a target media player."""

    _attr_has_entity_name = True
    _attr_name = "Playlist"
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, entry: NovyaConfigEntry) -> None:
        """Initialise the radio player."""
        self._entry = entry
        self._api: NovyaApiClient = entry.runtime_data.api
        self._attr_unique_id = f"{entry.entry_id}_playlist"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Novya.live",
            "model": "AI Music Platform",
            "configuration_url": self._api.base_url,
        }

        self._active = False
        self._advancing = False
        self._queue: list[dict[str, Any]] = []
        self._current_song: dict[str, Any] | None = None
        self._current_song_id: str | None = None
        self._current_title: str | None = None
        self._current_artist: str | None = None
        self._current_image: str | None = None
        self._unsub = None

    # --- target helpers ---------------------------------------------------

    @property
    def _target(self) -> str | None:
        return self._entry.options.get(CONF_TARGET)

    def _target_state(self):
        target = self._target
        return self.hass.states.get(target) if target else None

    async def _target_call(self, service: str, data: dict[str, Any] | None = None) -> None:
        if not self._target:
            raise HomeAssistantError(
                "No target media player set. Configure one in the Novya options."
            )
        await self.hass.services.async_call(
            "media_player",
            service,
            {ATTR_ENTITY_ID: self._target, **(data or {})},
            blocking=True,
        )

    # --- HA properties ----------------------------------------------------

    @property
    def available(self) -> bool:
        """Available only when a valid target player exists."""
        return self._target_state() is not None

    @property
    def state(self) -> MediaPlayerState | None:
        """Mirror the target's playback state."""
        st = self._target_state()
        if st is None:
            return None
        if st.state in _ACTIVE_STATES:
            return MediaPlayerState(st.state)
        return MediaPlayerState.IDLE if self._active else MediaPlayerState.OFF

    @property
    def media_title(self) -> str | None:
        return self._current_title

    @property
    def media_artist(self) -> str | None:
        return self._current_artist

    @property
    def media_image_url(self) -> str | None:
        return self._current_image

    @property
    def media_content_id(self) -> str | None:
        if self._current_song_id:
            return self._api.stream_url(self._current_song_id)
        return None

    @property
    def volume_level(self) -> float | None:
        st = self._target_state()
        return st.attributes.get("volume_level") if st else None

    @property
    def is_volume_muted(self) -> bool | None:
        st = self._target_state()
        return st.attributes.get("is_volume_muted") if st else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"target": self._target, "queued": len(self._queue)}

    # --- lifecycle --------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Subscribe to the target player's state changes for auto-advance."""
        await super().async_added_to_hass()
        if self._target:
            self._unsub = async_track_state_change_event(
                self.hass, [self._target], self._handle_target_event
            )

    @callback
    def _handle_target_event(self, event: Event) -> None:
        """Advance to the next track when the target finishes playing."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is not None:
            self.async_write_ha_state()
        if not self._active or self._advancing:
            return
        if new_state is None or old_state is None:
            return
        if new_state.state in _ENDED_STATES and old_state.state in _ACTIVE_STATES:
            self.hass.async_create_task(self._play_next())

    # --- playback controls ------------------------------------------------

    async def async_media_play(self) -> None:
        """Start the radio, or resume the target if already active."""
        if self._active and self._current_song_id is not None:
            await self._target_call("media_play")
        else:
            await self._start_radio()

    async def async_media_pause(self) -> None:
        """Pause playback on the target."""
        await self._target_call("media_pause")

    async def async_media_stop(self) -> None:
        """Stop the radio."""
        self._active = False
        self._queue = []
        self._clear_current()
        await self._target_call("media_stop")
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Skip to the next track."""
        if not self._active:
            await self._start_radio()
        else:
            await self._report_progress(skipped=True)
            await self._play_next()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._target_call("volume_set", {"volume_level": volume})

    async def async_mute_volume(self, mute: bool) -> None:
        await self._target_call("volume_mute", {"is_volume_muted": mute})

    async def async_volume_up(self) -> None:
        await self._target_call("volume_up")

    async def async_volume_down(self) -> None:
        await self._target_call("volume_down")

    # --- browsing & direct play ------------------------------------------

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse Novya (and other media sources) from the radio player."""
        if media_content_id is None:
            media_content_id = f"media-source://{DOMAIN}"
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type
            in (MediaType.MUSIC, "audio/mpeg")
            or item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a single resolved track on the target (stops the radio loop)."""
        if media_source.is_media_source_id(media_id):
            resolved = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            media_id = async_process_play_media_url(self.hass, resolved.url)

        self._active = False
        self._queue = []
        self._clear_current()
        await self._target_call(
            "play_media",
            {"media_content_id": media_id, "media_content_type": MediaType.MUSIC},
        )
        self.async_write_ha_state()

    # --- radio engine -----------------------------------------------------

    async def _start_radio(self) -> None:
        """Start a backend session and begin playback."""
        if not self._target:
            raise HomeAssistantError(
                "No target media player set. Configure one in the Novya options."
            )
        payload = {
            "genres": self._entry.options.get(CONF_GENRES),
            "mood": self._entry.options.get(CONF_MOOD),
            "explorationLevel": self._entry.options.get(CONF_EXPLORATION),
        }
        # Fall back to the user's saved preferences when no option is set.
        if not payload["genres"] or not payload["mood"]:
            try:
                prefs = await self._api.async_get_preferences()
            except (NovyaApiError, NovyaAuthError):
                prefs = {}
            if not payload["genres"] and prefs.get("favoriteGenres"):
                payload["genres"] = prefs["favoriteGenres"]
            if not payload["mood"] and prefs.get("moodPreferences"):
                moods = prefs["moodPreferences"]
                payload["mood"] = moods[0] if moods else None
        try:
            session = await self._api.async_start_session(payload)
        except (NovyaApiError, NovyaAuthError) as err:
            raise HomeAssistantError(f"Could not start Novya radio: {err}") from err

        self._queue = list(session.get("initialQueue") or [])
        if not self._queue and (current := session.get("currentSong")):
            self._queue = [{"type": "song", "song": current}]
        self._active = True
        await self._play_next()

    async def _play_next(self) -> None:
        """Resolve the next playable track and play it on the target."""
        if self._advancing or not self._active:
            return
        self._advancing = True
        try:
            await self._report_progress()
            track = await self._next_playable_track()
            if track is None:
                _LOGGER.warning("Novya returned no playable track; stopping radio")
                self._active = False
                return
            url, song = track
            self._set_current(song)
            await self._target_call(
                "play_media",
                {"media_content_id": url, "media_content_type": MediaType.MUSIC},
            )
        except (NovyaApiError, NovyaAuthError) as err:
            _LOGGER.error("Novya radio error: %s", err)
            self._active = False
        finally:
            self._advancing = False
            self.async_write_ha_state()

    async def _next_playable_track(self) -> tuple[str, dict[str, Any] | None] | None:
        """Return (url, song) for the next song/ad, skipping 'generating' items."""
        for _ in range(_MAX_GENERATING_SKIPS):
            track = self._queue.pop(0) if self._queue else await self._api.async_next_track()
            ttype = track.get("type")
            if ttype == "song":
                song = track.get("song") or {}
                song_id = song.get("id")
                if song_id:
                    return self._api.stream_url(song_id), song
            elif ttype == "ad":
                ad = track.get("ad") or {}
                url = ad.get("streamUrl")
                if url:
                    full = url if url.startswith("http") else f"{self._api.base_url}{url}"
                    return full, {"title": ad.get("title", "Advertisement")}
            # 'generating' or malformed -> wait briefly and try the next one
            await asyncio.sleep(2)
        return None

    async def _report_progress(self, skipped: bool = False) -> None:
        """Best-effort progress report for the previous song."""
        if not self._current_song_id:
            return
        st = self._target_state()
        elapsed = 0
        if st is not None:
            elapsed = int(
                st.attributes.get("media_position")
                or st.attributes.get("media_duration")
                or 0
            )
        try:
            await self._api.async_report_progress(
                {
                    "songId": self._current_song_id,
                    "elapsedSeconds": elapsed,
                }
            )
            if skipped:
                await self._api.async_rate_song(self._current_song_id, "skip")
        except (NovyaApiError, NovyaAuthError) as err:
            _LOGGER.debug("Progress report failed: %s", err)

    # --- metadata bookkeeping --------------------------------------------

    def _set_current(self, song: dict[str, Any] | None) -> None:
        self._current_song = song
        if not song:
            self._clear_current()
            return
        self._current_song_id = song.get("id")
        self._current_title = (
            song.get("title") or song.get("name") or song.get("prompt") or "Novya"
        )
        self._current_artist = (
            song.get("artist") or song.get("displayName") or song.get("genre")
        )
        self._current_image = (
            self._api.cover_url(self._current_song_id)
            if self._current_song_id
            else None
        )

    def _clear_current(self) -> None:
        self._current_song = None
        self._current_song_id = None
        self._current_title = None
        self._current_artist = None
        self._current_image = None
