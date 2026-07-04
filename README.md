# Novya.live – Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Unofficial Home Assistant integration for [Novya.live](https://app.novya.live), the AI
music generation platform. **Requires Home Assistant 2025.1 or newer.**
It connects to the Novya REST API and lets you:

- **Listen**: browse and play your Novya songs on any media player (Sonos,
  Chromecast, VLC, speakers…) via the Home Assistant **Media Browser** —
  Recent songs, **By genre**, your **Favorite genres**, **Your library** and
  **Your playlists**.
- **InfinityPlay / Radio**: a dedicated **Novya InfinityPlay** media player that runs
  the backend-managed listening session as a continuous, auto-advancing radio —
  play, pause, next track, now-playing title and artwork — driving the speaker
  you choose in the options.
- **Generate**: trigger AI music generation from automations, scripts or the UI.
- **Monitor** your account with sensors: daily generations used / remaining,
  daily limit, subscription status and the status of your latest AI generation.

> This is a community integration and is not affiliated with Novya.

## Installation

### HACS (recommended)
1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/manustars/ha-novya` with category
   **Integration**.
3. Search for **Novya.live**, install it, and restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration → Novya.live**.

### Manual
1. Copy the `custom_components/novya_live` folder into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for
   **Novya.live**.

### Updating

Every update (via HACS or manual copy) **requires a full Home Assistant
restart** to take effect — reloading the integration is not enough, since
Python keeps the previously loaded code in memory.

Since neither HACS nor Home Assistant reliably warn you about this on their
own, the integration checks for itself: once the files on disk no longer
match the version currently running in memory, it raises a **Repair**
(**Settings → System → Repairs**) telling you a restart is needed — click
**Fix** there to restart Home Assistant directly. This check runs every 5
minutes (piggy-backing on the regular status refresh), so it can take a few
minutes to appear after an update.

## Configuration

You will be asked for:

| Field | Description |
|-------|-------------|
| Email | Your Novya account email |
| Password | Your Novya account password |
| Server URL | Defaults to `https://app.novya.live` |

The integration logs in, stores the credentials and refreshes the JWT token
automatically when it expires.

## Entities

| Sensor | Description |
|--------|-------------|
| `sensor.novya_live_generations_used_today` | Generations used today (raw payload in attributes) |
| `sensor.novya_live_generations_remaining_today` | Remaining daily generations |
| `sensor.novya_live_daily_generation_limit` | Daily generation limit (from plan) |
| `sensor.novya_live_subscription_status` | Subscription status; plan info in attributes |
| `sensor.novya_live_latest_generation_status` | Status of the most recent generation task |

> The `/api/usage/today` response is not described in the published OpenAPI
> spec, so the usage sensors read the most likely keys and expose the full raw
> payload under the `raw_usage` attribute. If your instance uses different field
> names, check that attribute and the mapping can be adjusted in
> `sensor.py` (`_usage_used` / `_usage_limit` / `_usage_remaining`).

## Playing music

**Single songs** — open the **Media** panel (or the media browser of any player)
and pick **Novya.live → Recent songs**, **By genre**, **Favorite genres** (taken
from your Novya music preferences) or **Your library** (your own songs), then
play onto any speaker. Streaming URLs are public, so playback works on any
device.

**Continuous radio (InfinityPlay)** — use the **Novya InfinityPlay** media player
(`media_player.novya_live_*_playlist`):

1. Open **Settings → Devices & Services → Novya → Configure** and pick the
   **Target media player** (the speaker the radio should play on).
2. Press **Play** on the Novya InfinityPlay entity. It starts a backend session and
   plays the queue, automatically advancing to the next AI-generated track when
   the current one ends. **Next** skips, **Pause/Stop** control playback, and the
   card shows the current title and cover art.

The radio also exposes **Browse media**, so you can pick a single Novya song from
the radio card itself.

**Choosing the vibe from the dashboard** — three entities on the Novya device
let you set genre, mood and exploration level without opening the options or
calling a service:

| Entity | Description |
|--------|-------------|
| `select.novya_live_infinityplay_genre` | Genre (options pulled from the Novya genre catalogue) |
| `select.novya_live_infinityplay_mood` | Mood (curated list — the API has no fixed enum for this) |
| `number.novya_live_infinityplay_exploration_level` | 0 (stick to taste) to 5 (explore) |

Changing any of these while InfinityPlay is playing steers the running
session immediately (same effect as `novya.set_vibe`); it also becomes the
default the next time you press **Play**. The **Target media player** /
genres / mood / exploration level fields in the options screen still exist
and only act as the *initial* seed on first setup — after that, use these
three entities instead.

> Why a target speaker? Home Assistant entities can't emit audio on their own, so
> the radio drives one of your existing media players. Change the target anytime
> in the options — the integration reloads automatically.

## Services

### `novya.generate_song`
Start an AI generation. Supports response data (returns the created task).

```yaml
action: novya.generate_song
data:
  prompt: An upbeat synthwave track about driving at night
  genre: synthwave
  mood: energetic
  duration: 180
```

### `novya.rate_song`
```yaml
action: novya.rate_song
data:
  song_id: 550e8400-e29b-41d4-a716-446655440000
  rating: like   # like | dislike | skip
```

### `novya.play_radio`
Start a backend-managed session and play the first track on a speaker.
```yaml
action: novya.play_radio
data:
  entity_id: media_player.living_room
  genres: [pop, electronic]
  mood: chill
  exploration_level: 1
```

### `novya.radio_next`
Skip to the next track of the current session on a player.
```yaml
action: novya.radio_next
data:
  entity_id: media_player.living_room
```

### `novya.set_vibe`
Steer the running playlist on the fly (genre / mood / prompt) — affects the
upcoming tracks of the current session.
```yaml
action: novya.set_vibe
data:
  genres: [lo-fi, jazz]
  mood: relaxed
```

## Choosing what to listen to

- **By any genre**: media browser → *By genre*.
- **Your favorite genres**: media browser → *Favorite genres* (pulled from your
  Novya preferences: `favoriteGenres`). The **InfinityPlay** player also starts from
  these by default when you haven't set genres in the options.
- **Your own songs**: media browser → *Your library*.
- **Your saved playlists**: media browser → *Your playlists* → open one to see
  and play its songs in order.
- **On the fly**: `novya.set_vibe` to change genre/mood while InfinityPlay plays.

> Note on "favorites": Novya stores favorite **genres/moods** in your
> preferences (used above), and per-song **like/dislike** ratings (service
> `novya.rate_song`) that feed your recommendations and taste profile. The API
> does not expose a separate "liked songs" list, so there is no dedicated
> *Liked* folder. *Your library* uses the `type` parameter, which is not
> documented with fixed values — the integration probes a few (`all`,
> `generated`, …) and uses the first that works.

## Events

`novya_generation_started` is fired when a generation task is created, with the
`task_id` and full `task` payload — handy for waiting on completion in
automations.

## Compatibility

Built for and validated against **Home Assistant 2025.1+** (uses
`runtime_data`, typed config entry, coordinator with explicit `config_entry`,
and an options flow that doesn't set `config_entry` manually — all current
patterns that remain valid through the 2025.x releases).

## Notes / limitations

- The **Novya InfinityPlay** player and the `play_radio` service target one of your
  existing media players, because HA entities can't emit audio by themselves.
- Auto-advance detects the target player finishing a track (transition to
  idle/off). Most players behave this way; very unusual players may need the
  **Next** button.
- Admin-only endpoints (model management, ads, infinite generation, etc.) are
  intentionally not exposed.
