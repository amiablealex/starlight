#!/usr/bin/env python3
"""Starlight HiFi - a minimal now-playing dashboard.

Reads a single Home Assistant ``media_player`` entity and serves a full-screen
"now playing" page for a Chromium kiosk. A background thread polls Home
Assistant once a second and caches the result, so the browser only ever talks
to local Flask - if Home Assistant blips, the next poll recovers on its own.

The same thread manages the screen's power: it wakes the display when something
plays and, after a grace period of nothing playing, powers it down. The
mechanism is configurable (SCREEN_CONTROL) - `xset` DPMS for X11/KMS, the Pi's
`vcgencmd display_power` for the legacy framebuffer, or any custom command pair.
"""
import colorsys
import hashlib
import io
import logging
import os
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, send_file
from PIL import Image
from waitress import serve

# --- configuration -------------------------------------------------------

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    base_url = os.environ.get("HA_BASE_URL", "").rstrip("/")
    token = os.environ.get("HA_TOKEN", "")
    entity_id = os.environ.get("HA_ENTITY_ID", "media_player.living_room")
    port = int(os.environ.get("DASHBOARD_PORT", "8080"))
    poll_interval = float(os.environ.get("POLL_INTERVAL", "1.0"))
    screen_sleep = _env_bool("SCREEN_SLEEP_ENABLED", True)
    screen_grace = float(os.environ.get("SCREEN_SLEEP_GRACE", "60"))
    screen_control = os.environ.get("SCREEN_CONTROL", "xset").strip().lower()
    screen_on_cmd = os.environ.get("SCREEN_ON_CMD", "")
    screen_off_cmd = os.environ.get("SCREEN_OFF_CMD", "")
    display = os.environ.get("DISPLAY", ":0")


cfg = Config()

DEFAULT_ACCENT = "#9aa0a6"   # neutral, used when there's no art or no usable colour
ART_MAX_PX = 600             # cover art is downscaled to this before serving

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("starlight")


# --- helpers -------------------------------------------------------------

def parse_position(attrs, playing):
    """Return the current track position in seconds, advanced to 'now'.

    Home Assistant reports ``media_position`` as of ``media_position_updated_at``.
    While playing we add the elapsed wall-clock time so the progress bar is
    correct the moment the browser receives it; the browser then interpolates
    between polls. While paused the reported position is already current.
    """
    pos = attrs.get("media_position")
    if pos is None:
        return None
    if not playing:
        return float(pos)
    updated = attrs.get("media_position_updated_at")
    if not updated:
        return float(pos)
    try:
        ref = datetime.fromisoformat(updated)
    except ValueError:
        return float(pos)
    elapsed = (datetime.now(timezone.utc) - ref).total_seconds()
    return max(0.0, float(pos) + elapsed)


def dominant_accent(img):
    """Pick one vivid, legible accent colour from an album cover.

    Quantises the cover to a small palette, scores each colour by saturation
    and brightness (lightly weighted by how much of the cover it covers), and
    skips near-black / near-white / washed-out colours. The winner is nudged
    brighter so it reads cleanly against a near-black background.
    """
    try:
        sample = img.convert("RGB")
        sample.thumbnail((80, 80))
        quantised = sample.quantize(colors=8)
        palette = quantised.getpalette() or []
        colours = quantised.getcolors() or []
        best, best_score = None, -1.0
        for count, idx in colours:
            r, g, b = palette[idx * 3: idx * 3 + 3]
            _, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if v < 0.2 or v > 0.95 or s < 0.15:
                continue
            score = (s * 0.7 + v * 0.3) * (1.0 + min(count, 2000) / 4000.0)
            if score > best_score:
                best, best_score = (r, g, b), score
        if best is None:
            return DEFAULT_ACCENT
        r, g, b = best
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        v = max(v, 0.72)          # guarantee legibility on near-black
        s = min(s, 0.85)
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    except Exception as exc:  # never let colour maths break a render
        log.warning("accent extraction failed: %s", exc)
        return DEFAULT_ACCENT


def resolve_screen_commands(mode, on_cmd_str, off_cmd_str):
    """Return (on_command, off_command) as argv lists for the chosen mechanism.

    - ``xset``     : X11 / KMS DPMS (the default).
    - ``vcgencmd`` : the Pi firmware's HDMI power, for the legacy framebuffer
                     driver where DPMS only blanks to black without sleeping.
    - ``command``  : whatever SCREEN_ON_CMD / SCREEN_OFF_CMD contain.

    Anything else returns empty lists, which disables screen control.
    """
    mode = (mode or "xset").strip().lower()
    if mode == "xset":
        return (["xset", "dpms", "force", "on"],
                ["xset", "dpms", "force", "off"])
    if mode == "vcgencmd":
        return (["vcgencmd", "display_power", "1"],
                ["vcgencmd", "display_power", "0"])
    if mode == "command":
        return (shlex.split(on_cmd_str or ""), shlex.split(off_cmd_str or ""))
    return ([], [])


# --- background poller ---------------------------------------------------

class Poller(threading.Thread):
    def __init__(self, config):
        super().__init__(daemon=True)
        self.cfg = config
        self._lock = threading.Lock()
        self._state = {"connected": False, "state": "unknown"}
        self._art_bytes = None
        self._art_type = "image/jpeg"
        self._art_token = None
        self._accent = DEFAULT_ACCENT
        self._session = requests.Session()
        if config.token:
            self._session.headers["Authorization"] = f"Bearer {config.token}"
        self._screen_on = None                 # None = unknown until first action
        self._last_active = time.monotonic()
        self._on_cmd, self._off_cmd = resolve_screen_commands(
            config.screen_control, config.screen_on_cmd, config.screen_off_cmd)
        self._screen_ok = self._check_screen_tooling()

    def _check_screen_tooling(self):
        if not self.cfg.screen_sleep:
            return False
        if not self._on_cmd or not self._off_cmd:
            log.warning("screen control off: no command for SCREEN_CONTROL=%r",
                        self.cfg.screen_control)
            return False
        binary = self._off_cmd[0]
        if shutil.which(binary) is None:
            log.warning("screen control off: %r not found on PATH", binary)
            return False
        return True

    # -- read side (used by the web routes) ------------------------------
    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def art(self):
        with self._lock:
            return self._art_bytes, self._art_type

    # -- loop ------------------------------------------------------------
    def run(self):
        while True:
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("poll failed: %s", exc)
                with self._lock:
                    self._state = {**self._state, "connected": False}
            try:
                self._manage_screen()
            except Exception as exc:
                log.debug("screen management: %s", exc)
            time.sleep(self.cfg.poll_interval)

    def _poll_once(self):
        url = f"{self.cfg.base_url}/api/states/{self.cfg.entity_id}"
        resp = self._session.get(url, timeout=4)
        resp.raise_for_status()
        data = resp.json()
        attrs = data.get("attributes", {})
        raw = data.get("state", "unknown")
        playing = raw == "playing"

        duration = attrs.get("media_duration")
        position = parse_position(attrs, playing)
        if duration and position is not None:
            position = min(position, float(duration))

        art_source = attrs.get("entity_picture") or attrs.get("entity_picture_local")
        token = hashlib.sha1(art_source.encode()).hexdigest()[:12] if art_source else None
        if token != self._art_token:
            self._refresh_art(art_source, token)

        state = {
            "connected": True,
            "state": raw,
            "playing": playing,
            "title": attrs.get("media_title"),
            "artist": attrs.get("media_artist"),
            "album": attrs.get("media_album_name"),
            "duration": float(duration) if duration else None,
            "position": position,
            "has_art": self._art_bytes is not None,
            "art_token": self._art_token,
            "accent": self._accent,
        }
        with self._lock:
            self._state = state
        if playing:
            self._last_active = time.monotonic()

    def _refresh_art(self, source, token):
        if not source:
            with self._lock:
                self._art_bytes, self._art_token, self._accent = None, None, DEFAULT_ACCENT
            return
        try:
            if source.startswith("http"):
                resp = requests.get(source, timeout=6)         # absolute (e.g. MA image proxy)
            else:
                resp = self._session.get(self.cfg.base_url + source, timeout=6)  # HA-relative
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            accent = dominant_accent(img)
            img.thumbnail((ART_MAX_PX, ART_MAX_PX))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            with self._lock:
                self._art_bytes = buf.getvalue()
                self._art_type = "image/jpeg"
                self._art_token = token
                self._accent = accent
        except Exception as exc:
            log.warning("art fetch failed: %s", exc)
            with self._lock:
                self._art_bytes, self._art_token, self._accent = None, None, DEFAULT_ACCENT

    def _manage_screen(self):
        if not self._screen_ok:
            return
        playing = self.snapshot().get("playing")
        if playing:
            if self._screen_on is not True:
                self._set_screen(True)
        elif (time.monotonic() - self._last_active) > self.cfg.screen_grace:
            if self._screen_on is not False:
                self._set_screen(False)

    def _set_screen(self, on):
        cmd = self._on_cmd if on else self._off_cmd
        action = "on" if on else "off"
        try:
            subprocess.run(
                cmd,
                env=dict(os.environ, DISPLAY=self.cfg.display),
                check=True, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._screen_on = on
            log.info("screen %s (%s)", action, cmd[0])
        except Exception as exc:
            # the display tool may not be ready yet during early boot; retry next cycle
            log.debug("screen %s command failed: %s", action, exc)


poller = Poller(cfg)

# --- web app -------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    resp = jsonify(poller.snapshot())
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/art")
def art():
    data, ctype = poller.art()
    if not data:
        return Response(status=204)
    resp = send_file(io.BytesIO(data), mimetype=ctype)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/healthz")
def healthz():
    return jsonify(ok=True, connected=poller.snapshot().get("connected", False))


@app.route("/debug/players")
def debug_players():
    """List media_player entities - handy for confirming HA_ENTITY_ID."""
    try:
        resp = poller._session.get(f"{cfg.base_url}/api/states", timeout=5)
        resp.raise_for_status()
        players = [
            {
                "entity_id": s["entity_id"],
                "name": s.get("attributes", {}).get("friendly_name"),
                "state": s.get("state"),
            }
            for s in resp.json()
            if s.get("entity_id", "").startswith("media_player.")
        ]
        return jsonify(sorted(players, key=lambda p: p["entity_id"]))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


def main():
    if not cfg.base_url or not cfg.token:
        log.warning("HA_BASE_URL or HA_TOKEN is not set - check your .env file")
    poller.start()
    log.info("dashboard on :%d  (entity=%s)", cfg.port, cfg.entity_id)
    serve(app, host="0.0.0.0", port=cfg.port, threads=4)


if __name__ == "__main__":
    main()
