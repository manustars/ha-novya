"""Lightweight async client for the Novya API."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    PATH_COVER,
    PATH_GENERATIONS,
    PATH_LIBRARY,
    PATH_LIBRARY_GENRES,
    PATH_LOGIN,
    PATH_NEXT,
    PATH_POPULAR_GENRES,
    PATH_PREFERENCES,
    PATH_PROFILE,
    PATH_PROGRESS,
    PATH_RANDOM,
    PATH_RATE,
    PATH_SESSION,
    PATH_SONGS,
    PATH_STREAM,
    PATH_SUBSCRIPTION,
    PATH_USAGE_TODAY,
)

_LOGGER = logging.getLogger(__name__)


class NovyaApiError(Exception):
    """Generic Novya API error."""


class NovyaAuthError(NovyaApiError):
    """Authentication failed (bad credentials or expired token)."""


class NovyaApiClient:
    """Minimal async wrapper around the Novya REST API.

    The client keeps the JWT access token in memory and transparently
    re-authenticates with the stored credentials whenever it receives a 401.
    """

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        email: str,
        password: str,
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._token: str | None = None
        self.user: dict[str, Any] | None = None

    @property
    def base_url(self) -> str:
        """Return the configured base URL (no trailing slash)."""
        return self._base_url

    def stream_url(self, song_id: str) -> str:
        """Return the public streaming URL for a song (no auth required)."""
        return f"{self._base_url}{PATH_STREAM.format(song_id=song_id)}"

    def cover_url(self, song_id: str) -> str:
        """Return the public cover image URL for a song (no auth required)."""
        return f"{self._base_url}{PATH_COVER.format(song_id=song_id)}"

    async def async_login(self) -> dict[str, Any]:
        """Authenticate and cache the access token."""
        url = f"{self._base_url}{PATH_LOGIN}"
        try:
            async with self._session.post(
                url, json={"email": self._email, "password": self._password}
            ) as resp:
                body = await resp.text()
                if resp.status in (400, 401, 403):
                    raise NovyaAuthError(f"Login rejected ({resp.status}): {body[:200]}")
                if resp.status >= 400:
                    raise NovyaApiError(f"Login error ({resp.status}): {body[:200]}")
                data = await resp.json()
        except ClientError as err:
            raise NovyaApiError(f"Cannot reach Novya: {err}") from err

        self._token = data.get("accessToken")
        self.user = data.get("user")
        if not self._token:
            raise NovyaAuthError("Login response did not contain an accessToken")
        return data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        _retry: bool = True,
    ) -> Any:
        """Perform an authenticated request, re-logging in on 401 once."""
        url = f"{self._base_url}{path}"
        headers: dict[str, str] = {}

        if auth:
            if not self._token:
                await self.async_login()
            headers["Authorization"] = f"Bearer {self._token}"

        # aiohttp wants query values as strings.
        str_params = (
            {k: str(v) for k, v in params.items() if v is not None} if params else None
        )

        try:
            async with self._session.request(
                method, url, json=json, params=str_params, headers=headers
            ) as resp:
                if resp.status == 401 and auth and _retry:
                    _LOGGER.debug("Token expired, re-authenticating")
                    await self.async_login()
                    return await self._request(
                        method, path, auth=auth, json=json, params=params, _retry=False
                    )
                text = await resp.text()
                if resp.status == 401:
                    raise NovyaAuthError(f"Unauthorized: {text[:200]}")
                if resp.status >= 400:
                    raise NovyaApiError(f"{method} {path} -> {resp.status}: {text[:200]}")
                if not text:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    return await resp.json()
                return text
        except ClientError as err:
            raise NovyaApiError(f"Request to {path} failed: {err}") from err

    # --- Account / status -------------------------------------------------

    async def async_get_profile(self) -> dict[str, Any]:
        """Get the current user profile."""
        return await self._request("GET", PATH_PROFILE)

    async def async_get_usage_today(self) -> dict[str, Any]:
        """Get today's usage and quota (shape is not documented in the spec)."""
        data = await self._request("GET", PATH_USAGE_TODAY)
        return data if isinstance(data, dict) else {}

    async def async_get_subscription(self) -> dict[str, Any]:
        """Get the current user subscription summary."""
        return await self._request("GET", PATH_SUBSCRIPTION)

    async def async_list_generations(self) -> list[dict[str, Any]]:
        """List the current user's generation tasks (most recent first)."""
        data = await self._request("GET", PATH_GENERATIONS)
        return _as_list(data)

    # --- Actions ----------------------------------------------------------

    async def async_create_generation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a new music generation task."""
        clean = {k: v for k, v in payload.items() if v is not None}
        return await self._request("POST", PATH_GENERATIONS, json=clean)

    async def async_rate_song(self, song_id: str, rating: str) -> Any:
        """Rate a song (like / dislike / skip)."""
        return await self._request(
            "POST", PATH_RATE.format(song_id=song_id), json={"rating": rating}
        )

    # --- Browsing ---------------------------------------------------------

    async def async_list_songs(
        self,
        *,
        search: str | None = None,
        genre: str | None = None,
        mood: str | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List songs with optional filters."""
        data = await self._request(
            "GET",
            PATH_SONGS,
            params={
                "search": search,
                "genre": genre,
                "mood": mood,
                "page": page,
                "limit": limit,
            },
        )
        return _as_list(data)

    async def async_get_random_song(self, genre: str) -> dict[str, Any] | None:
        """Get a random song for a genre."""
        data = await self._request(
            "GET", PATH_RANDOM, params={"genre": genre}, auth=False
        )
        return data if isinstance(data, dict) else None

    async def async_get_popular_genres(self) -> list[Any]:
        """Get the most popular genres by song count."""
        data = await self._request("GET", PATH_POPULAR_GENRES, auth=False)
        return _as_list(data)

    # --- Backend radio session -------------------------------------------

    async def async_start_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start a backend-managed listening session."""
        clean = {k: v for k, v in payload.items() if v is not None}
        return await self._request("POST", PATH_SESSION, json=clean)

    async def async_next_track(self) -> dict[str, Any]:
        """Get the next track (song or ad) for the current session."""
        return await self._request("POST", PATH_NEXT)

    async def async_report_progress(self, payload: dict[str, Any]) -> Any:
        """Report playback progress for the current session."""
        clean = {k: v for k, v in payload.items() if v is not None}
        return await self._request("POST", PATH_PROGRESS, json=clean)

    async def async_update_session(self, payload: dict[str, Any]) -> Any:
        """Update the current session vibe (genres, mood, prompt…)."""
        clean = {k: v for k, v in payload.items() if v is not None}
        return await self._request("PATCH", PATH_SESSION, json=clean)

    # --- preferences & library -------------------------------------------

    async def async_get_preferences(self) -> dict[str, Any]:
        """Get the user's music preferences (favourite genres, moods…)."""
        data = await self._request("GET", PATH_PREFERENCES)
        return data if isinstance(data, dict) else {}

    async def async_get_library_genres(self) -> list[Any]:
        """Get the unique genres present in the user's library."""
        return _as_list(await self._request("GET", PATH_LIBRARY_GENRES))

    async def async_get_library(
        self, *, type: str, genre: str = "", page: int = 1, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get the user's library (all params are required by the API)."""
        data = await self._request(
            "GET",
            PATH_LIBRARY,
            params={"type": type, "genre": genre, "page": page, "limit": limit},
        )
        return _as_list(data)

    async def async_get_library_best_effort(
        self, candidates: list[str], genre: str = ""
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Try several ``type`` values, return (working_type, songs).

        The library ``type`` parameter is not documented with an enum, so we
        probe a few likely values and use the first that succeeds.
        """
        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                songs = await self.async_get_library(type=candidate, genre=genre)
            except NovyaApiError as err:
                last_exc = err
                continue
            return candidate, songs
        if last_exc is not None:
            raise last_exc
        return None, []


def _as_list(data: Any) -> list[Any]:
    """Coerce common API list shapes into a plain list.

    Different Novya endpoints may return either a raw array or an object that
    wraps the array under ``items`` / ``data`` / ``songs`` / ``results``.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "songs", "results", "tasks"):
            if isinstance(data.get(key), list):
                return data[key]
    return []
