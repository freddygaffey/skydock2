/**
 * Ground control map: path, predictions, spray, live drone marker, live tail.
 * Expects window.__SKYDOCK = { mid, src, tile_osm, tile_esri }.
 */
(function () {
  const C = window.__SKYDOCK || {};
  const MID = C.mid;
  const SRC = C.src;
  const MAP_MAX_ZOOM = SdMap.MAP_MAX_ZOOM;
  const OSM_NATIVE_MAX_ZOOM = SdMap.OSM_NATIVE_MAX_ZOOM;
  const MAP_FIT_OPTS = { padding: [22, 22], maxZoom: MAP_MAX_ZOOM };

  let map,
    osmTile,
    satTile,
    usingSat = false;
  let layerPath = null,
    layerPred = null,
    layerSpray = null,
    layerDrone = null;
  let _droneStateLabel = "—";
  let _summary = null;

  let liveTimer = null,
    liveByte = 0,
    liveActive = false;
  const LIVE_MS_NORMAL = 2000;
  const LIVE_MS_LOW = 5000;
  let _lowPower = false;
  let _lastPredRefreshMs = 0;
  let _lastSprayRefreshMs = 0;

  function escHtml(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  async function api(path) {
    const sep = path.includes("?") ? "&" : "?";
    const url = path.startsWith("/missions/") ? path + sep + "src=" + encodeURIComponent(SRC) : path;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  function fmtDur(s) {
    if (s < 0) return "0s";
    const m = Math.floor(s / 60),
      sec = Math.round(s % 60);
    return m ? `${m}m ${sec}s` : `${sec}s`;
  }
  function fmtTs(ts) {
    if (!ts) return "";
    return new Date(ts).toISOString().replace("T", " ").slice(0, 23) + "Z";
  }
  function mapTileOpts(extra) {
    return SdMap.mapTileOpts(extra);
  }
  function normalizeStateLabel(v) {
    if (v == null) return "";
    const s = String(v);
    const dot = s.lastIndexOf(".");
    return (dot >= 0 ? s.slice(dot + 1) : s).toUpperCase();
  }
  function inferStateFromEvent(ev) {
    if (!ev) return "";
    return normalizeStateLabel(
      ev.state_to ??
        ev.state ??
        ev.state_from ??
        (ev.drone_state && (ev.drone_state.state ?? ev.drone_state.fsm_state ?? ev.drone_state.mode))
    );
  }
  function inferLatLonFromEvent(ev) {
    if (!ev) return null;
    const ds = ev.drone_state || {};
    const lat = ds.latitude ?? ds.lat ?? ev.lat;
    const lon = ds.longitude ?? ds.lon ?? ev.lon;
    if (lat == null || lon == null) return null;
    const la = +lat,
      lo = +lon;
    if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
    return [la, lo];
  }
  function updateDroneMarker(lat, lon, state, ts) {
    if (!map || lat == null || lon == null) return;
    const st = normalizeStateLabel(state) || _droneStateLabel || "—";
    _droneStateLabel = st;
    if (layerDrone) {
      try {
        map.removeLayer(layerDrone);
      } catch (e) {}
    }
    layerDrone = L.circleMarker([lat, lon], {
      radius: 7,
      color: "#ffe74a",
      fillColor: "#1a5cbf",
      fillOpacity: 0.95,
      weight: 2,
    });
    const when = ts ? `<br><span class="muted">${fmtTs(ts)}</span>` : "";
    layerDrone.bindPopup(`<b>Drone</b><br>State: <b>${escHtml(st)}</b>${when}`);
    layerDrone.addTo(map);
    const line = document.getElementById("gcMapInfo");
    if (line)
      line.textContent = `State: ${st}${_lowPower ? " · Low Power" : ""}${liveActive ? " · Live" : ""}`;
  }
  function lowPowerStorageKey() {
    return `sd-low-power:${SRC}`;
  }
  function getLivePollMs() {
    return _lowPower ? LIVE_MS_LOW : LIVE_MS_NORMAL;
  }
  function applyLowPowerUi() {
    const b = document.getElementById("lowPowerBtn");
    if (!b) return;
    b.textContent = `Low Power: ${_lowPower ? "On" : "Off"}`;
    b.classList.toggle("btn-warning", _lowPower);
    b.classList.toggle("btn-outline-secondary", !_lowPower);
  }
  function restartLivePollIfNeeded() {
    if (!liveActive) return;
    clearInterval(liveTimer);
    liveTimer = setInterval(livePoll, getLivePollMs());
  }
  function setLowPowerMode(v) {
    _lowPower = !!v;
    try {
      localStorage.setItem(lowPowerStorageKey(), _lowPower ? "1" : "0");
    } catch (e) {}
    applyLowPowerUi();
    restartLivePollIfNeeded();
  }

  async function loadMap() {
    const [pathPts, predPts, sprayEvs] = await Promise.all([
      api(`/missions/${MID}/path?stride=2&source=fsm`),
      api(`/missions/${MID}/weeds/pred?dedup=1`),
      api(`/missions/${MID}/spray`),
    ]);
    if (layerPath) map.removeLayer(layerPath);
    const pathCoords = pathPts.filter((p) => p.lat || p.lon).map((p) => [p.lat, p.lon]);
    layerPath = SdMap.pathLayerFsmColored(pathPts, { weight: 2, opacity: 0.65 });
    if (document.getElementById("layerPath").checked) layerPath.addTo(map);

    if (layerPred) map.removeLayer(layerPred);
    layerPred = L.layerGroup(
      predPts.map((p) =>
        L.circleMarker([p.lat, p.lon], {
          radius: 5,
          color: "#4a9eff",
          fillColor: "#4a9eff",
          fillOpacity: 0.5,
          weight: 1.5,
        }).bindPopup(`Weed detected<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`)
      )
    );
    if (document.getElementById("layerPred").checked) layerPred.addTo(map);

    if (layerSpray) map.removeLayer(layerSpray);
    layerSpray = L.layerGroup(SdMap.sprayCircleMarkers(sprayEvs));
    if (document.getElementById("layerSpray").checked) layerSpray.addTo(map);

    const all = [...pathCoords, ...predPts.map((p) => [p.lat, p.lon])].filter((c) => c[0] || c[1]);
    if (all.length) map.fitBounds(L.latLngBounds(all), MAP_FIT_OPTS);
    else map.setView([0, 0], 2);
    if (pathPts && pathPts.length) {
      const lp = pathPts[pathPts.length - 1];
      if (lp && lp.lat != null && lp.lon != null) {
        updateDroneMarker(lp.lat, lp.lon, _droneStateLabel, lp.ts || null);
      }
    }
  }

  async function refreshPredLayer() {
    const predPts = await api(`/missions/${MID}/weeds/pred?dedup=1`);
    if (layerPred) map.removeLayer(layerPred);
    layerPred = L.layerGroup(
      predPts.map((p) =>
        L.circleMarker([p.lat, p.lon], {
          radius: 5,
          color: "#4a9eff",
          fillColor: "#4a9eff",
          fillOpacity: 0.5,
          weight: 1.5,
        }).bindPopup(`Weed detected<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`)
      )
    );
    if (document.getElementById("layerPred")?.checked) layerPred.addTo(map);
    if (_summary) _summary.unique_weeds = predPts.length;
  }

  async function refreshSprayLayer() {
    const sprayEvs = await api(`/missions/${MID}/spray`);
    if (layerSpray) map.removeLayer(layerSpray);
    layerSpray = L.layerGroup(SdMap.sprayCircleMarkers(sprayEvs));
    if (document.getElementById("layerSpray")?.checked) layerSpray.addTo(map);
  }

  async function livePoll() {
    try {
      const data = await api(`/missions/${MID}/tail?since_byte=${liveByte}`);
      if (!data.events.length) return;
      liveByte = data.next_byte;
      let latestPos = null;
      for (const ev of data.events) {
        const ll = inferLatLonFromEvent(ev);
        const st = inferStateFromEvent(ev);
        if (st) _droneStateLabel = st;
        if (ll) latestPos = { ll, st, ts: ev.ts || null };
      }
      if (latestPos) {
        updateDroneMarker(latestPos.ll[0], latestPos.ll[1], latestPos.st || _droneStateLabel, latestPos.ts);
      }
      if (_summary) {
        for (const ev of data.events) {
          const t = ev.event;
          _summary.event_counts[t] = (_summary.event_counts[t] || 0) + 1;
          if (t === "weed_detected") _summary.weed_detections++;
        }

        const now = Date.now();
        const anyWeedDetected = data.events.some((e) => e.event === "weed_detected");
        const anySprayEvent = data.events.some(
          (e) =>
            e.event === "db_weed_sprayed" ||
            e.event === "spray_attempt" ||
            e.event === "spray_miss"
        );

        // Low power throttles expensive refetches, but we still update overlays
        // so users don't need to reload the page.
        const predMinMs = _lowPower ? 20000 : 5000;
        const sprayMinMs = _lowPower ? 20000 : 5000;

        if (anyWeedDetected && now - _lastPredRefreshMs >= predMinMs) {
          _lastPredRefreshMs = now;
          try {
            await refreshPredLayer();
          } catch (e) {
            console.warn("GC refreshPredLayer failed:", e);
          }
        }

        if (anySprayEvent && now - _lastSprayRefreshMs >= sprayMinMs) {
          _lastSprayRefreshMs = now;
          try {
            await refreshSprayLayer();
          } catch (e) {
            console.warn("GC refreshSprayLayer failed:", e);
          }
        }

        const el = document.getElementById("gcSummaryBar");
        if (el) {
          const { duration_s, weed_detections, unique_weeds, spray_events, header } = _summary;
          el.innerHTML = `
            <span class="stat-pill">Duration <span class="val">${fmtDur(duration_s)}</span></span>
            <span class="stat-pill">Weed events <span class="val">${weed_detections}</span></span>
            <span class="stat-pill">Unique weeds <span class="val">${unique_weeds}</span></span>
            <span class="stat-pill">Spray <span class="val">${spray_events}</span></span>
            <span class="stat-pill">${header.is_sim ? '<span style="color:#ff9a4a">SIM</span>' : '<span style="color:#4adf86">REAL</span>'}</span>`;
        }
      }
    } catch (e) {
      console.warn("live poll:", e);
    }
  }

  function initMap() {
    map = L.map("map", { maxZoom: MAP_MAX_ZOOM, preferCanvas: true });
    if (typeof L.DomEvent !== "undefined" && L.DomEvent.disableScrollPropagation) {
      L.DomEvent.disableScrollPropagation(map.getContainer());
    }
    SdMap.keepMapSized(map);
    SdMap.ensureDetectionUnderlay(map);
    osmTile = L.tileLayer(C.tile_osm, mapTileOpts({ maxNativeZoom: OSM_NATIVE_MAX_ZOOM, attribution: "© OpenStreetMap contributors" }));
    satTile = L.tileLayer(C.tile_esri, mapTileOpts({ attribution: "Tiles © Esri" }));
    osmTile.addTo(map);
    document.getElementById("tileToggle").addEventListener("click", () => {
      if (usingSat) {
        map.removeLayer(satTile);
        osmTile.addTo(map);
        usingSat = false;
      } else {
        map.removeLayer(osmTile);
        satTile.addTo(map);
        usingSat = true;
      }
    });
    for (const id of ["layerPath", "layerPred", "layerSpray"]) {
      document.getElementById(id).addEventListener("change", (e) => {
        const lyr = { layerPath, layerPred, layerSpray }[id];
        if (!lyr) return;
        e.target.checked ? lyr.addTo(map) : map.removeLayer(lyr);
      });
    }
    document.getElementById("liveBtn").addEventListener("click", async () => {
      liveActive = !liveActive;
      const btn = document.getElementById("liveBtn");
      const badge = document.getElementById("liveBadge");
      if (liveActive) {
        try {
          const d = await api(`/missions/${MID}/tail?since_byte=9999999999`);
          liveByte = d.file_size;
        } catch (e) {
          liveByte = 0;
        }
        liveTimer = setInterval(livePoll, getLivePollMs());
        btn.className = "btn btn-sm btn-danger";
        btn.textContent = "■ Stop Live";
        badge.classList.remove("d-none");
      } else {
        clearInterval(liveTimer);
        btn.className = "btn btn-sm btn-outline-danger";
        btn.innerHTML = "&#9679; Live";
        badge.classList.add("d-none");
      }
      const line = document.getElementById("gcMapInfo");
      if (line) line.textContent = `State: ${_droneStateLabel}${_lowPower ? " · Low Power" : ""}${liveActive ? " · Live" : ""}`;
    });
    SdMap.attachMapDetectionPopupPainter(map);
  }

  async function bootstrap() {
    try {
      _lowPower = localStorage.getItem(lowPowerStorageKey()) === "1";
    } catch (e) {
      _lowPower = false;
    }
    applyLowPowerUi();
    document.getElementById("lowPowerBtn").addEventListener("click", () => setLowPowerMode(!_lowPower));

    try {
      _summary = await api(`/missions/${MID}/summary`);
      const el = document.getElementById("gcSummaryBar");
      if (el && _summary) {
        const { duration_s, weed_detections, unique_weeds, spray_events, header } = _summary;
        el.innerHTML = `
          <span class="stat-pill">Duration <span class="val">${fmtDur(duration_s)}</span></span>
          <span class="stat-pill">Weed events <span class="val">${weed_detections}</span></span>
          <span class="stat-pill">Unique weeds <span class="val">${unique_weeds}</span></span>
          <span class="stat-pill">Spray <span class="val">${spray_events}</span></span>
          <span class="stat-pill">${header.is_sim ? '<span style="color:#ff9a4a">SIM</span>' : '<span style="color:#4adf86">REAL</span>'}</span>`;
      }
    } catch (e) {
      console.warn(e);
    }

    try {
      const tline = await api(`/missions/${MID}/timeline`);
      const segs = (tline && tline.segments) || [];
      if (segs.length) {
        _droneStateLabel = normalizeStateLabel(segs[segs.length - 1].state) || _droneStateLabel;
      }
    } catch (e) {}

    initMap();
    try {
      await loadMap();
    } catch (e) {
      console.warn(e);
    }
    if (layerDrone && layerDrone.getLatLng) {
      const ll = layerDrone.getLatLng();
      updateDroneMarker(ll.lat, ll.lng, _droneStateLabel, null);
    }
  }

  bootstrap();
})();
