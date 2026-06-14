# --- Starlight HiFi kiosk -------------------------------------------------
# Append this to ~/.bash_profile. On console autologin it starts the X
# session (and therefore the kiosk) automatically on tty1, and nowhere else
# so you can still SSH in normally.
if [ -z "${DISPLAY:-}" ] && [ "${XDG_VTNR:-}" = "1" ]; then
  exec startx -- -nocursor
fi
