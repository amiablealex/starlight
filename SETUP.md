# Setup — from a fresh OS flash to a running kiosk

This takes a Raspberry Pi with an attached screen and turns it into a dedicated
display that boots straight into the dashboard and sleeps the screen when
nothing's playing.

**Prerequisite:** the player you want to show must already exist in Home
Assistant as a `media_player` entity. How you get one — Music Assistant, Sonos,
Cast, AirPlay, an AVR integration, a squeezelite player — is your choice and
isn't part of this project. If you can see it under Developer Tools → States in
Home Assistant, you're ready.

Throughout, the user is assumed to be `pi`. If yours differs, adjust paths.

---

## 1. Flash Raspberry Pi OS Lite

In Raspberry Pi Imager:

- **OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite**. On a 1 GB Pi
  (3 / 3B / Zero 2 W) pick the **32-bit** image — it leaves more RAM for
  Chromium. On a Pi 4 or 5 with 2 GB or more, use the 64-bit image.
- **Settings (the cog):** set a hostname, a username and password, your Wi-Fi
  (or use Ethernet), your locale, and **enable SSH**.

Flash, boot, and SSH in:

```bash
ssh pi@<hostname>.local      # or ssh pi@<ip>
```

Wired Ethernet is steadier than Wi-Fi for an always-on box, if you can manage
it.

## 2. Update and install packages

```bash
sudo apt update && sudo apt full-upgrade -y

# minimal X + kiosk stack (no desktop)
sudo apt install -y --no-install-recommends \
  xserver-xorg xinit x11-xserver-utils openbox \
  fonts-dejavu-core python3-venv python3-pip \
  libopenjp2-7

# the browser
sudo apt install -y chromium-browser
```

Notes:
- `x11-xserver-utils` provides `xset`/`xhost` (the screen-sleep mechanism).
- `libopenjp2-7` is a Pillow runtime dependency. If Pillow ever fails to
  import, also try `sudo apt install -y libtiff6 libjpeg62-turbo`.
- If `chromium-browser` isn't found on your image, install `chromium` instead —
  the kiosk script handles either name.

## 3. Get the project onto the Pi

```bash
git clone https://github.com/amiablealex/starlight.git ~/starlight-dashboard
cd ~/starlight-dashboard
```

## 4. Install the app

```bash
./scripts/install.sh
```

This creates the virtualenv, installs dependencies, copies `config/xinitrc` to
`~/.xinitrc`, and installs and enables the systemd service. Then point it at
your player:

```bash
nano .env          # set HA_BASE_URL, HA_TOKEN, and HA_ENTITY_ID
sudo systemctl start starlight-dashboard
```

The token comes from Home Assistant → your profile → Security → Long-lived
access tokens.

## 5. Check it before going full-kiosk

From another machine's browser, open `http://<pi-ip>:8080`. You should see the
dashboard reflecting whatever the player is doing. Useful checks:

```bash
# confirm the entity id is right (lists every media_player HA knows):
#   http://<pi-ip>:8080/debug/players
sudo systemctl status starlight-dashboard      # is the service happy?
journalctl -u starlight-dashboard -f           # live logs
```

If `/debug/players` shows a different entity id than the one in `.env`, correct
it and `sudo systemctl restart starlight-dashboard`.

## 6. Turn on auto-login so the kiosk starts on boot

Enable console autologin:

```bash
sudo raspi-config
#  → System Options → Boot / Auto Login → Console Autologin
```

(Or non-interactively: `sudo raspi-config nonint do_boot_behaviour B2`.)

Then make the autologin shell start the X kiosk **on tty1 only** (so SSH stays a
normal shell). Append the snippet to `~/.bash_profile`:

```bash
cat config/bash_profile_snippet.sh >> ~/.bash_profile
```

## 7. Reboot

```bash
sudo reboot
```

On boot the Pi logs in on tty1, starts X, launches Chromium fullscreen at the
dashboard, and the screen-sleep logic takes over.

## 8. Verify screen sleep

Play something — the screen should be on. Stop playback and wait out
`SCREEN_SLEEP_GRACE` (60 s by default): the backlight should switch off as the
screen loses signal and enters standby. Start playback again — it should wake.

Most monitors sleep on signal loss. If yours instead shows a persistent
"No Signal" splash and stays lit, set `SCREEN_SLEEP_ENABLED=false` and switch it
off at the button when you're done — or drive a smart plug from Home Assistant
on the player's state for a true-off cut.

---

## Optional tuning

Nice-to-haves for an appliance that runs for years. None are required.

**zram** — compressed swap in RAM instead of thrashing the SD card:

```bash
sudo apt install -y zram-tools
# edit /etc/default/zramswap: ALGO=lz4, PERCENT=50
sudo systemctl restart zramswap
```

**If the display comes up at the wrong resolution.** Modern Raspberry Pi OS uses
the KMS graphics stack and reads the monitor's EDID automatically, so this
usually isn't needed. If it isn't detected, force it by adding to the end of the
single line in `/boot/firmware/cmdline.txt`:

```
video=HDMI-A-1:1360x768@60
```

**Reduce SD-card writes.** The app is low-write, but routing logs to RAM with
`log2ram` extends card life on a 24/7 appliance.

## Updating later

```bash
cd ~/starlight-dashboard
git pull
sudo systemctl restart starlight-dashboard
```

Changes to `~/.xinitrc` or the kiosk only take effect on the next reboot (or
after restarting the X session).

## Troubleshooting

- **Black screen after Chromium starts (common on Pi 3 / 3B).** The full KMS
  driver can fail to render here — X starts but nothing composites. Two fixes:
  either add `--disable-gpu` to the Chromium flags in `~/.xinitrc` (forces
  software rendering, keeps the modern stack), or switch to the legacy
  framebuffer: `sudo apt install -y xserver-xorg-video-fbdev`, then comment out
  `dtoverlay=vc4-kms-v3d` in `/boot/firmware/config.txt` and reboot. On a Pi 4
  or 5, KMS works fine — you shouldn't need either.
- **"Reconnecting…" forever.** The service can't reach Home Assistant. Check
  `HA_BASE_URL`/`HA_TOKEN` in `.env` and `journalctl -u starlight-dashboard`.
- **Screen won't sleep.** First confirm `SCREEN_SLEEP_ENABLED=true` and the
  tool for your mode is installed. If you're on the **legacy framebuffer**
  (KMS disabled), `xset` DPMS only blanks the picture to black and leaves the
  backlight on — set `SCREEN_CONTROL=vcgencmd` in `.env` and restart, which uses
  the Pi firmware to actually power the HDMI output down. (`vcgencmd` needs the
  service user to be in the `video` group; the default `pi` user already is.)
  Also see the note in step 8 about monitors that refuse to sleep on signal
  loss.
- **Blank screen / no Chromium at all.** Check you're on tty1 and the
  `~/.bash_profile` snippet is present; `cat ~/.xinitrc` should be the kiosk
  script. Run `startx` manually to see errors.
