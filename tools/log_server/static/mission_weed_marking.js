/**
 * Weed marking page: map + real_missions setup JSON (sv.json shape). No log-analysis UI.
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
  let layerSetupWeeds = null,
    layerSetupScan = null,
    layerSetupScanMarkers = null;
  let _droneStateLabel = "—";
  let _setupDraft = { field_center: null, weed_locations: [], scan_path: [] };
  let _setupTarget = "real";
  let _scanEditMode = false;
  let _scanInsertMode = false;
  let _selectedWaypoint = -1;
  let _clickAddWeedMode = false;

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
    layerDrone.bindPopup(`<b>Drone position</b><br>State: <b>${escHtml(st)}</b>${when}`);
    layerDrone.addTo(map);
  }
  async function ensureDroneMarkerFromLatestPath() {
    if (layerDrone && layerDrone.getLatLng) return true;
    try {
      const pts = await api(`/missions/${MID}/path?stride=1&source=fsm`);
      if (pts && pts.length) {
        const lp = pts[pts.length - 1];
        if (lp && lp.lat != null && lp.lon != null) {
          updateDroneMarker(lp.lat, lp.lon, _droneStateLabel, lp.ts || null);
          return true;
        }
      }
    } catch (e) {}
    return !!(layerDrone && layerDrone.getLatLng);
  }
  function setupStatus(msg) {
    const el = document.getElementById("setupStatus");
    if (el) el.textContent = msg;
  }
  function setupTarget() {
    const sel = document.getElementById("setupTargetSel");
    const v = (sel && sel.value) || _setupTarget || "real";
    return v === "sim" ? "sim" : "real";
  }
  function setupTargetStorageKey() {
    return "sd-setup-target";
  }
  function setupDefaultName() {
    const d = new Date();
    const z = (n) => String(n).padStart(2, "0");
    return `field_${d.getUTCFullYear()}-${z(d.getUTCMonth() + 1)}-${z(d.getUTCDate())}.json`;
  }
  function jumpMapTo(lat, lon) {
    if (!map) return false;
    const la = +lat;
    const lo = +lon;
    if (!Number.isFinite(la) || !Number.isFinite(lo)) {
      setupStatus("Invalid lat/lon.");
      return false;
    }
    if (la < -90 || la > 90 || lo < -180 || lo > 180) {
      setupStatus("Lat/lon out of range.");
      return false;
    }
    const z = Math.min(MAP_MAX_ZOOM, Math.max(map.getZoom(), 17));
    map.setView([la, lo], z, { animate: true });
    return true;
  }
  function fitAllWeedsOnMap() {
    if (!map) return false;
    const weeds = _setupDraft.weed_locations || [];
    const pts = weeds
      .map((w) => [+w.lat, +w.lon])
      .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    if (!pts.length) {
      setupStatus("No weeds yet.");
      return false;
    }
    const b = L.latLngBounds(pts);
    map.fitBounds(b, { padding: [36, 36], maxZoom: MAP_MAX_ZOOM });
    return true;
  }
  function refreshJumpWeedSelect() {
    const sel = document.getElementById("setupJumpWeedSel");
    if (!sel) return;
    const weeds = _setupDraft.weed_locations || [];
    const prev = sel.value;
    sel.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = weeds.length ? "Select weed…" : "(no weeds yet)";
    sel.appendChild(opt0);
    weeds.forEach((w, i) => {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = `#${i}  ${(+w.lat).toFixed(5)}, ${(+w.lon).toFixed(5)}`;
      sel.appendChild(o);
    });
    if (prev !== "" && weeds[+prev] !== undefined) sel.value = prev;
  }
  function setupRenderOverlays() {
    if (!map) return;
    if (layerSetupWeeds) {
      try {
        map.removeLayer(layerSetupWeeds);
      } catch (e) {}
    }
    if (layerSetupScan) {
      try {
        map.removeLayer(layerSetupScan);
      } catch (e) {}
    }
    if (layerSetupScanMarkers) {
      try {
        map.removeLayer(layerSetupScanMarkers);
      } catch (e) {}
    }
    const weeds = _setupDraft.weed_locations || [];
    layerSetupWeeds = L.layerGroup(
      weeds.map((w, i) =>
        L.circleMarker([w.lat, w.lon], {
          radius: 6,
          color: "#ffffff",
          fillColor: "#ffffff",
          fillOpacity: 0.9,
          weight: 1.5,
        }).bindPopup(`Truth weed #${w.id ?? i}<br>${w.lat.toFixed(6)}, ${w.lon.toFixed(6)}`)
      )
    );
    const scan = _setupDraft.scan_path || [];
    layerSetupScan = L.layerGroup(
      scan.length > 1 ? [L.polyline(scan, { color: "#ffe74a", weight: 2, opacity: 0.85 })] : []
    );
    layerSetupScanMarkers = L.layerGroup(
      scan.map((p, i) => {
        const sel = i === _selectedWaypoint;
        return L.circleMarker([p[0], p[1]], {
          radius: sel ? 7 : (_scanEditMode ? 6 : 4),
          color: sel ? "#4adf86" : (_scanEditMode ? "#ff9a4a" : "#9fb0c7"),
          fillColor: sel ? "#4adf86" : (_scanEditMode ? "#ff9a4a" : "#9fb0c7"),
          fillOpacity: 0.95,
          weight: sel ? 2 : 1,
        }).bindTooltip(`#${i}`, { permanent: false, direction: "top" });
      })
    );
    if (_scanEditMode) {
      // Draggable handles while editing scan path.
      layerSetupScanMarkers = L.layerGroup(
        scan.map((p, i) => {
          const m = L.marker([p[0], p[1]], { draggable: true, title: `Waypoint ${i}` });
          m.on("click", () => {
            _selectedWaypoint = i;
            setupRenderOverlays();
          });
          m.on("dragend", (ev) => {
            const ll = ev.target.getLatLng();
            _setupDraft.scan_path[i] = [ll.lat, ll.lng];
            _selectedWaypoint = i;
            setupRenderOverlays();
          });
          m.bindTooltip(`#${i}`, { permanent: false, direction: "top" });
          return m;
        })
      );
    }
    layerSetupWeeds.addTo(map);
    layerSetupScan.addTo(map);
    layerSetupScanMarkers.addTo(map);
    refreshJumpWeedSelect();
    const selTxt = _selectedWaypoint >= 0 ? ` · selected #${_selectedWaypoint}` : "";
    setupStatus(`${weeds.length} weed point(s), ${scan.length} scan waypoint(s)${selTxt}.`);
  }
  function setScanEditMode(v) {
    _scanEditMode = !!v;
    const b = document.getElementById("setupEditPathBtn");
    if (b) b.textContent = `Edit: ${_scanEditMode ? "On" : "Off"}`;
    if (!_scanEditMode) {
      _scanInsertMode = false;
      const ib = document.getElementById("setupInsertPathBtn");
      if (ib) ib.textContent = "Insert: Off";
    }
    setupRenderOverlays();
  }
  function setScanInsertMode(v) {
    _scanInsertMode = !!v;
    const b = document.getElementById("setupInsertPathBtn");
    if (b) b.textContent = `Insert: ${_scanInsertMode ? "On" : "Off"}`;
    if (_scanInsertMode && !_scanEditMode) setScanEditMode(true);
  }
  function addScanWaypoint(lat, lon) {
    const sp = _setupDraft.scan_path || [];
    sp.push([+lat, +lon]);
    _setupDraft.scan_path = sp;
    _selectedWaypoint = sp.length - 1;
    setupRenderOverlays();
  }
  function insertScanWaypointNearSegment(lat, lon) {
    const sp = _setupDraft.scan_path || [];
    if (sp.length < 2) {
      addScanWaypoint(lat, lon);
      return;
    }
    function dist2(a, b) {
      const dx = a[0] - b[0], dy = a[1] - b[1];
      return dx * dx + dy * dy;
    }
    let bestIdx = sp.length;
    let best = Infinity;
    const p = [lat, lon];
    for (let i = 0; i < sp.length - 1; i++) {
      const mid = [(sp[i][0] + sp[i + 1][0]) * 0.5, (sp[i][1] + sp[i + 1][1]) * 0.5];
      const d = dist2(p, mid);
      if (d < best) {
        best = d;
        bestIdx = i + 1;
      }
    }
    sp.splice(bestIdx, 0, [lat, lon]);
    _selectedWaypoint = bestIdx;
    _setupDraft.scan_path = sp;
    setupRenderOverlays();
  }
  function deleteSelectedWaypoint() {
    const sp = _setupDraft.scan_path || [];
    if (_selectedWaypoint < 0 || _selectedWaypoint >= sp.length) return;
    sp.splice(_selectedWaypoint, 1);
    if (_selectedWaypoint >= sp.length) _selectedWaypoint = sp.length - 1;
    _setupDraft.scan_path = sp;
    setupRenderOverlays();
  }
  function addWeedAt(lat, lon) {
    const la = +lat;
    const lo = +lon;
    if (!Number.isFinite(la) || !Number.isFinite(lo)) {
      setupStatus("Invalid lat/lon.");
      return false;
    }
    if (la < -90 || la > 90 || lo < -180 || lo > 180) {
      setupStatus("Lat/lon out of range.");
      return false;
    }
    const ws = _setupDraft.weed_locations || [];
    ws.push({ id: ws.length, lat: la, lon: lo });
    _setupDraft.weed_locations = ws;
    setupReindexWeeds();
    setupFieldCenterFromWeeds();
    setupRenderOverlays();
    return true;
  }
  function setClickAddWeedMode(v) {
    _clickAddWeedMode = !!v;
    const b = document.getElementById("setupClickWeedBtn");
    if (b) b.textContent = `Click map: ${_clickAddWeedMode ? "On" : "Off"}`;
    if (map && map.getContainer) {
      map.getContainer().classList.toggle("weed-click-add", _clickAddWeedMode);
    }
    if (_clickAddWeedMode && _scanEditMode) {
      setupStatus("Path Edit is on — map clicks edit the scan path. Turn Edit off to add weeds by clicking.");
    }
  }
  function setupReindexWeeds() {
    (_setupDraft.weed_locations || []).forEach((w, i) => {
      w.id = i;
    });
  }
  function setupFieldCenterFromWeeds() {
    const ws = _setupDraft.weed_locations || [];
    if (!ws.length) {
      _setupDraft.field_center = null;
      return;
    }
    const lat = ws.reduce((a, w) => a + (+w.lat || 0), 0) / ws.length;
    const lon = ws.reduce((a, w) => a + (+w.lon || 0), 0) / ws.length;
    _setupDraft.field_center = [lat, lon];
  }
  function setupPayloadForSave() {
    setupReindexWeeds();
    setupFieldCenterFromWeeds();
    return {
      field_center: _setupDraft.field_center || [0, 0],
      weed_locations: (_setupDraft.weed_locations || []).map((w) => ({ id: w.id, lat: +w.lat, lon: +w.lon })),
      scan_path: (_setupDraft.scan_path || []).map((p) => [+p[0], +p[1]]),
    };
  }
  async function setupLoadFileList() {
    try {
      const tgt = setupTarget();
      const r = await api(`/setup_files?target=${encodeURIComponent(tgt)}`);
      const sel = document.getElementById("setupLoadSel");
      if (!sel) return;
      sel.innerHTML = '<option value="">Load setup…</option>';
      (r.files || []).forEach((n) => {
        const o = document.createElement("option");
        o.value = n;
        o.textContent = n;
        sel.appendChild(o);
      });
    } catch (e) {
      console.warn(e);
    }
  }

  async function loadMap() {
    const [pathPts, predPts, sprayEvs] = await Promise.all([
      api(`/missions/${MID}/path?stride=1&source=fsm`),
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

  function initMap() {
    map = L.map("map", { maxZoom: MAP_MAX_ZOOM, preferCanvas: true });
    if (typeof L.DomEvent !== "undefined" && L.DomEvent.disableScrollPropagation) {
      L.DomEvent.disableScrollPropagation(map.getContainer());
    }
    SdMap.ensureDetectionUnderlay(map);
    osmTile = L.tileLayer(C.tile_osm, mapTileOpts({ maxNativeZoom: OSM_NATIVE_MAX_ZOOM, attribution: "© OpenStreetMap contributors" }));
    satTile = L.tileLayer(C.tile_esri, mapTileOpts({ attribution: "Tiles © Esri" }));
    osmTile.addTo(map);

    // Map control: fit all marked truth weeds.
    const fitCtrl = L.control({ position: "topleft" });
    fitCtrl.onAdd = () => {
      const div = L.DomUtil.create("div", "leaflet-bar");
      div.style.background = "var(--sd-input, rgba(0,0,0,0.15))";
      div.style.border = "1px solid var(--sd-border, #1b2a46)";
      div.style.borderRadius = "6px";
      const a = L.DomUtil.create("a", "", div);
      a.href = "#";
      a.innerHTML = "Fit";
      a.style.fontSize = "12px";
      a.style.lineHeight = "26px";
      a.style.padding = "0 10px";
      a.style.color = "var(--sd-text, #dbe7f5)";
      a.onclick = (e) => {
        if (e && e.preventDefault) e.preventDefault();
        if (e && e.stopPropagation) e.stopPropagation();
        fitAllWeedsOnMap();
      };
      return div;
    };
    fitCtrl.addTo(map);

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

    const clickWeedBtn = document.getElementById("setupClickWeedBtn");
    if (clickWeedBtn) clickWeedBtn.addEventListener("click", () => setClickAddWeedMode(!_clickAddWeedMode));

    document.getElementById("setupMarkDroneBtn").addEventListener("click", async () => {
      const ok = await ensureDroneMarkerFromLatestPath();
      if (!ok || !layerDrone || !layerDrone.getLatLng) {
        setupStatus("Drone position is not available yet.");
        return;
      }
      const ll = layerDrone.getLatLng();
      addWeedAt(ll.lat, ll.lng);
    });
    const addCoordsBtn = document.getElementById("setupAddWeedCoordsBtn");
    if (addCoordsBtn) {
      addCoordsBtn.addEventListener("click", () => {
        const latIn = document.getElementById("setupWeedLat");
        const lonIn = document.getElementById("setupWeedLon");
        const lat = latIn && latIn.value != null ? String(latIn.value).trim() : "";
        const lon = lonIn && lonIn.value != null ? String(lonIn.value).trim() : "";
        if (!lat || !lon) {
          setupStatus("Enter latitude and longitude.");
          return;
        }
        addWeedAt(lat, lon);
      });
    }
    const jumpCoordsBtn = document.getElementById("setupJumpCoordsBtn");
    if (jumpCoordsBtn) {
      jumpCoordsBtn.addEventListener("click", () => {
        const latIn = document.getElementById("setupWeedLat");
        const lonIn = document.getElementById("setupWeedLon");
        const lat = latIn && latIn.value != null ? String(latIn.value).trim() : "";
        const lon = lonIn && lonIn.value != null ? String(lonIn.value).trim() : "";
        if (!lat || !lon) {
          setupStatus("Enter latitude and longitude to jump.");
          return;
        }
        if (jumpMapTo(lat, lon)) setupStatus(`Map centered on ${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`);
      });
    }
    const jumpWeedBtn = document.getElementById("setupJumpWeedBtn");
    const jumpWeedSel = document.getElementById("setupJumpWeedSel");
    function jumpToSelectedWeed() {
      if (!jumpWeedSel) return;
      const idx = jumpWeedSel.value;
      if (idx === "" || idx == null) {
        setupStatus("Select a weed from the list.");
        return;
      }
      const w = (_setupDraft.weed_locations || [])[+idx];
      if (!w) {
        setupStatus("Weed not found.");
        return;
      }
      if (jumpMapTo(w.lat, w.lon)) setupStatus(`Jumped to weed #${idx}`);
    }
    if (jumpWeedBtn) jumpWeedBtn.addEventListener("click", jumpToSelectedWeed);
    if (jumpWeedSel) {
      jumpWeedSel.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          jumpToSelectedWeed();
        }
      });
    }
    document.getElementById("setupUndoBtn").addEventListener("click", () => {
      if (!_setupDraft.weed_locations.length) return;
      _setupDraft.weed_locations.pop();
      setupReindexWeeds();
      setupFieldCenterFromWeeds();
      setupRenderOverlays();
    });
    document.getElementById("setupClearBtn").addEventListener("click", () => {
      _setupDraft = { field_center: null, weed_locations: [], scan_path: [] };
      setupRenderOverlays();
    });
    document.getElementById("setupGenPathBtn").addEventListener("click", async () => {
      try {
        const payload = setupPayloadForSave();
        const r = await fetch(`/setup_scan_path?src=${encodeURIComponent(SRC)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ weed_locations: payload.weed_locations }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "path generation failed");
        _setupDraft.scan_path = d.scan_path || [];
      } catch (err) {
        setupStatus(`Path generation failed: ${err}`);
        return;
      }
      setupRenderOverlays();
    });
    document.getElementById("setupSaveBtn").addEventListener("click", async () => {
      const inp = document.getElementById("setupNameInput");
      let name = ((inp && inp.value) || "").trim();
      if (!name) name = setupDefaultName();
      if (!name.endsWith(".json")) name += ".json";
      const tgt = setupTarget();
      const payload = setupPayloadForSave();
      try {
        const r = await fetch(`/setup_file?src=${encodeURIComponent(SRC)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, payload, target: tgt }),
        });
        const d = await r.json();
        if (!r.ok || !d.ok) throw new Error((d && d.error) || "save failed");
        if (inp) inp.value = d.name || name;
        await setupLoadFileList();
        setupStatus(`Saved ${tgt} setup: ${d.name || name}`);
      } catch (e) {
        setupStatus(`Save failed: ${e}`);
      }
    });
    document.getElementById("setupLoadSel").addEventListener("change", async () => {
      const sel = document.getElementById("setupLoadSel");
      const name = sel.value;
      if (!name) return;
      try {
        const tgt = setupTarget();
        const d = await api(`/setup_file?name=${encodeURIComponent(name)}&target=${encodeURIComponent(tgt)}`);
        _setupDraft = d.payload || { field_center: null, weed_locations: [], scan_path: [] };
        setupReindexWeeds();
        setupRenderOverlays();
        const inp = document.getElementById("setupNameInput");
        if (inp) inp.value = name;
        setupStatus(`Loaded ${tgt} setup: ${name}`);
      } catch (e) {
        setupStatus(`Load failed: ${e}`);
      }
    });
    const editBtn = document.getElementById("setupEditPathBtn");
    if (editBtn) editBtn.addEventListener("click", () => {
      setScanEditMode(!_scanEditMode);
      if (_scanEditMode && _clickAddWeedMode) {
        setupStatus("Path Edit on — map clicks edit the scan path. Turn Edit off to add weeds by map click.");
      }
    });
    const insertBtn = document.getElementById("setupInsertPathBtn");
    if (insertBtn) insertBtn.addEventListener("click", () => setScanInsertMode(!_scanInsertMode));
    const addDroneBtn = document.getElementById("setupAddPathDroneBtn");
    if (addDroneBtn) addDroneBtn.addEventListener("click", async () => {
      const ok = await ensureDroneMarkerFromLatestPath();
      if (!ok || !layerDrone || !layerDrone.getLatLng) {
        setupStatus("Drone position is not available yet.");
        return;
      }
      const ll = layerDrone.getLatLng();
      addScanWaypoint(ll.lat, ll.lng);
    });
    const undoPathBtn = document.getElementById("setupUndoPathBtn");
    if (undoPathBtn) undoPathBtn.addEventListener("click", () => {
      if (!(_setupDraft.scan_path || []).length) return;
      _setupDraft.scan_path.pop();
      if (_selectedWaypoint >= _setupDraft.scan_path.length) _selectedWaypoint = _setupDraft.scan_path.length - 1;
      setupRenderOverlays();
    });
    const delPathBtn = document.getElementById("setupDeletePathBtn");
    if (delPathBtn) delPathBtn.addEventListener("click", () => deleteSelectedWaypoint());
    const revPathBtn = document.getElementById("setupReversePathBtn");
    if (revPathBtn) revPathBtn.addEventListener("click", () => {
      _setupDraft.scan_path = (_setupDraft.scan_path || []).slice().reverse();
      if (_selectedWaypoint >= 0) _selectedWaypoint = _setupDraft.scan_path.length - 1 - _selectedWaypoint;
      setupRenderOverlays();
    });
    const clearPathBtn = document.getElementById("setupClearPathBtn");
    if (clearPathBtn) clearPathBtn.addEventListener("click", () => {
      _setupDraft.scan_path = [];
      _selectedWaypoint = -1;
      setupRenderOverlays();
    });
    map.on("click", (e) => {
      if (_scanEditMode) {
        if (_scanInsertMode) insertScanWaypointNearSegment(e.latlng.lat, e.latlng.lng);
        else addScanWaypoint(e.latlng.lat, e.latlng.lng);
        return;
      }
      if (_clickAddWeedMode) {
        addWeedAt(e.latlng.lat, e.latlng.lng);
      }
    });
    document.addEventListener("keydown", (e) => {
      if (!_scanEditMode || _selectedWaypoint < 0) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      const sp = _setupDraft.scan_path || [];
      if (_selectedWaypoint >= sp.length) return;
      const step = e.shiftKey ? 0.00002 : 0.000005;
      let moved = false;
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        deleteSelectedWaypoint();
        return;
      }
      if (e.key === "ArrowUp") { sp[_selectedWaypoint][0] += step; moved = true; }
      else if (e.key === "ArrowDown") { sp[_selectedWaypoint][0] -= step; moved = true; }
      else if (e.key === "ArrowRight") { sp[_selectedWaypoint][1] += step; moved = true; }
      else if (e.key === "ArrowLeft") { sp[_selectedWaypoint][1] -= step; moved = true; }
      if (moved) {
        e.preventDefault();
        _setupDraft.scan_path = sp;
        setupRenderOverlays();
      }
    });
    const targetSel = document.getElementById("setupTargetSel");
    if (targetSel) {
      try {
        const savedTarget = localStorage.getItem(setupTargetStorageKey());
        if (savedTarget === "sim" || savedTarget === "real") {
          targetSel.value = savedTarget;
          _setupTarget = savedTarget;
        }
      } catch (e) {}
      targetSel.addEventListener("change", async () => {
        _setupTarget = setupTarget();
        try {
          localStorage.setItem(setupTargetStorageKey(), _setupTarget);
        } catch (e) {}
        await setupLoadFileList();
        setupStatus(`Target: ${_setupTarget} setup files`);
      });
    }
    setupLoadFileList().catch(console.warn);
    const nameInp = document.getElementById("setupNameInput");
    if (nameInp && !nameInp.value) nameInp.value = setupDefaultName();
    SdMap.attachMapDetectionPopupPainter(map);
  }

  async function bootstrap() {
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
    setupRenderOverlays();
    const refit = () => {
      try {
        map.invalidateSize();
      } catch (e) {}
    };
    setTimeout(refit, 50);
    setTimeout(refit, 300);
    window.addEventListener("resize", refit);
  }

  bootstrap();
})();
