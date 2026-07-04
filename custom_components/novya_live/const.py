"""Constants for the Novya integration."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

DOMAIN = "novya_live"

ISSUE_RESTART_REQUIRED = "restart_required"


def read_manifest_version() -> str | None:
    """Read the version field straight from manifest.json on disk.

    Bypasses Python's module import cache, so it reflects files HACS may have
    already replaced on disk even before Home Assistant is restarted.
    """
    try:
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    except OSError:
        return None
    return manifest.get("version")


# Captured once, when this module is first imported after a Home Assistant
# start/restart -- i.e. the version actually running in memory right now.
RUNNING_VERSION = read_manifest_version()

CONF_BASE_URL = "base_url"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Options.
CONF_TARGET = "target_entity_id"
CONF_GENRES = "genres"
CONF_MOOD = "mood"
CONF_EXPLORATION = "exploration_level"

DEFAULT_BASE_URL = "https://app.novya.live"

# Polling interval for usage / subscription / generation status.
UPDATE_INTERVAL = timedelta(minutes=5)

PLATFORMS = ["media_player", "sensor"]

# API paths (already include the /api prefix where required by the spec).
PATH_LOGIN = "/api/auth/login"
PATH_PROFILE = "/api/users/me"
PATH_USAGE_TODAY = "/api/usage/today"
PATH_SUBSCRIPTION = "/api/subscription/me"
PATH_GENERATIONS = "/api/generation"
PATH_SONGS = "/api/songs"
PATH_RANDOM = "/api/songs/random"
PATH_POPULAR_GENRES = "/api/songs/popular-genres"
PATH_LIBRARY = "/api/songs/library"
PATH_LIBRARY_GENRES = "/api/songs/library/genres"
PATH_PREFERENCES = "/api/users/me/preferences"
PATH_RATE = "/api/songs/{song_id}/rate"
PATH_SESSION = "/api/playlist/session"
PATH_NEXT = "/api/playlist/next"
PATH_PROGRESS = "/api/playlist/progress"

# Saved playlists (distinct from the /api/playlist/* radio session above).
PATH_PLAYLISTS = "/api/playlists"

# Public (no-auth) media paths.
PATH_STREAM = "/api/songs/stream/{song_id}"
PATH_COVER = "/api/songs/{song_id}/cover"

# Service names.
SERVICE_GENERATE_SONG = "generate_song"
SERVICE_RATE_SONG = "rate_song"
SERVICE_PLAY_RADIO = "play_radio"
SERVICE_RADIO_NEXT = "radio_next"
SERVICE_SET_VIBE = "set_vibe"

# Event fired when an asynchronous generation task is created.
EVENT_GENERATION_STARTED = "novya_generation_started"
