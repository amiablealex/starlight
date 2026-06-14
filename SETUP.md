# Setup — from a fresh OS flash to a running kiosk

Target: a Raspberry Pi 3B with an HDMI monitor, showing the dashboard on boot
and sleeping the screen when nothing's playing. Assumes the player is already
(or will be) exposed in Home Assistant as a `media_player` entity.

Throughout, the user is assumed to be `pi`. If yours differs, adjust paths.

---

## 1. Flash Raspberry Pi OS Lite (Trixie, 32-bit)

In Raspberry Pi Imager:

- **Device:** Raspberry Pi 3
- **OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (32-bit)**
  (Trixie). 32-bit is the right call on a 1 GB Pi — it leaves more RAM for
  Chromium than the 64-bit build.
- **Settings (the cog):** set hostname `starlight`, username `pi`, a password,
  your Wi-Fi if you're not using Ethernet, your locale, and **enable SSH**.

Flash, boot, and SSH in:

```bash
ssh pi@starlight.local      # or ssh pi@<ip>
```

Wired Ethernet is worth it here if you can — steadier than the 3B's 2.4 GHz
Wi-Fi, which also helps Squeezelite timing.

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

## 3. Bring back Squeezelite and VirtualHere

These are your existing pieces, just re-applied on the fresh OS:

- **VirtualHere:** download the **armhf** server build (32-bit) and re-apply
  your premium licence. Licences are tied to the server instance, so use
  VirtualHere's licence-transfer process for the new install.
- **Squeezelite:** reinstall, then point it at the UCA222 (`hw:CARD=CODEC`),
  keep your `-b 512:512` buffer args, and re-add the player in Music Assistant
  (leave the group's HTTP profile on "forced content length" as before).

Neither depends on anything in this project; do them whenever suits.

## 4. Get the project onto the Pi

```bash
git clone <your-repo-url> ~/starlight-dashboard
cd ~/starlight-dashboard
```

(Or `scp`/`rsync` the files across if the repo isn't pushed yet.)

## 5. Install the app

```bash
./scripts/install.sh
```

This creates the virtualenv, installs dependencies, copies `config/xinitrc` to
`~/.xinitrc`, and installs + enables the systemd service. Then add your token:

```bash
nano .env          # set HA_TOKEN (HA → profile → Security → long-lived tokens)
sudo systemctl start starlight-dashboard
```

## 6. Check it before going full-kiosk

From your desktop browser, open `http://<pi-ip>:8080`. You should see the
dashboard reflecting whatever the player is doing. Useful checks:

```bash
# confirm the entity id is right (lists all media_players HA knows)
#   http://<pi-ip>:8080/debug/players
sudo systemctl status starlight-dashboard      # is the service happy?
journalctl -u starlight-dashboard -f           # live logs
```

If `/debug/players` shows a different entity id than `media_player.starlight_hifi`,
put the correct one in `.env` and `sudo systemctl restart starlight-dashboard`.

## 7. Turn on auto-login so the kiosk starts on boot

Enable console autologin:

```bash
sudo raspi-config
#  → System Options → Boot / Auto Login → Console Autologin
```

(Or non-interactively: `sudo raspi-config nonint do_boot_behaviour B2`.)

Then make the autologin shell start the X kiosk **on tty1 only** (so SSH stays
a normal shell). Append the snippet to `~/.bash_profile`:

```bash
cat config/bash_profile_snippet.sh >> ~/.bash_profile
```

## 8. Reboot

```bash
sudo reboot
```

On boot the Pi logs in on tty1, starts X, launches Chromium fullscreen at the
dashboard, and the screen-sleep logic takes over.

## 9. Verify screen sleep

Play something — the screen should be on. Stop playback and wait out
`SCREEN_SLEEP_GRACE` (60 s by default): the backlight should switch off as the
monitor loses signal and enters standby. Start playback again — it should wake.

Most portable monitors sleep on signal loss. If yours instead shows a
persistent "No Signal" splash and stays lit, set `SCREEN_SLEEP_ENABLED=false`
and switch it off at the button when you're done — or drive a smart plug from
Home Assistant on the player's state for a true-off cut.

---

## Optional tuning

Nice-to-haves for an appliance that runs for years. None are required.

**zram** — compressed swap in RAM instead of thrashing the SD card:

```bash
sudo apt install -y zram-tools
# edit /etc/default/zramswap: ALGO=lz4, PERCENT=50
sudo systemctl restart zramswap
```

**If the display comes up at the wrong resolution.** Modern Raspberry Pi OS
uses the KMS graphics stack and reads the monitor's EDID automatically, so this
usually isn't needed. If it isn't detected, force it by adding to the end of
the single line in `/boot/firmware/cmdline.txt`:

```
video=HDMI-A-1:1360x768@60
```

**GPU memory.** On the KMS driver this is largely auto-managed via CMA, so the
old `gpu_mem` split barely matters now — leave it at the default. (If you ever
fall back to legacy graphics, `gpu_mem=128` in `/boot/firmware/config.txt` is a
sensible value.)

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

- **Blank screen / no Chromium:** check you're on tty1 and the
  `~/.bash_profile` snippet is present. `cat ~/.xinitrc` should be the kiosk
  script. Try `startx` manually to see errors.
- **"Reconnecting…" forever:** the service can't reach Home Assistant. Check
  `HA_BASE_URL`/`HA_TOKEN` in `.env` and `journalctl -u starlight-dashboard`.
- **Screen won't sleep:** confirm `xset` is installed and the `xhost` line ran
  (it's in `~/.xinitrc`); see the note in step 9 about stubborn monitors.
- **Visual glitches on the 3B:** add `--disable-gpu` to the Chromium flags in
  `~/.xinitrc` and reboot. Software-rendering this page is perfectly smooth.
