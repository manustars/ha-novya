"""Expose Novya songs as a Home Assistant media source.

This lets you browse Novya from the media browser and play any track on any
existing media player (Sonos, Cast, VLC, etc). The streaming endpoint is
public, so playback works on any device once a URL is resolved.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from . import NovyaConfigEntry
from .api import NovyaApiClient, NovyaApiError
from .const import DOMAIN

MIME_TYPE = "audio/mpeg"


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Set up the Novya media source."""
    return NovyaMediaSource(hass)


def _song_field(song: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if song.get(key) not in (None, ""):
            return song[key]
    return None


def _song_title(song: dict[str, Any]) -> str:
    return _song_field(song, "title", "name", "prompt") or "Untitled"


def _song_artist(song: dict[str, Any]) -> str | None:
    return _song_field(song, "artist", "author", "displayName", "genre")


def _genre_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return _song_field(item, "genre", "name", "tag", "value")
    return None


class NovyaMediaSource(MediaSource):
    """Provide Novya songs as browsable, playable media."""

    name = "Novya"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    # --- helpers ----------------------------------------------------------

    def _entries(self) -> list[NovyaConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]

    def _api(self, entry_id: str) -> NovyaApiClient:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise Unresolvable("Novya account is not available")
        return entry.runtime_data.api

    # --- resolve ----------------------------------------------------------

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a song identifier to a playable stream URL."""
        parts = item.identifier.split("/")
        if len(parts) != 3 or parts[1] != "song":
            raise Unresolvable(f"Unknown Novya item: {item.identifier}")
        entry_id, _, song_id = parts
        api = self._api(entry_id)
        return PlayMedia(api.stream_url(song_id), MIME_TYPE)

    # --- browse -----------------------------------------------------------

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse the Novya media tree."""
        identifier = item.identifier or ""

        if not identifier:
            entries = self._entries()
            if len(entries) == 1:
                return self._entry_root(entries[0])
            return self._accounts_root(entries)

        parts = identifier.split("/")
        entry_id = parts[0]

        # account root
        if len(parts) == 1:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                raise Unresolvable("Unknown account")
            return self._entry_root(entry)

        section = parts[1]
        api = self._api(entry_id)

        if section == "songs":
            try:
                songs = await api.async_list_songs(limit=50)
            except NovyaApiError as err:
                raise Unresolvable(str(err)) from err
            return self._songs_listing(
                entry_id, "songs", "Recent songs", api, songs
            )

        if section == "genres":
            try:
                genres = await api.async_get_popular_genres()
            except NovyaApiError as err:
                raise Unresolvable(str(err)) from err
            return self._genres_listing(entry_id, "genres", "By genre", genres)

        if section == "favgenres":
            try:
                prefs = await api.async_get_preferences()
            except NovyaApiError as err:
                raise Unresolvable(str(err)) from err
            fav = prefs.get("favoriteGenres") or []
            return self._genres_listing(
                entry_id, "favgenres", "Favorite genres", fav
            )

        if section == "library":
            try:
                _type, songs = await api.async_get_library_best_effort(
                    ["all", "generated", "owned", "public", "liked"]
                )
            except NovyaApiError as err:
                raise Unresolvable(str(err)) from err
            return self._songs_listing(
                entry_id, "library", "Your library", api, songs
            )

        if section == "genre" and len(parts) == 3:
            genre = unquote(parts[2])
            try:
                songs = await api.async_list_songs(genre=genre, limit=50)
            except NovyaApiError as err:
                raise Unresolvable(str(err)) from err
            return self._songs_listing(
                entry_id, f"genre/{quote(genre, safe='')}", genre, api, songs
            )

        raise Unresolvable(f"Unknown Novya path: {identifier}")

    # --- tree builders ----------------------------------------------------

    def _accounts_root(
        self, entries: list[NovyaConfigEntry]
    ) -> BrowseMediaSource:
        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=entry.entry_id,
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                title=entry.title,
                can_play=False,
                can_expand=True,
            )
            for entry in entries
        ]
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier="",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title="Novya",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=children,
        )

    def _entry_root(self, entry: NovyaConfigEntry) -> BrowseMediaSource:
        eid = entry.entry_id
        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{eid}/songs",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                title="Recent songs",
                can_play=False,
                can_expand=True,
            ),
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{eid}/genres",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                title="By genre",
                can_play=False,
                can_expand=True,
            ),
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{eid}/favgenres",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                title="Favorite genres",
                can_play=False,
                can_expand=True,
            ),
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{eid}/library",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                title="Your library",
                can_play=False,
                can_expand=True,
            ),
        ]
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=eid,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title=entry.title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=children,
        )

    def _genres_listing(
        self, entry_id: str, suffix: str, title: str, genres: list[Any]
    ) -> BrowseMediaSource:
        children = []
        seen: set[str] = set()
        for raw in genres:
            name = _genre_name(raw)
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"{entry_id}/genre/{quote(name, safe='')}",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    title=name,
                    can_play=False,
                    can_expand=True,
                )
            )
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{entry_id}/{suffix}",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title=title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=children,
        )

    def _songs_listing(
        self,
        entry_id: str,
        identifier_suffix: str,
        title: str,
        api: NovyaApiClient,
        songs: list[dict[str, Any]],
    ) -> BrowseMediaSource:
        children = []
        for song in songs:
            song_id = _song_field(song, "id", "songId", "_id")
            if not song_id:
                continue
            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"{entry_id}/song/{song_id}",
                    media_class=MediaClass.MUSIC,
                    media_content_type=MIME_TYPE,
                    title=_song_title(song),
                    can_play=True,
                    can_expand=False,
                    thumbnail=api.cover_url(song_id),
                )
            )
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{entry_id}/{identifier_suffix}",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title=title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.MUSIC,
            children=children,
        )
