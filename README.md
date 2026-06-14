# Starlight HiFi dashboard

A small full-screen "now playing" display for a Raspberry Pi wired to an old
hi-fi. It reads one Home Assistant `media_player` entity and shows the cover
art, title, artist, album, and progress for whatever that player is playing.

It's built for one job in one room, so it's deliberately narrow: no controls,
no library, no settings UI. Just the screen.

![what it shows: cover art on the left, track details on the right, on a near-black background]

## How it works

A background thread polls Home Assistant once a second and caches the result.
The browser only ever talks to local Flask, so a Home Assistant restart or a
network blip just shows "Reconnecting…" and recovers on the next poll — no
crash, no white screen. Cover art is proxied and downscaled through Flask, and
a single accent colour is pulled from each cover for the progress bar and
artist line.

The same thread manages the monitor. While music plays the screen is on; after
a minute of nothing playing it drops the HDMI signal (DPMS), and the panel
falls into its own backlight-off standby. It wakes the instant playback starts.

Polling rather than a websocket is a choice, not a shortcut: on an always-on
appliance a persistent socket is one more thing to die silently, whereas a
one-second poll self-heals every cycle. The progress bar stays smooth because
the browser interpolates between polls.

## Requirements

- A Raspberry Pi running a Chromium kiosk (Raspberry Pi OS Lite + a minimal X
  session — see [SETUP.md](SETUP.md)).
- Home Assistant reachable on the network, with the player exposed as a
  `media_player` entity (e.g. via the Music Assistant integration).

## Setup

Full step-by-step, from a fresh OS flash to a running kiosk, is in
[SETUP.md](SETUP.md). The short version once the OS packages are in place:

```bash
git clone <your-repo-url> ~/starlight-dashboard
cd ~/starlight-dashboard
./scripts/install.sh          # venv, deps, ~/.xinitrc, systemd service
nano .env                     # add your Home Assistant token
sudo systemctl start starlight-dashboard
```

## Configuration

Everything lives in `.env` (copied from `.env.example`; gitignored):

| Variable | What it does |
| --- | --- |
| `HA_BASE_URL` | Home Assistant URL, no trailing slash |
| `HA_TOKEN` | Long-lived access token |
| `HA_ENTITY_ID` | The room's `media_player` entity |
| `DASHBOARD_PORT` | Port Flask listens on (default 8080) |
| `POLL_INTERVAL` | Seconds between polls (default 1.0) |
| `SCREEN_SLEEP_ENABLED` | Whether to power the monitor down when idle |
| `SCREEN_SLEEP_GRACE` | Seconds of nothing playing before sleep |

Not sure of the entity id? With the service running, `http://<pi>:8080/debug/players`
lists every `media_player` Home Assistant knows about.

## Tech

Python (Flask, waitress, Pillow) on a Raspberry Pi 3B. Type is
[Inter](https://github.com/rsms/inter) (SIL Open Font License). No build step,
no JavaScript framework — one HTML file, one stylesheet, one script.
