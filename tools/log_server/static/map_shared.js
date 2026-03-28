/**
 * Shared map utilities for mission dashboard and compare pages (Leaflet).
 * Depends on global L (Leaflet 1.x).
 */
(function (global) {
  var TILE_ERROR_B64 =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

  var SdMap = {
    DETECTION_PANE: "detectionUnderlay",
    DETECTION_PANE_Z: 350,

    /** No center dot when corners draw a polygon; tiny hit-target when only center exists (popup). */
    CENTER_ONLY_RADIUS: 2,
    CENTER_ONLY_OPACITY: 0.35,

    MAP_MAX_ZOOM: 26,
    TILE_NATIVE_MAX_ZOOM: 22,
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

    BBOX_GROUND_STROKE: "#e53935",

    ensureDetectionUnderlay: function (map) {
      if (!map.getPane(this.DETECTION_PANE)) map.createPane(this.DETECTION_PANE);
      map.getPane(this.DETECTION_PANE).style.zIndex = String(this.DETECTION_PANE_Z);
    },

    mapTileOpts: function (extra) {
      return Object.assign(
        {
          maxZoom: this.MAP_MAX_ZOOM,
          maxNativeZoom: this.TILE_NATIVE_MAX_ZOOM,
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
        var col =
          ev.event === "weed_sprayed" || ev.event === "spray_attempt" ? "#4adf86" : "#ff4a4a";
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

      (frames || []).forEach(function (f) {
        (f.ground_projections || []).forEach(function (p) {
          var tTag = p.truth_id != null ? " — truth #" + p.truth_id : " — false positive";
          var corners = p.corners || [];
          var hasPoly = corners.length >= 3;
          var c = p.center;

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
            L.polygon(pts, polyOpts).bindPopup(popup).addTo(g);
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
            L.circleMarker([c.lat, c.lon], cmOpts).bindPopup(pop2).addTo(g);
            all.push([c.lat, c.lon]);
          }
        });
      });
      return { group: g, bounds: all };
    },

    /**
     * Camera FOV on ground — one yellow dashed polygon per row (telemetry projection or legacy <code>frame_footprint</code>).
     * @param {Array<{footprint:Array, ts?:string, frame_index?:number, state?:string}>} rows
     * @param {object} cfg — { mode:'mission'|'compare', escHtml, tag?:string }
     */
    cameraFrameOverlayFromFootprintRows: function (rows, cfg) {
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
        L.polygon(ring, {
          pane: pane,
          color: col,
          fillColor: col,
          fillOpacity: 0.08,
          weight: 2,
          dashArray: "6 4",
        })
          .bindPopup(popup)
          .addTo(g);
        camFp.forEach(function (q) {
          if (q.lat != null && q.lon != null) all.push([q.lat, q.lon]);
        });
      });
      return { group: g, bounds: all };
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
    compareFilteredGroup: function (frames, color, tag, escHtml) {
      return this.filteredGroundLayerFromFrames(frames, {
        mode: "compare",
        color: color,
        tag: tag,
        escHtml: escHtml,
      }).group;
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
