/* Polls the local Flask endpoint once a second and renders the result.
   Between polls the progress bar is interpolated from the last known
   position, so it moves smoothly without hammering Home Assistant. */
(function () {
  "use strict";

  var POLL_MS = 1000;
  var TICK_MS = 250;

  var el = {
    nowplaying: document.getElementById("nowplaying"),
    idle: document.getElementById("idle"),
    offline: document.getElementById("offline"),
    art: document.getElementById("art"),
    artwrap: document.getElementById("artwrap"),
    title: document.getElementById("title"),
    artist: document.getElementById("artist"),
    album: document.getElementById("album"),
    progress: document.getElementById("progress"),
    fill: document.getElementById("fill"),
    elapsed: document.getElementById("elapsed"),
    total: document.getElementById("total"),
    root: document.documentElement
  };

  var lastArtToken = null;
  var play = { position: 0, duration: 0, playing: false, at: 0, has: false };

  function fmt(t) {
    if (t === null || t === undefined || isNaN(t)) return "";
    t = Math.max(0, Math.floor(t));
    var m = Math.floor(t / 60);
    var s = t % 60;
    return m + ":" + (s < 10 ? "0" + s : s);
  }

  function show(view) {
    el.nowplaying.classList.toggle("hidden", view !== "nowplaying");
    el.idle.classList.toggle("hidden", view !== "idle");
    el.offline.classList.toggle("hidden", view !== "offline");
  }

  // states that mean "there is a track here", everything else is idle
  function isActive(s) {
    if (s.state === "playing" || s.state === "paused" || s.state === "buffering") return true;
    var dead = ["idle", "off", "standby", "unavailable", "unknown", "none", null];
    return !!s.title && dead.indexOf(s.state) === -1;
  }

  function render(s) {
    if (!s.connected) { play.playing = false; show("offline"); return; }
    if (!isActive(s)) { play.playing = false; show("idle"); return; }

    show("nowplaying");
    if (s.accent) el.root.style.setProperty("--accent", s.accent);

    el.title.textContent = s.title || "Playing";
    el.artist.textContent = s.artist || "";
    el.album.textContent = s.album || "";
    el.artist.style.display = s.artist ? "" : "none";
    el.album.style.display = s.album ? "" : "none";

    if (s.has_art && s.art_token) {
      if (s.art_token !== lastArtToken) {
        lastArtToken = s.art_token;
        el.art.src = "/art?token=" + encodeURIComponent(s.art_token);
      }
      el.artwrap.classList.remove("noart");
    } else {
      lastArtToken = null;
      el.art.removeAttribute("src");
      el.artwrap.classList.add("noart");
    }

    var hasProgress = !!s.duration && s.position !== null && s.position !== undefined;
    el.progress.classList.toggle("hidden", !hasProgress);
    el.nowplaying.classList.toggle("is-paused", s.state === "paused");

    play = {
      position: s.position || 0,
      duration: s.duration || 0,
      playing: s.state === "playing",
      at: performance.now(),
      has: hasProgress
    };
    if (hasProgress) {
      el.total.textContent = fmt(s.duration);
      tick();
    }
  }

  function tick() {
    if (!play.has) return;
    var pos = play.position;
    if (play.playing) pos += (performance.now() - play.at) / 1000;
    if (play.duration) pos = Math.min(pos, play.duration);
    var pct = play.duration ? (pos / play.duration) * 100 : 0;
    el.fill.style.width = pct.toFixed(2) + "%";
    el.elapsed.textContent = fmt(pos);
  }

  var lastTick = 0;
  function loop(ts) {
    if (ts - lastTick > TICK_MS) { lastTick = ts; tick(); }
    requestAnimationFrame(loop);
  }

  function poll() {
    fetch("/api/state", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(render)
      .catch(function () { play.playing = false; show("offline"); });
  }

  poll();
  setInterval(poll, POLL_MS);
  requestAnimationFrame(loop);
})();
