"""Smoke tests - no network or Home Assistant required.

Run from the project root:  ./venv/bin/python -m pytest -q
(pytest is a dev-only dependency: ./venv/bin/pip install pytest)
"""
import io

from PIL import Image

import app as appmod


def _jpeg(colour):
    img = Image.new("RGB", (64, 64), colour)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue(), img


def test_accent_is_legible_hex_and_tracks_hue():
    _, img = _jpeg((200, 30, 30))
    hexc = appmod.dominant_accent(img)
    assert hexc.startswith("#") and len(hexc) == 7
    r = int(hexc[1:3], 16); g = int(hexc[3:5], 16); b = int(hexc[5:7], 16)
    assert r > g and r > b            # a red cover yields a red-ish accent


def test_accent_falls_back_on_greyscale():
    _, img = _jpeg((128, 128, 128))
    assert appmod.dominant_accent(img) == appmod.DEFAULT_ACCENT


def test_position_paused_is_reported_as_is():
    assert appmod.parse_position({"media_position": 42}, playing=False) == 42.0


def test_position_missing_is_none():
    assert appmod.parse_position({}, playing=True) is None


def test_routes():
    appmod.poller._state = {
        "connected": True, "state": "playing", "playing": True,
        "title": "Daylight", "artist": "Taylor Swift", "album": "Lover",
        "duration": 294.0, "position": 100.0, "has_art": True,
        "art_token": "abc123", "accent": "#cc4422",
    }
    art_bytes, _ = _jpeg((10, 20, 200))
    appmod.poller._art_bytes = art_bytes
    appmod.poller._art_token = "abc123"

    client = appmod.app.test_client()

    assert client.get("/healthz").status_code == 200

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.get_json()["title"] == "Daylight"

    home = client.get("/")
    assert home.status_code == 200 and b"Starlight" in home.data

    art = client.get("/art")
    assert art.status_code == 200 and art.mimetype == "image/jpeg"


def test_art_returns_204_when_absent():
    appmod.poller._art_bytes = None
    assert appmod.app.test_client().get("/art").status_code == 204


def test_resolve_screen_commands():
    on, off = appmod.resolve_screen_commands("xset", "", "")
    assert off == ["xset", "dpms", "force", "off"]

    on, off = appmod.resolve_screen_commands("vcgencmd", "", "")
    assert on == ["vcgencmd", "display_power", "1"]
    assert off == ["vcgencmd", "display_power", "0"]

    on, off = appmod.resolve_screen_commands(
        "command", "tplink on living", "tplink off living")
    assert on == ["tplink", "on", "living"]
    assert off == ["tplink", "off", "living"]

    # unknown mode disables control (empty argv lists)
    assert appmod.resolve_screen_commands("nonsense", "", "") == ([], [])
