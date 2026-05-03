/**
 * Shared map utilities for mission dashboard and compare pages (Leaflet).
 * Depends on global L (Leaflet 1.x).
 */
(function (global) {
  var TILE_ERROR_B64 =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

  /** Escape for HTML double-quoted attributes (alt, title). */
  function escAttr(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  var SdMap = {
    /** Ground detection footprints (bbox on map, frame review detections). Above FOV and default overlay (path/pred). */
    DETECTION_PANE: "detectionUnderlay",
    DETECTION_PANE_Z: 630,
    /** Camera FOV quads from <code>/camera_fov_footprints</code> — below ground detection pane so bbox stays on top. */
    FOV_GROUND_PANE: "fovGroundPane",
    FOV_GROUND_PANE_Z: 560,

    /** No center dot when corners draw a polygon; tiny hit-target when only center exists (popup). */
    CENTER_ONLY_RADIUS: 2,
    CENTER_ONLY_OPACITY: 0.35,

    /** Leaflet map zoom ceiling (satellite oversamples beyond native tile resolution). */
    MAP_MAX_ZOOM: 30,
    /**
     * Esri World Imagery: max zoom level to *request* from the service. Above this, Esri often
     * returns valid JPEGs that are gray “Map data not yet available” tiles (varies by place).
     * Map zoom can still go to MAP_MAX_ZOOM; Leaflet upscales the last good zoom level.
     * If you still see gray tiles at z18, lower this to 17.
     */
    ESRI_NATIVE_MAX_ZOOM: 18,
    /** OSM raster tiles only exist through this z. */
    OSM_NATIVE_MAX_ZOOM: 19,
    TILE_ERROR_URL: "data:image/png;base64," + TILE_ERROR_B64,

    /** Camera FOV on ground (<code>frame_footprint</code>) — matches Frame Review yellow. */
    CAMERA_FRAME_COLOR: "#ffe74a",
    /** FSM mode colors (aligned with timeline / compare state colors). Unknown modes fall back to <code>CAMERA_FRAME_COLOR</code>. */
    FOV_STATE_COLORS: {
      SCAN: "#4a9eff",
      GOTO: "#bf4aff",
      HOMING: "#ff9a4a",
      SPRAY: "#4adf86",
      RTL: "#ff4a4a",
      OVERRIDE: "#9fb0c7",
      DONE: "#6b8899",
      LAND: "#ff6b6b",
    },

    /** Normalize log values like <code>DroneStateEnum.SCAN</code> to <code>SCAN</code>. */
    normalizeFsmStateKey: function (raw) {
      if (raw == null || raw === "") return null;
      var s = String(raw).trim();
      var i = s.lastIndexOf(".");
      if (i >= 0) s = s.slice(i + 1);
      return s.toUpperCase() || null;
    },

    /** Stroke/fill color for a camera FOV polygon from <code>row.state</code>. */
    fovColorForState: function (state) {
      var k = this.normalizeFsmStateKey(state);
      if (!k) return this.CAMERA_FRAME_COLOR;
      return this.FOV_STATE_COLORS[k] || this.CAMERA_FRAME_COLOR;
    },

    /**
     * Extra popup HTML for camera FOV quads: link to open the nearest saved JPEG in the Frames tab.
     * Requires <code>cfg.fovFrameViewer.missionId</code> and <code>row.time_ns</code> from the API.
     */
    fovPopupAppendFrameLink: function (cfg, timeNs) {
      var fvv = cfg && cfg.fovFrameViewer;
      if (!fvv || !fvv.missionId) return "";
      if (timeNs == null || timeNs === "") return "";
      var ns = Number(timeNs);
      if (!Number.isFinite(ns)) return "";
      return (
        '<div class="mt-2 pt-2" style="font-size:11px;border-top:1px solid rgba(140,160,190,.35)">' +
        '<a class="sd-fov-open-frame" href="#" data-time-ns="' +
        String(Math.round(ns)) +
        '">Open nearest frame (annotated)</a>' +
        '<div class="muted mt-1" style="font-size:10px;line-height:1.35">Uses this fsm_tick’s <code>time_ns</code> vs <code>frames/*.jpg</code> stems.</div>' +
        "</div>"
      );
    },

    /** Drone path polyline stroke: FSM segment colors; default blue when state missing (older logs). */
    pathStrokeForFsmState: function (state) {
      var k = this.normalizeFsmStateKey(state);
      if (!k) return "#4a9eff";
      return this.FOV_STATE_COLORS[k] || "#4a9eff";
    },

    /**
     * Path as a LayerGroup of polylines, colored by <code>state</code> per segment (matches FOV / timeline).
     * @param {Array<{lat:number,lon:number,state?:string}>} pathPts — from <code>/path?source=fsm</code>
     * @param {{pane?:string,weight?:number,opacity?:number}} [opts]
     * @returns {L.LayerGroup}
     */
    pathLayerFsmColored: function (pathPts, opts) {
      opts = opts || {};
      var pane = opts.pane;
      var w = opts.weight != null ? opts.weight : 2;
      var op = opts.opacity != null ? opts.opacity : 0.65;
      var pts = (pathPts || []).filter(function (p) {
        return p && (p.lat || p.lon);
      });
      if (!pts.length) return L.layerGroup([]);
      var layers = [];
      var seg = [[pts[0].lat, pts[0].lon]];
      var segState = pts[0].state;
      for (var i = 1; i < pts.length; i++) {
        var k = this.normalizeFsmStateKey(pts[i].state);
        var kSeg = this.normalizeFsmStateKey(segState);
        if (k !== kSeg) {
          layers.push(
            L.polyline(seg, {
              color: this.pathStrokeForFsmState(segState),
              weight: w,
              opacity: op,
              pane: pane,
            })
          );
          seg = [
            [pts[i - 1].lat, pts[i - 1].lon],
            [pts[i].lat, pts[i].lon],
          ];
          segState = pts[i].state;
        } else {
          seg.push([pts[i].lat, pts[i].lon]);
        }
      }
      layers.push(
        L.polyline(seg, {
          color: this.pathStrokeForFsmState(segState),
          weight: w,
          opacity: op,
          pane: pane,
        })
      );
      return L.layerGroup(layers);
    },

    /**
     * Convex hull of lat/lon points (small-field approximation: local equirectangular plane).
     * @param {Array<[number,number]>} latLonPts — [lat, lon]
     * @returns {Array<[number,number]>} closed ring (first point not repeated at end)
     */
    convexHullLatLonRing: function (latLonPts) {
      var n = (latLonPts || []).length;
      if (n < 3) return [];
      var sumLat = 0,
        sumLon = 0;
      for (var i = 0; i < n; i++) {
        sumLat += latLonPts[i][0];
        sumLon += latLonPts[i][1];
      }
      var refLat = sumLat / n;
      var refLon = sumLon / n;
      var cos = Math.cos((refLat * Math.PI) / 180);
      var toXY = function (p) {
        var x = (p[1] - refLon) * cos * 111320;
        var y = (p[0] - refLat) * 110540;
        return [x, y];
      };
      var toLL = function (xy) {
        var lat = refLat + xy[1] / 110540;
        var lon = refLon + xy[0] / (cos * 111320);
        return [lat, lon];
      };
      var pts = [];
      for (var j = 0; j < n; j++) pts.push(toXY(latLonPts[j]));
      pts.sort(function (a, b) {
        return a[0] - b[0] || a[1] - b[1];
      });
      function cross(o, a, b) {
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
      }
      var lower = [];
      for (var k = 0; k < pts.length; k++) {
        while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], pts[k]) <= 0) lower.pop();
        lower.push(pts[k]);
      }
      var upper = [];
      for (var m = pts.length - 1; m >= 0; m--) {
        while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], pts[m]) <= 0) upper.pop();
        upper.push(pts[m]);
      }
      upper.pop();
      lower.pop();
      var hull = lower.concat(upper);
      if (hull.length < 3) return [];
      return hull.map(toLL);
    },

    BBOX_GROUND_STROKE: "#ff9800",

    /** [[x,y],[x,y]] or [x0,y0,x1,y1] from JSON; null if unusable. */
    normalizeBboxPx: function (bx) {
      if (!bx || bx.length < 2) return null;
      var a0 = bx[0];
      var a1 = bx[1];
      if (Array.isArray(a0) && Array.isArray(a1) && a0.length >= 2 && a1.length >= 2) {
        return [
          [Number(a0[0]), Number(a0[1])],
          [Number(a1[0]), Number(a1[1])],
        ];
      }
      if (bx.length >= 4 && typeof a0 !== "object") {
        return [
          [Number(bx[0]), Number(bx[1])],
          [Number(bx[2]), Number(bx[3])],
        ];
      }
      return null;
    },

    /**
     * Draw bbox (fill + stroke) on a transparent canvas over the popup image — no text on the image;
     * class/confidence stay in the popup header only.
     * Uses the same pixel bbox → screen mapping as the Frames tab.
     */
    drawPopupDetectionOverlay: function (img, canvas, p, strokeColor) {
      var bx = this.normalizeBboxPx(p.bbox_px);
      if (!bx || !canvas || !img) return false;
      var iw = img.naturalWidth || 640;
      var ih = img.naturalHeight || 640;
      var cw = img.clientWidth;
      var ch = img.clientHeight;
      // Some “No photo in log” cases use placeholder images that may not have a layout size
      // at the instant the popup painter runs. Fall back to natural sizes so we still draw.
      if (cw < 2 || ch < 2) {
        cw = iw;
        ch = ih;
      }
      canvas.width = cw;
      canvas.height = ch;
      canvas.style.width = cw + "px";
      canvas.style.height = ch + "px";
      var ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, cw, ch);
      var x0 = Math.min(bx[0][0], bx[1][0]);
      var y0 = Math.min(bx[0][1], bx[1][1]);
      var x1 = Math.max(bx[0][0], bx[1][0]);
      var y1 = Math.max(bx[0][1], bx[1][1]);
      var sx = cw / iw;
      var sy = ch / ih;
      function hexToRgb(hex) {
        var h = String(hex).replace("#", "");
        if (h.length !== 6) return { r: 229, g: 57, b: 53 };
        return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) };
      }
      var rgb = hexToRgb(strokeColor);
      ctx.fillStyle = "rgba(" + rgb.r + "," + rgb.g + "," + rgb.b + ",0.16)";
      ctx.fillRect(x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2;
      ctx.strokeRect(x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy);
      return true;
    },

    /**
     * Paint detection bbox on map/frame popups.
     * Listens on the map and reads bbox from `data-sd-det-payload` on `.sd-det-wrap`.
     *
     * Important: do **not** call `popup.update()` here — Leaflet's `DivOverlay.update()` runs
     * `_updateContent()`, which resets `innerHTML` and replaces the img/canvas. Drawing would
     * hit detached nodes and nothing would appear. Use `_updateLayout` / `_updatePosition` only.
     */
    attachMapDetectionPopupPainter: function (map) {
      if (!map || map._sdDetPopupPainterAttached) return;
      map._sdDetPopupPainterAttached = true;
      var self = this;
      map.on("popupopen", function (e) {
        var el = e.popup && e.popup.getElement && e.popup.getElement();
        if (!el) return;
        if (typeof L.DomEvent !== "undefined" && L.DomEvent.disableScrollPropagation && !el._sdDisableScrollPropagation) {
          el._sdDisableScrollPropagation = true;
          L.DomEvent.disableScrollPropagation(el);
        }
        var wrap = el.querySelector(".sd-det-wrap[data-sd-det-payload]");
        if (!wrap) return;
        var encoded = wrap.getAttribute("data-sd-det-payload");
        if (!encoded) return;
        var payload;
        try {
          payload = JSON.parse(decodeURIComponent(encoded));
        } catch (err) {
          return;
        }
        var img = wrap.querySelector(".sd-det-img");
        var canvas = wrap.querySelector(".sd-det-cv");
        if (!img || !canvas) return;
        var p = {
          bbox_px: payload.bbox_px,
          label: payload.label,
          confidence: payload.confidence,
          annotation: payload.annotation,
        };
        var stroke = payload.stroke || self.BBOX_GROUND_STROKE;
        var popup = e.popup;
        var ro = null;
        var timers = [];
        /** Resize popup shell after image/layout changes without resetting innerHTML (see file comment above). */
        function relayoutPopupShell() {
          if (!popup || !popup._map) return;
          try {
            popup._container.style.visibility = "hidden";
            if (typeof popup._updateLayout === "function") popup._updateLayout();
            if (typeof popup._updatePosition === "function") popup._updatePosition();
            if (typeof popup._adjustPan === "function") popup._adjustPan();
            popup._container.style.visibility = "";
          } catch (err) {}
        }
        function cleanup() {
          timers.forEach(function (t) {
            clearTimeout(t);
          });
          timers = [];
          if (ro) {
            try {
              ro.disconnect();
            } catch (err) {}
            ro = null;
          }
          map.off("popupclose", onPopupClose);
        }
        function onPopupClose(ev) {
          if (ev.popup !== popup) return;
          cleanup();
        }
        function redraw() {
          relayoutPopupShell();
          requestAnimationFrame(function () {
            var root = popup.getElement && popup.getElement();
            if (!root) return;
            var w = root.querySelector(".sd-det-wrap[data-sd-det-payload]");
            if (!w) return;
            var im = w.querySelector(".sd-det-img");
            var cv = w.querySelector(".sd-det-cv");
            if (!im || !cv) return;
            self.drawPopupDetectionOverlay(im, cv, p, stroke);
          });
        }
        function afterLayout() {
          redraw();
          [0, 50, 150, 400, 900].forEach(function (ms) {
            timers.push(
              setTimeout(function () {
                redraw();
              }, ms)
            );
          });
          if (typeof ResizeObserver !== "undefined") {
            ro = new ResizeObserver(function () {
              redraw();
            });
            try {
              ro.observe(wrap);
            } catch (err) {}
          }
        }
        map.on("popupclose", onPopupClose);
        function kick() {
          requestAnimationFrame(afterLayout);
        }
        kick();
        if (!img.complete) {
          img.onload = kick;
          img.onerror = kick;
        }
      });
    },

    /**
     * Popup HTML for a ground detection: frame image with canvas overlay (bbox) when available.
     * @param {object} o — { missionId, src, strokeColor?, tagPrefix?, tTag?, frameListIndex?: number }
     *        <code>frameListIndex</code> — 0-based index of this frame in the <code>frames</code> array /
     *        <code>/frame_events</code> list (used for “Open in frame viewer” and image click); if omitted,
     *        falls back to <code>frame.frame_index</code> (often wrong — prefer passing the list index).
     */
    detectionPopupHtmlWithImage: function (esc, p, frame, o) {
      o = o || {};
      var tTag = o.tTag != null ? o.tTag : "";
      var label = esc(p.label || "?");
      var conf = p.confidence != null ? Math.round(Number(p.confidence) * 100) + "%" : "";
      var fi = frame.frame_index != null ? frame.frame_index : "?";
      var headline =
        (o.tagPrefix || "") + "<b>" + label + "</b>" + (conf ? " · " + conf : "") + " · frame #" + fi + tTag;
      var photo = frame.photo_path && frame.photo_path !== "No photo taken";
      // Even when the real photo is missing, still return popup markup that includes an <img> + <canvas>
      // so the bbox overlay painter can run and show the detection geometry.
      var imgUrl = photo
        ? "/missions/" +
          o.missionId +
          "/image?path=" +
          encodeURIComponent(frame.photo_path) +
          "&src=" +
          encodeURIComponent(o.src || "sim")
        : this.TILE_ERROR_URL;
      var noPhotoNote = photo ? "" : '<div class="muted small mt-1">No image in log</div>';
      var navIdx =
        o.frameListIndex != null && o.frameListIndex !== ""
          ? Number(o.frameListIndex)
          : frame.frame_index != null
            ? Number(frame.frame_index)
            : NaN;
      var fiOk = Number.isFinite(navIdx);
      /* Mission dashboard: data-sd-frame-index → Frames tab selectFrameIndex (frame_events list index). */
      var openFullLink =
        !photo
          ? ""
          :
        '<div class="mt-1" style="font-size:11px">' +
        '<a class="sd-det-open-full" href="' +
        imgUrl +
        '"' +
        (fiOk ? ' data-sd-frame-index="' + String(navIdx) + '"' : "") +
        (fiOk ? "" : ' target="_blank" rel="noopener"') +
        ">" +
        (fiOk ? "Open in frame viewer" : "Open full size") +
        "</a></div>";
      var imgNavAttr = fiOk && photo ? ' data-sd-frame-index="' + String(navIdx) + '"' : "";
      var imgPointerStyle = fiOk && photo ? ";cursor:pointer" : "";
      var annotationPlain = "";
      if (tTag) {
        annotationPlain = String(tTag)
          .replace(/^\s*[—\-]\s*/, "")
          .replace(/\s*\(center\)\s*$/i, "")
          .trim();
      }
      var bbox = this.normalizeBboxPx(p.bbox_px);
      if (!bbox) {
        var rawLabelNb = p.label != null && p.label !== "" ? String(p.label) : "?";
        var altNb = [rawLabelNb, conf, "frame " + fi, annotationPlain, "no pixel bbox"].filter(Boolean).join(", ");
        return (
          headline +
          '<br><span class="muted small">No pixel bbox</span>' +
          (photo ? "" : '<br><span class="muted small">No image in log</span>') +
          '<br><img class="sd-det-img" src="' +
          imgUrl +
          '" alt="' +
          escAttr(altNb) +
          '" title="' +
          escAttr(altNb) +
          imgNavAttr +
          '" style="max-width:min(320px,85vw);border-radius:4px;display:block' +
          imgPointerStyle +
          '"/>' +
          openFullLink
        );
      }
      var strokeForPayload = (o && o.strokeColor) || this.BBOX_GROUND_STROKE;
      var detPayload = encodeURIComponent(
        JSON.stringify({
          bbox_px: p.bbox_px,
          label: p.label,
          confidence: p.confidence,
          stroke: strokeForPayload,
          annotation: annotationPlain || undefined,
        })
      );
      var rawLabel = p.label != null && p.label !== "" ? String(p.label) : "?";
      var altParts = [rawLabel];
      if (conf) altParts.push(conf);
      altParts.push("frame " + fi);
      if (annotationPlain) altParts.push(annotationPlain);
      var imgAlt = altParts.join(", ");
      return (
        '<div class="sd-det-popup" style="max-width:min(400px,90vw);box-sizing:border-box">' +
        '<div class="small mb-1">' +
        headline +
        "</div>" +
        noPhotoNote +
        '<div class="position-relative sd-det-wrap" data-sd-det-payload="' +
        detPayload +
        '" style="line-height:0">' +
        '<img class="sd-det-img" src="' +
        imgUrl +
        '" alt="' +
        escAttr(imgAlt) +
        '" title="' +
        escAttr(imgAlt) +
        '"' +
        imgNavAttr +
        ' style="width:100%;max-height:min(70vh,560px);height:auto;display:block;border-radius:4px' +
        imgPointerStyle +
        '"/>' +
        '<canvas class="sd-det-cv" style="position:absolute;left:0;top:0;z-index:2;pointer-events:none;border-radius:4px"></canvas>' +
        "</div>" +
        openFullLink +
        "</div>"
      );
    },

    ensureDetectionUnderlay: function (map) {
      if (!map.getPane(this.FOV_GROUND_PANE)) map.createPane(this.FOV_GROUND_PANE);
      map.getPane(this.FOV_GROUND_PANE).style.zIndex = String(this.FOV_GROUND_PANE_Z);
      if (!map.getPane(this.DETECTION_PANE)) map.createPane(this.DETECTION_PANE);
      map.getPane(this.DETECTION_PANE).style.zIndex = String(this.DETECTION_PANE_Z);
    },

    footprintRingLayer: function (ring, col, cfg) {
      var pane = (cfg && cfg.pane) || this.FOV_GROUND_PANE;
      var fillOp = cfg && cfg.fillOpacity != null ? Number(cfg.fillOpacity) : 0.08;
      var strokeOp = cfg && cfg.strokeOpacity != null ? Number(cfg.strokeOpacity) : 0.9;
      var weight = cfg && cfg.weight != null ? Number(cfg.weight) : 1;
      /* Solid edges only: dashed strokes on hundreds of overlapping quads read as noisy “mesh”. */
      var dash = cfg && cfg.dashArray != null ? cfg.dashArray : null;
      return L.polygon(ring, {
        pane: pane,
        color: col,
        fillColor: col,
        fillOpacity: fillOp,
        opacity: strokeOp,
        weight: weight,
        dashArray: dash,
      });
    },

    mapTileOpts: function (extra) {
      return Object.assign(
        {
          maxZoom: this.MAP_MAX_ZOOM,
          maxNativeZoom: this.ESRI_NATIVE_MAX_ZOOM,
          errorTileUrl: this.TILE_ERROR_URL,
        },
        extra || {}
      );
    },

    sprayEventLatLon: function (ev) {
      if (!ev) return null;
      var w = ev.weed || ev.target_weed || {};
      var lat = w.lat;
      var lon = w.lon;
      if (lat == null || lon == null) {
        lat = ev.lat;
        lon = ev.lon;
      }
      if (lat == null || lon == null) {
        var ds = ev.drone_state;
        if (ds && ds.latitude != null && ds.longitude != null) {
          lat = ds.latitude;
          lon = ds.longitude;
        }
      }
      if (lat == null || lon == null) return null;
      var la = +lat;
      var lo = +lon;
      if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
      return [la, lo];
    },

    /**
     * @param {string} [popupPrefix] e.g. "A" for compare; omit for mission-only popups.
     * @returns {L.CircleMarker[]}
     */
    sprayCircleMarkers: function (sprayEvs, popupPrefix) {
      var out = [];
      var prefix = popupPrefix ? popupPrefix + " · " : "";
      for (var i = 0; i < (sprayEvs || []).length; i++) {
        var ev = sprayEvs[i];
        var ll = this.sprayEventLatLon(ev);
        if (!ll) continue;
        var w = ev && (ev.weed || ev.target_weed) ? (ev.weed || ev.target_weed) : {};
        var weedKey = null;
        if (w && w.id != null) weedKey = String(w.id);
        // Fallback: stable-ish key based on coordinates (rounded).
        if (weedKey == null) {
          var la0 = ll[0],
            lo0 = ll[1];
          weedKey = String(Math.round(la0 * 1e6)) + "," + String(Math.round(lo0 * 1e6));
        }
        function hashStr(s) {
          var h = 0;
          for (var k = 0; k < s.length; k++) h = (h * 31 + s.charCodeAt(k)) >>> 0;
          return h;
        }
        var paletteGreen = ["#2ecc71", "#4adf86", "#6bf1a3", "#1abc9c", "#00d084", "#16a085"];
        var paletteRed = ["#ff4a4a", "#ff6b6b", "#ff5252", "#e74c3c", "#f25f5c", "#c0392b"];
        var pal = ev.event === "weed_sprayed" || ev.event === "spray_attempt" ? paletteGreen : paletteRed;
        var idx = hashStr(weedKey) % pal.length;
        var col = pal[idx];
        out.push(
          L.circleMarker(ll, {
            radius: 8,
            color: col,
            fillColor: col,
            fillOpacity: 0.7,
            weight: 2,
          }).bindPopup(prefix + (ev.event || "") + "<br>" + (ev.ts || ""))
        );
      }
      return out;
    },

    countGroundProjectionRows: function (frames) {
      var n = 0;
      (frames || []).forEach(function (f) {
        n += (f.ground_projections || []).length;
      });
      return n;
    },

    /** Frames that have a drawable camera <code>frame_footprint</code> polygon (≥3 points). */
    countCameraFramePolygons: function (frames) {
      var n = 0;
      (frames || []).forEach(function (f) {
        if ((f.frame_footprint || []).length >= 3) n++;
      });
      return n;
    },

    /** Rows from <code>/camera_fov_footprints</code> (fsm_tick–based) with <code>footprint</code> arrays. */
    countCameraFovFootprintRows: function (rows) {
      var n = 0;
      (rows || []).forEach(function (r) {
        if ((r.footprint || []).length >= 3) n++;
      });
      return n;
    },

    /**
     * Filtered ground_projections — mission styling or compare (per-mission color + tag).
     * @param {object} cfg — { mode:'mission'|'compare', escHtml:function, color?:string, tag?:string }
     * @returns {{ group: L.LayerGroup, bounds: [number,number][] }}
     */
    filteredGroundLayerFromFrames: function (frames, cfg) {
      var g = L.layerGroup();
      var all = [];
      var pane = (cfg && cfg.pane) || this.DETECTION_PANE;
      var esc =
        (cfg && cfg.escHtml) ||
        function (s) {
          return String(s ?? "");
        };
      var mode = (cfg && cfg.mode) || "mission";
      var self = this;

      (frames || []).forEach(function (f, frameListIdx) {
        (f.ground_projections || []).forEach(function (p) {
          var tTag = p.truth_id != null ? " — truth #" + p.truth_id : " — false positive";
          var corners = p.corners || [];
          var hasPoly = corners.length >= 3;
          var c = p.center;
          var ann = cfg.annotatePopups;
          var useAnnot = !!(ann && ann.missionId);
          var strokeColor =
            mode === "mission" ? self.BBOX_GROUND_STROKE : cfg.color || self.BBOX_GROUND_STROKE;
          var tagPrefix = mode === "compare" ? "Mission " + esc(cfg.tag || "?") + " · " : "";

          if (hasPoly) {
            var pts = corners.map(function (q) {
              return [q.lat, q.lon];
            });
            var polyOpts;
            var popup;
            if (mode === "mission") {
              var stroke = self.BBOX_GROUND_STROKE;
              polyOpts = {
                pane: pane,
                color: stroke,
                fillColor: stroke,
                fillOpacity: 0.1,
                weight: 1,
              };
              popup = "<b>" + esc(p.label || "?") + "</b> ground bbox" + tTag;
            } else {
              var c0 = cfg.color;
              polyOpts = {
                pane: pane,
                color: c0,
                fillColor: c0,
                fillOpacity: 0.1,
                weight: 1,
              };
              popup = "Mission " + cfg.tag + " · " + esc(p.label || "?");
            }
            if (useAnnot) {
              popup = self.detectionPopupHtmlWithImage(esc, p, f, {
                missionId: ann.missionId,
                src: ann.src || "sim",
                strokeColor: strokeColor,
                tagPrefix: tagPrefix,
                tTag: tTag,
                frameListIndex: frameListIdx,
              });
            }
            var poly = L.polygon(pts, polyOpts).bindPopup(popup, { maxWidth: 420, className: "sd-det-leaflet-popup" }).addTo(g);
            corners.forEach(function (q) {
              if (q.lat != null && q.lon != null) all.push([q.lat, q.lon]);
            });
          } else if (c && c.lat != null && c.lon != null) {
            var cmOpts;
            var pop2;
            if (mode === "mission") {
              var stroke2 = self.BBOX_GROUND_STROKE;
              cmOpts = {
                pane: pane,
                radius: self.CENTER_ONLY_RADIUS,
                color: stroke2,
                fillColor: stroke2,
                fillOpacity: self.CENTER_ONLY_OPACITY,
                weight: 1,
              };
              pop2 = esc(p.label || "?") + " (center)" + tTag;
            } else {
              var c1 = cfg.color;
              cmOpts = {
                pane: pane,
                radius: self.CENTER_ONLY_RADIUS,
                color: c1,
                fillColor: c1,
                fillOpacity: self.CENTER_ONLY_OPACITY,
                weight: 1,
              };
              pop2 = "Mission " + cfg.tag + " · " + esc(p.label || "?");
            }
            if (useAnnot) {
              pop2 = self.detectionPopupHtmlWithImage(esc, p, f, {
                missionId: ann.missionId,
                src: ann.src || "sim",
                strokeColor: strokeColor,
                tagPrefix: tagPrefix,
                tTag: tTag + " (center)",
                frameListIndex: frameListIdx,
              });
            }
            var cm = L.circleMarker([c.lat, c.lon], cmOpts).bindPopup(pop2, { maxWidth: 420, className: "sd-det-leaflet-popup" }).addTo(g);
            all.push([c.lat, c.lon]);
          }
        });
      });
      return { group: g, bounds: all };
    },

    /**
     * Camera FOV on ground — one polygon per row, or one convex hull of all corners.
     * @param {Array<{footprint:Array, ts?:string, frame_index?:number, state?:string}>} rows
     * @param {object} cfg — { mode, escHtml, tag?, outerHullOnly?, fillOpacity?, strokeOpacity?, weight?, dashArray?, hullColor? }
     */
    cameraFrameOverlayFromFootprintRows: function (rows, cfg) {
      var g = L.layerGroup();
      var all = [];
      var pane = (cfg && cfg.pane) || this.FOV_GROUND_PANE;
      var esc =
        (cfg && cfg.escHtml) ||
        function (s) {
          return String(s ?? "");
        };
      var mode = (cfg && cfg.mode) || "mission";
      var self = this;
      var fillOp = cfg && cfg.fillOpacity != null ? Number(cfg.fillOpacity) : 0.08;
      var strokeOp = cfg && cfg.strokeOpacity != null ? Number(cfg.strokeOpacity) : 0.9;
      var weight = cfg && cfg.weight != null ? Number(cfg.weight) : 1;
      var dash = cfg && cfg.dashArray != null ? cfg.dashArray : null;
      var outerHull = cfg && cfg.outerHullOnly;
      var layerCfg = {
        pane: pane,
        fillOpacity: fillOp,
        strokeOpacity: strokeOp,
        weight: weight,
        dashArray: dash,
      };

      if (outerHull) {
        var corners = [];
        (rows || []).forEach(function (row) {
          (row.footprint || []).forEach(function (p) {
            if (p.lat != null && p.lon != null) corners.push([p.lat, p.lon]);
          });
        });
        var cornerTotal = corners.length;
        if (corners.length > 5000) {
          var stp = Math.ceil(corners.length / 5000);
          var thin = [];
          for (var hi = 0; hi < corners.length; hi += stp) thin.push(corners[hi]);
          corners = thin;
        }
        var ring = self.convexHullLatLonRing(corners);
        if (ring.length < 3) return { group: g, bounds: all };
        var hcol = (cfg && cfg.hullColor) || self.CAMERA_FRAME_COLOR;
        self
          .footprintRingLayer(ring, hcol, Object.assign({}, layerCfg, { dashArray: null }))
          .bindPopup(
            "<b>Camera FOV — outer hull</b><br>" +
              cornerTotal +
              " corners" +
              (cornerTotal > corners.length ? " (" + corners.length + " sampled for hull)" : "") +
              " · convex outline"
          )
          .addTo(g);
        ring.forEach(function (c) {
          all.push(c);
        });
        return { group: g, bounds: all };
      }

      (rows || []).forEach(function (row, fi) {
        var camFp = row.footprint || [];
        if (camFp.length < 3) return;
        var ring = camFp.map(function (p) {
          return [p.lat, p.lon];
        });
        var idx = row.frame_index != null ? row.frame_index : fi;
        var ts = row.ts || "";
        var st = row.state || "";
        var col = self.fovColorForState(st);

        var popup;
        if (mode === "mission") {
          popup =
            "<b>Camera FOV " +
            esc(String(idx + 1)) +
            "</b> (fsm_tick · utils projection)" +
            (st ? "<br>FSM: <b>" + esc(st) + "</b>" : "") +
            (ts ? "<br>" + esc(ts) : "");
        } else {
          popup =
            "Mission " +
            esc(cfg.tag || "?") +
            " · FOV " +
            esc(String(idx + 1)) +
            (st ? "<br>FSM: <b>" + esc(st) + "</b>" : "") +
            (ts ? "<br>" + esc(ts) : "");
        }
        popup += self.fovPopupAppendFrameLink(cfg, row.time_ns) || "";
        var poly = self.footprintRingLayer(ring, col, layerCfg).addTo(g);
        poly.bindPopup(popup, { maxWidth: 360, className: "sd-fov-leaflet-popup" });
        camFp.forEach(function (q) {
          if (q.lat != null && q.lon != null) all.push([q.lat, q.lon]);
        });
      });
      return { group: g, bounds: all };
    },

    /**
     * Same as {@link cameraFrameOverlayFromFootprintRows} but adds polygons in chunks via
     * <code>requestAnimationFrame</code> so the tab stays responsive on large missions.
     */
    cameraFrameOverlayFromFootprintRowsAsync: function (rows, cfg) {
      var g = L.layerGroup();
      var all = [];
      var pane = (cfg && cfg.pane) || this.FOV_GROUND_PANE;
      var esc =
        (cfg && cfg.escHtml) ||
        function (s) {
          return String(s ?? "");
        };
      var mode = (cfg && cfg.mode) || "mission";
      var self = this;
      var fillOp = cfg && cfg.fillOpacity != null ? Number(cfg.fillOpacity) : 0.08;
      var strokeOp = cfg && cfg.strokeOpacity != null ? Number(cfg.strokeOpacity) : 0.9;
      var weight = cfg && cfg.weight != null ? Number(cfg.weight) : 1;
      var dash = cfg && cfg.dashArray != null ? cfg.dashArray : null;
      var outerHull = cfg && cfg.outerHullOnly;
      var layerCfgAsync = {
        pane: pane,
        fillOpacity: fillOp,
        strokeOpacity: strokeOp,
        weight: weight,
        dashArray: dash,
      };
      var rowsArr = rows || [];

      return new Promise(function (resolve) {
        if (outerHull) {
          var corners = [];
          rowsArr.forEach(function (row) {
            (row.footprint || []).forEach(function (p) {
              if (p.lat != null && p.lon != null) corners.push([p.lat, p.lon]);
            });
          });
          var cornerTotal = corners.length;
          if (corners.length > 5000) {
            var stp2 = Math.ceil(corners.length / 5000);
            var thin2 = [];
            for (var hi2 = 0; hi2 < corners.length; hi2 += stp2) thin2.push(corners[hi2]);
            corners = thin2;
          }
          var ringH = self.convexHullLatLonRing(corners);
          if (ringH.length < 3) {
            resolve({ group: g, bounds: all });
            return;
          }
          var hcol2 = (cfg && cfg.hullColor) || self.CAMERA_FRAME_COLOR;
          self
            .footprintRingLayer(ringH, hcol2, Object.assign({}, layerCfgAsync, { dashArray: null }))
            .bindPopup(
              "<b>Camera FOV — outer hull</b><br>" +
                cornerTotal +
                " corners" +
                (cornerTotal > corners.length ? " (" + corners.length + " sampled for hull)" : "") +
                " · convex outline"
            )
            .addTo(g);
          ringH.forEach(function (c) {
            all.push(c);
          });
          resolve({ group: g, bounds: all });
          return;
        }

        var CHUNK = 32;
        var idx = 0;
        function addRowAt(fi) {
          var row = rowsArr[fi];
          var camFp = row.footprint || [];
          if (camFp.length < 3) return;
          var ring = camFp.map(function (p) {
            return [p.lat, p.lon];
          });
          var ix = row.frame_index != null ? row.frame_index : fi;
          var ts = row.ts || "";
          var st = row.state || "";
          var col = self.fovColorForState(st);
          var popup;
          if (mode === "mission") {
            popup =
              "<b>Camera FOV " +
              esc(String(ix + 1)) +
              "</b> (fsm_tick · utils projection)" +
              (st ? "<br>FSM: <b>" + esc(st) + "</b>" : "") +
              (ts ? "<br>" + esc(ts) : "");
          } else {
            popup =
              "Mission " +
              esc(cfg.tag || "?") +
              " · FOV " +
              esc(String(ix + 1)) +
              (st ? "<br>FSM: <b>" + esc(st) + "</b>" : "") +
              (ts ? "<br>" + esc(ts) : "");
          }
          popup += self.fovPopupAppendFrameLink(cfg, row.time_ns) || "";
          var poly = self.footprintRingLayer(ring, col, layerCfgAsync).addTo(g);
          poly.bindPopup(popup, { maxWidth: 360, className: "sd-fov-leaflet-popup" });
          camFp.forEach(function (q) {
            if (q.lat != null && q.lon != null) all.push([q.lat, q.lon]);
          });
        }
        function step() {
          var end = Math.min(idx + CHUNK, rowsArr.length);
          for (; idx < end; idx++) addRowAt(idx);
          if (idx < rowsArr.length) {
            requestAnimationFrame(step);
          } else {
            resolve({ group: g, bounds: all });
          }
        }
        requestAnimationFrame(step);
      });
    },

    /**
     * Legacy: one polygon per frame event with <code>frame_footprint</code>.
     * @param {object} cfg — { mode:'mission'|'compare', escHtml, tag?:string }
     */
    cameraFrameOverlayFromFrames: function (frames, cfg) {
      var rows = (frames || []).map(function (f, i) {
        return {
          footprint: f.frame_footprint,
          frame_index: f.frame_index != null ? f.frame_index : i,
          ts: f.ts,
        };
      });
      return this.cameraFrameOverlayFromFootprintRows(rows, cfg);
    },

    /** Convenience: compare page — single LayerGroup, mission A/B (yellow overlays). */
    compareFilteredGroup: function (frames, color, tag, escHtml, annotateOpts) {
      var base = {
        mode: "compare",
        color: color,
        tag: tag,
        escHtml: escHtml,
      };
      if (annotateOpts && annotateOpts.missionId) {
        base.annotatePopups = annotateOpts;
      }
      return this.filteredGroundLayerFromFrames(frames, base).group;
    },

    compareCameraFrameGroup: function (frames, tag, escHtml) {
      return this.cameraFrameOverlayFromFrames(frames, {
        mode: "compare",
        tag: tag,
        escHtml: escHtml,
      }).group;
    },

    compareCameraFovFootprintGroup: function (rows, tag, escHtml) {
      return this.cameraFrameOverlayFromFootprintRows(rows, {
        mode: "compare",
        tag: tag,
        escHtml: escHtml,
      }).group;
    },
  };

  global.SdMap = SdMap;
})(typeof window !== "undefined" ? window : this);
