import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # skydock2/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ai_class import Detection  # noqa: E402
from drone_state import DroneStateForHoming  # noqa: E402
from utils import detection_to_latlon  # noqa: E402

SIM_DATA_ROOT = Path(os.environ.get("SKYDOCK_SIM_DATA_DIR", str(_PROJECT_ROOT / "sim_data")))
MISSIONS_ROOT = Path(os.environ.get("SKYDOCK_MISSIONS_DIR", str(_PROJECT_ROOT / "missions")))

app = Flask(__name__)

# ─── shared theme CSS + JS (injected into every page) ─────────────────────────

_SHARED_STYLE = """<style>
:root{
  --sd-bg:#0b1220;--sd-card:#111b2e;--sd-input:#0e1728;
  --sd-hover:#162040;--sd-border:#1b2a46;
  --sd-text:#e8edf5;--sd-muted:#8fa8c8;--sd-code:#aed4ff;
  --sd-accent:#7db3ff;--sd-pill:#0e1728;
  --sd-better:#4adf86;--sd-worse:#ff6060;--sd-same:#8fa8c8;
}
[data-theme="light"]{
  --sd-bg:#f0f4f8;--sd-card:#ffffff;--sd-input:#ffffff;
  --sd-hover:#e4eaf6;--sd-border:#c8d3e0;
  --sd-text:#1a2030;--sd-muted:#4a5a70;--sd-code:#0d4080;
  --sd-accent:#1a5cbf;--sd-pill:#dce8ff;
  --sd-better:#1a7a40;--sd-worse:#b01010;--sd-same:#4a5a70;
}
body{background:var(--sd-bg);color:var(--sd-text)}
.card{background:var(--sd-card);border:1px solid var(--sd-border)}
a{color:var(--sd-accent)}
.muted{color:var(--sd-muted)}
code{color:var(--sd-code)}
pre{background:var(--sd-input);border:1px solid var(--sd-border);
    padding:10px;border-radius:6px;font-size:12px;color:var(--sd-text)}
/* Bootstrap table overrides */
.table{--bs-table-bg:transparent;--bs-table-border-color:var(--sd-border);
       --bs-table-color:var(--sd-text);color:var(--sd-text)!important}
.table thead th,.table td,.table th{border-color:var(--sd-border)!important;color:var(--sd-text)!important}
/* Bootstrap form overrides */
.form-control,.form-select{background:var(--sd-input)!important;
  border-color:var(--sd-border)!important;color:var(--sd-text)!important}
.form-control:focus,.form-select:focus{border-color:var(--sd-accent)!important;
  box-shadow:none!important;background:var(--sd-input)!important;color:var(--sd-text)!important}
.form-control option,.form-select option{background:var(--sd-input);color:var(--sd-text)}
.form-check-label,.form-label{color:var(--sd-muted)}
/* Bootstrap list-group */
.list-group-item{background:var(--sd-input);border-color:var(--sd-border);color:var(--sd-text)}
.list-group-item-action:hover{background:var(--sd-hover);color:var(--sd-text)}
/* Bootstrap nav-tabs */
.nav-tabs{border-color:var(--sd-border)}
.nav-tabs .nav-link{color:var(--sd-muted);border-color:transparent}
.nav-tabs .nav-link.active{background:var(--sd-card);color:var(--sd-text);
  border-color:var(--sd-border) var(--sd-border) var(--sd-card)}
.nav-tabs .nav-link:hover{color:var(--sd-text);border-color:var(--sd-border)}
.tab-content{background:var(--sd-card);border:1px solid var(--sd-border);
  border-top:none;border-radius:0 0 8px 8px;padding:16px}
/* Bootstrap outline-secondary button */
.btn-outline-secondary{color:var(--sd-muted)!important;border-color:var(--sd-border)!important}
.btn-outline-secondary:hover{background:var(--sd-hover)!important;
  color:var(--sd-text)!important;border-color:var(--sd-border)!important}
/* Bootstrap outline-info button */
.btn-outline-info{color:var(--sd-accent)!important;border-color:var(--sd-accent)!important}
.btn-outline-info:hover{background:var(--sd-hover)!important;color:var(--sd-text)!important}
/* Shared components */
.stats-tbl td,.stats-tbl th{padding:5px 10px;border-color:var(--sd-border)!important;font-size:13px}
.badge-state{font-size:11px;padding:2px 7px;border-radius:10px}
.stat-pill{display:inline-block;background:var(--sd-pill);border:1px solid var(--sd-border);
  border-radius:20px;padding:3px 12px;font-size:13px;margin:2px}
.stat-pill .val{font-weight:600;color:var(--sd-accent)}
.better{color:var(--sd-better);font-weight:600}
.worse{color:var(--sd-worse);font-weight:600}
.same{color:var(--sd-same)}
/* Theme toggle — fixed pill, always visible */
#sd-theme-toggle{
  position:fixed;bottom:18px;right:18px;z-index:9999;
  display:flex;align-items:center;gap:8px;
  background:var(--sd-card);border:1px solid var(--sd-border);
  border-radius:999px;padding:6px 14px 6px 10px;
  font-size:13px;font-weight:500;color:var(--sd-text);
  cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.35);
  user-select:none;transition:box-shadow .15s;
}
#sd-theme-toggle:hover{box-shadow:0 4px 18px rgba(0,0,0,.45)}
#sd-theme-toggle .sd-track{
  width:34px;height:18px;background:#1b2a46;border-radius:9px;
  position:relative;transition:background .2s;flex-shrink:0;
}
[data-theme="light"] #sd-theme-toggle .sd-track{background:#aac4ee}
#sd-theme-toggle .sd-knob{
  position:absolute;top:2px;left:2px;width:14px;height:14px;
  border-radius:50%;background:#7db3ff;transition:transform .2s,background .2s;
}
[data-theme="light"] #sd-theme-toggle .sd-knob{
  transform:translateX(16px);background:#1a5cbf;
}
</style>"""

_THEME_JS = """<script>
// Apply saved theme immediately — before first paint — to prevent flash
(function(){
  var t=localStorage.getItem('sd-theme')||'dark';
  document.documentElement.setAttribute('data-theme',t);
})();

function chartColors(){
  var light=document.documentElement.getAttribute('data-theme')==='light';
  return{
    text: light?'#1a2030':'#e8edf5',
    grid: light?'#c8d3e0':'#1b2a46',
    axis: light?'#4a5a70':'#9fb0c7',
    bg:   'rgba(0,0,0,0)',
  };
}

function _applyTheme(t){
  document.documentElement.setAttribute('data-theme',t);
  localStorage.setItem('sd-theme',t);
  var lbl=document.getElementById('sd-theme-label');
  if(lbl) lbl.textContent=t==='dark'?'Light mode':'Dark mode';
  // Recolour all visible Plotly charts
  var cc=chartColors();
  var upd={'font.color':cc.text,'xaxis.gridcolor':cc.grid,'xaxis.color':cc.axis,
           'yaxis.gridcolor':cc.grid,'yaxis.color':cc.axis};
  document.querySelectorAll('.js-plotly-plot').forEach(function(el){
    try{Plotly.relayout(el,upd);}catch(e){}
  });
}

document.addEventListener('DOMContentLoaded',function(){
  // Inject the floating toggle pill once
  var pill=document.createElement('div');
  pill.id='sd-theme-toggle';
  pill.title='Toggle light / dark mode';
  pill.innerHTML=
    '<div class="sd-track"><div class="sd-knob"></div></div>'+
    '<span id="sd-theme-label"></span>';
  document.body.appendChild(pill);

  var cur=document.documentElement.getAttribute('data-theme')||'dark';
  document.getElementById('sd-theme-label').textContent=
    cur==='dark'?'Light mode':'Dark mode';

  pill.addEventListener('click',function(){
    var c=document.documentElement.getAttribute('data-theme')||'dark';
    _applyTheme(c==='dark'?'light':'dark');
  });

  // Also wire up any legacy #themeBtn if present (old buttons in headers)
  var btn=document.getElementById('themeBtn');
  if(btn) btn.style.display='none';
});
</script>"""


# ─── helpers ──────────────────────────────────────────────────────────────────

def _iter_events(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _mission_paths() -> list[Path]:
    if not MISSIONS_ROOT.exists():
        return []
    dirs = [p for p in MISSIONS_ROOT.iterdir() if p.is_dir() and p.name.isdigit()]
    return sorted(dirs, key=lambda p: int(p.name))


def _sim_files() -> list[str]:
    if not SIM_DATA_ROOT.exists():
        return []
    files = [p.name for p in SIM_DATA_ROOT.iterdir() if p.is_file() and p.suffix == ".json"]
    return sorted(files)


def _mission_log(mission_id: str) -> Path:
    if not mission_id.isdigit():
        abort(404)
    p = MISSIONS_ROOT / mission_id / "mission.jsonl"
    if not p.exists():
        abort(404)
    return p


def _parse_ts(ts_str: str) -> float:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _grid_dedup(pts: list, thresh_m: float = 0.5) -> list:
    """O(n) grid-based spatial deduplication. Returns one representative per cell."""
    cell_deg = thresh_m / 111_320.0
    seen: dict = {}
    for pt in pts:
        key = (round(pt["lat"] / cell_deg), round(pt["lon"] / cell_deg))
        if key not in seen:
            seen[key] = pt
    return list(seen.values())


def _drone_state_from_dict(ds: dict | None) -> DroneStateForHoming | None:
    if not ds or not isinstance(ds, dict):
        return None
    return DroneStateForHoming(
        latitude=float(ds.get("latitude") or 0.0),
        longitude=float(ds.get("longitude") or 0.0),
        altitude_rel_home=float(ds.get("altitude_rel_home") or 0.0),
        rotaion_x=float(ds.get("rotaion_x") or 0.0),
        rotaion_y=float(ds.get("rotaion_y") or 0.0),
        rotaion_z=float(ds.get("rotaion_z") or 0.0),
    )


def _ground_project_one(det: dict, ds: DroneStateForHoming) -> dict | None:
    """
    Project bbox center + four pixel corners to lat/lon using the same model as utils.detection_to_latlon.
    """
    bbox = det.get("bbox")
    if not bbox or len(bbox) < 2:
        return None
    try:
        p0, p1 = bbox[0], bbox[1]
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
    except (TypeError, ValueError, IndexError):
        return None

    label = str(det.get("label") or "?")
    conf = det.get("confidence")
    try:
        full = Detection(
            label=label,
            confidence=float(conf) if conf is not None else 0.0,
            bbox=[(x0, y0), (x1, y1)],
        )
        c_lat, c_lon = detection_to_latlon(ds, full)
        c_lat, c_lon = float(c_lat), float(c_lon)
    except Exception:
        return None

    corners_ll: list[dict[str, float]] = []
    for u, v in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        try:
            pt = Detection(label=label, confidence=0.0, bbox=[(u, v), (u, v)])
            la, lo = detection_to_latlon(ds, pt)
            corners_ll.append({"lat": float(la), "lon": float(lo)})
        except Exception:
            continue

    return {
        "label": label,
        "confidence": conf,
        "bbox_px": bbox,
        "center": {"lat": c_lat, "lon": c_lon},
        "corners": corners_ll,
        "truth_id": det.get("truth_id"),
    }


def _ground_project_list(detections: list[dict], ds: DroneStateForHoming | None) -> tuple[list[dict], str | None]:
    if ds is None:
        return [], "no drone_state on this log line (needed for projection)"
    if ds.altitude_rel_home <= 0:
        return [], "altitude_rel_home must be > 0 to project rays to ground"
    out: list[dict] = []
    for det in detections:
        g = _ground_project_one(det, ds)
        if g:
            out.append(g)
    return out, None


# ─── index ────────────────────────────────────────────────────────────────────

_INDEX_HTML = """<!doctype html>
<html><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Skydock Logs</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  {{ SS | safe }}
</head><body>
<div class="container py-4">
  <div class="d-flex justify-content-between align-items-center mb-4">
    <div>
      <h2 class="mb-0">Skydock Logs</h2>
      <div class="muted">Mission browser &amp; analysis</div>
      <div class="small mt-1">Scanning: <code class="{{ 'better' if missions_root_exists else 'worse' }}">{{ missions_path }}</code>
        <span class="muted">({{ 'found' if missions_root_exists else 'missing' }})</span></div>
    </div>
    <div class="d-flex gap-2 align-items-center">
      <a href="{{ url_for('compare_page') }}" class="btn btn-sm btn-outline-info">&hArr; Compare missions</a>
      <button id="themeBtn"></button>
    </div>
  </div>
  <div class="row g-3">
    <div class="col-12 col-lg-8">
      <div class="card p-3">
        <h5 class="mb-3">Missions</h5>
        <div class="list-group">
          {% for m in missions %}
            {% if m.exists %}
              <a class="list-group-item list-group-item-action"
                 href="{{ url_for('mission_dashboard', mission_id=m.id) }}">
                <div class="d-flex justify-content-between align-items-center">
                  <span><b>Mission {{ m.id }}</b></span>
                  <span class="small better">{{ m.path }}</span>
                </div>
              </a>
            {% else %}
              <div class="list-group-item">
                <b>{{ m.id }}</b> <span class="small worse">{{ m.path }}</span>
                <span class="muted small"> — no mission.jsonl</span>
              </div>
            {% endif %}
          {% endfor %}
          {% if missions|length == 0 %}
            <div class="muted p-2">No missions found.</div>
          {% endif %}
        </div>
      </div>
    </div>
    <div class="col-12 col-lg-4">
      <div class="card p-3">
        <h5 class="mb-2">SIM ground truth</h5>
        <div class="small mb-2">Files in <code class="{{ 'better' if sim_root_exists else 'worse' }}">{{ sim_data_path }}</code>
          <span class="muted">({{ 'found' if sim_root_exists else 'missing' }})</span></div>
        <ul>
          {% for f in sim_files %}<li><code>{{ f }}</code></li>{% endfor %}
          {% if sim_files|length == 0 %}<li class="muted">(none found)</li>{% endif %}
        </ul>
      </div>
    </div>
  </div>
</div>
{{ TJ | safe }}
</body></html>"""


@app.get("/")
def index():
    return redirect(url_for("compare_page"))


@app.get("/missions")
def missions_list():
    missions = [
        {"id": d.name, "path": str(d / "mission.jsonl"), "exists": (d / "mission.jsonl").exists()}
        for d in _mission_paths()
    ]
    return render_template_string(_INDEX_HTML, missions=missions, sim_files=_sim_files(),
                                  missions_path=str(MISSIONS_ROOT), missions_root_exists=MISSIONS_ROOT.exists(),
                                  sim_data_path=str(SIM_DATA_ROOT), sim_root_exists=SIM_DATA_ROOT.exists(),
                                  SS=_SHARED_STYLE, TJ=_THEME_JS)




# ─── dashboard ────────────────────────────────────────────────────────────────

_DASHBOARD_HTML = """<!doctype html>
<html><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Mission {{ mission_id }} – Skydock</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
  {{ SS | safe }}
  <style>
    #map{height:72vh;min-height:560px;max-height:860px;border-radius:8px}
    #framelist{height:480px;overflow-y:auto}
    .frame-item{cursor:pointer;padding:8px 10px;border-bottom:1px solid var(--sd-border);font-size:12px}
    .frame-item:hover{background:var(--sd-input)}
    .frame-item.active{background:var(--sd-hover);border-left:3px solid var(--sd-accent)}
    #frameCanvas{background:var(--sd-input);border:1px solid var(--sd-border);
                 border-radius:6px;max-width:100%;image-rendering:pixelated}
    .live-badge{display:inline-block;background:#ff4a4a;color:#fff;border-radius:12px;
                padding:2px 10px;font-size:12px;font-weight:bold;animation:pulse 1s infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
  </style>
</head><body>
<div class="container-fluid py-3" style="max-width:1400px">

  <!-- header -->
  <div class="d-flex align-items-start justify-content-between mb-3 flex-wrap gap-2">
    <div>
      <div class="d-flex align-items-center gap-2 mb-1">
        <h2 class="mb-0">Mission {{ mission_id }}</h2>
        <span id="liveBadge" class="live-badge d-none">LIVE</span>
      </div>
      <div class="muted small">{{ log_path }}</div>
    </div>
    <div class="d-flex gap-2 align-items-center">
      <button id="liveBtn" class="btn btn-sm btn-outline-danger">&#9679; Live</button>
      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('compare_page') }}">← Home</a>
      <button id="themeBtn"></button>
    </div>
  </div>

  <!-- summary pills -->
  <div id="summaryBar" class="mb-2">
    <span class="muted small">Loading…</span>
  </div>
  <div class="card p-3 mb-3">
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
      <h6 class="mb-0">Mission insights</h6>
      <span class="muted small" id="insightsHint">Log size, path length, altitude, DB mirrors</span>
    </div>
    <div id="insightsBody" class="row g-2 small">
      <span class="muted">Loading…</span>
    </div>
  </div>

  <!-- tabs -->
  <ul class="nav nav-tabs" id="mainTabs">
    <li class="nav-item">
      <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tabMap">Map</button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabTimeline">FSM Timeline</button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabFrames">Frames</button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabReport">Report</button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabFrameReview">Frame Review</button>
    </li>
  </ul>

  <div class="tab-content">

    <!-- ── MAP ─────────────────────────────────────────────────────────── -->
    <div class="tab-pane fade show active" id="tabMap">
      <div class="row g-2 mb-2 align-items-end flex-wrap">
        <div class="col-auto">
          <label class="form-label muted small mb-1">Truth file</label>
          <select id="truthFile" class="form-select form-select-sm" style="min-width:180px">
            <option value="">(no truth file)</option>
            {% for f in sim_files %}
              <option value="{{ f }}"{% if auto_truth == f %} selected{% endif %}>{{ f }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-auto">
          <label class="form-label muted small mb-1">Match (m)</label>
          <input id="threshM" class="form-control form-control-sm" type="number"
                 step="0.5" value="0.5" style="width:72px"/>
        </div>
        <div class="col-auto">
          <button id="runCompare" class="btn btn-sm btn-primary">Run accuracy</button>
        </div>
        <div class="col-auto ms-2 d-flex flex-wrap gap-2 align-items-center">
          <div class="form-check form-check-inline mb-0">
            <input class="form-check-input" type="checkbox" id="layerPath" checked>
            <label class="form-check-label small" for="layerPath">Path</label>
          </div>
          <div class="form-check form-check-inline mb-0">
            <input class="form-check-input" type="checkbox" id="layerPred" checked>
            <label class="form-check-label small" for="layerPred">Predictions</label>
          </div>
          <div class="form-check form-check-inline mb-0">
            <input class="form-check-input" type="checkbox" id="layerTruth">
            <label class="form-check-label small" for="layerTruth">Truth</label>
          </div>
          <div class="form-check form-check-inline mb-0">
            <input class="form-check-input" type="checkbox" id="layerSpray" checked>
            <label class="form-check-label small" for="layerSpray">Spray</label>
          </div>
          <div class="form-check form-check-inline mb-0">
            <input class="form-check-input" type="checkbox" id="layerBboxGround">
            <label class="form-check-label small" for="layerBboxGround" title="Camera bbox corners projected to lat/lon (from frame logs)">BBox ground</label>
          </div>
          <button id="tileToggle" class="btn btn-sm btn-outline-secondary">Satellite</button>
        </div>
      </div>
      <div id="mapInfoLine" class="muted small mb-2" style="min-height:1.3em"></div>
      <div id="map"></div>
      <div id="bboxGroundNote" class="muted small mt-2 d-none" style="min-height:1.3em"></div>
      <div id="mapStats" class="muted small mt-2" style="min-height:1.4em"></div>
    </div>

    <!-- ── FSM TIMELINE ──────────────────────────────────────────────── -->
    <div class="tab-pane fade" id="tabTimeline">
      <div id="timelineChart" style="height:420px"></div>
      <div id="timelineSummary" class="mt-3"></div>
    </div>

    <!-- ── FRAMES ────────────────────────────────────────────────────── -->
    <div class="tab-pane fade" id="tabFrames">
      <div class="row g-3">
        <div class="col-12 col-md-4">
          <div class="muted small mb-2" id="frameCount">Loading frames…</div>
          <div id="framelist" class="card p-0"></div>
        </div>
        <div class="col-12 col-md-8">
          <div class="form-check mb-2">
            <input class="form-check-input" type="checkbox" id="toggleFrameGround">
            <label class="form-check-label small" for="toggleFrameGround">Show bbox on ground (map + table + coordinates)</label>
          </div>
          <div id="frameInfo" class="muted small mb-2" style="min-height:1.4em">
            Click a frame in the list to view
          </div>
          <div id="frameGroundWrap" class="d-none">
            <div class="muted small mb-1">Ground: each bbox projected to the ground (center + four corners)</div>
            <div id="frameGroundMap" style="height:280px;border-radius:8px;border:1px solid var(--sd-border)"></div>
            <div id="frameGroundNote" class="muted small mt-2" style="min-height:1.2em"></div>
            <div id="frameGroundTableWrap" class="table-responsive small mt-2"></div>
          </div>
          <canvas id="frameCanvas" width="640" height="640" class="mt-3"></canvas>
          <div id="frameRawBlock" class="card p-2 mt-2">
            <div class="muted small mb-1">Ground + pixel JSON <span id="frameRawHint" class="d-none">(raw pixel list only exists when logged separately)</span></div>
            <pre id="frameRawPre" class="mb-0" style="max-height:220px;overflow:auto;font-size:11px;white-space:pre-wrap;word-break:break-word"></pre>
          </div>
        </div>
      </div>
    </div>

    <!-- ── REPORT ─────────────────────────────────────────────────────── -->
    <div class="tab-pane fade" id="tabReport">
      <div id="reportContent">
        <div class="muted small">Open this tab to load the report.</div>
      </div>
    </div>

    <!-- ── FRAME REVIEW ───────────────────────────────────────────────── -->
    <div class="tab-pane fade" id="tabFrameReview">
      <div class="row g-3">

        <!-- Left panel: controls -->
        <div class="col-12 col-md-3">
          <div class="mb-2">
            <label class="form-label muted small mb-1">Truth file</label>
            <select id="frTruthFile" class="form-select form-select-sm">
              <option value="">(no truth file)</option>
              {% for f in sim_files %}
                <option value="{{ f }}"{% if auto_truth == f %} selected{% endif %}>{{ f }}</option>
              {% endfor %}
            </select>
            <button id="frLoadTruth" class="btn btn-sm btn-outline-secondary mt-1 w-100">Load truth</button>
          </div>
          <hr style="border-color:var(--sd-border)">
          <div id="frLoading" class="muted small mb-2">Open tab to load frames…</div>
          <div id="frSliderWrap" class="d-none">
            <div class="d-flex justify-content-between align-items-center mb-1">
              <span class="muted small">Frame</span>
              <span class="small"><b id="frIdxDisplay">0</b> / <span id="frTotal">0</span></span>
            </div>
            <input type="range" id="frSlider" min="0" max="0" value="0" class="form-range mb-1">
            <div class="d-flex gap-2">
              <button id="frPrev" class="btn btn-sm btn-outline-secondary flex-fill">&#8249; Prev</button>
              <button id="frNext" class="btn btn-sm btn-outline-secondary flex-fill">Next &#8250;</button>
            </div>
            <div id="frInfo" class="muted small mt-3 p-2 card" style="font-size:11px;min-height:90px"></div>
          </div>
          <hr style="border-color:var(--sd-border)">
          <div class="muted small mb-2">Layers</div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="frCkTruth" checked>
            <label class="form-check-label small" for="frCkTruth" style="color:#ffffff">&#9679; Truth weeds</label>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="frCkPred" checked>
            <label class="form-check-label small" for="frCkPred" style="color:#4a9eff">&#9675; Clustered waypoints</label>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="frCkFootprint" checked>
            <label class="form-check-label small" for="frCkFootprint" style="color:#ffe74a">&#9632; Frame footprint</label>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="frCkDetections" checked>
            <label class="form-check-label small" for="frCkDetections" style="color:#ff9a4a">&#9679; Frame detections</label>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="frCkPath">
            <label class="form-check-label small" for="frCkPath" style="color:#4a9eff">&#8213; Drone path</label>
          </div>
          <button id="frTileToggle" class="btn btn-sm btn-outline-secondary mt-2 w-100">Satellite</button>
        </div>

        <!-- Right panel: map -->
        <div class="col-12 col-md-9">
          <div id="frMap" style="height:72vh;min-height:500px;border-radius:8px;background:var(--sd-input)"></div>
        </div>

      </div>
    </div>

  </div><!-- /tab-content -->
</div><!-- /container -->

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
// ── constants injected by Flask ──────────────────────────────────────────────
const MID       = {{ mission_id_json | safe }};
const SIM_FILES = {{ sim_files_json | safe }};
const AUTO_TRUTH = {{ auto_truth_json | safe }};

// ── colour helpers ───────────────────────────────────────────────────────────
const STATE_COLORS = {
  SCAN:"#4a9eff", SPRAY:"#4adf86", HOMING:"#ff9a4a",
  GOTO:"#bf4aff", OVERRIDE:"#9fb0c7", LAND:"#ff4a4a",
};
const LABEL_PAL = ["#4a9eff","#4adf86","#ff9a4a","#bf4aff","#ff4a4a","#ffe74a"];
function stateColor(s){ return STATE_COLORS[s] || "#7db3ff"; }
function labelColor(lbl){
  let h=0; for(let i=0;i<lbl.length;i++) h=(h*31+lbl.charCodeAt(i))>>>0;
  return LABEL_PAL[h % LABEL_PAL.length];
}
function escHtml(s){
  return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── fetch / format helpers ───────────────────────────────────────────────────
async function api(path){
  const r = await fetch(path);
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}
function fmtDur(s){
  if(s<0) return "0s";
  const m=Math.floor(s/60), sec=Math.round(s%60);
  return m ? `${m}m ${sec}s` : `${sec}s`;
}
function fmtTs(ts){
  if(!ts) return "";
  return new Date(ts).toISOString().replace("T"," ").slice(0,23)+"Z";
}
function fmtBytes(n){
  if(n==null||n===0) return "0 B";
  const u=["B","KB","MB","GB"];
  let i=0,x=+n;
  while(x>=1024&&i<u.length-1){ x/=1024; i++; }
  return `${x.toFixed(i?1:0)} ${u[i]}`;
}

function insightTablesHtml(ins){
  if(!ins) return '<div class="col-12 muted">No insights</div>';
  const altR = (ins.altitude_rel_m_min!=null && ins.altitude_rel_m_max!=null)
    ? `${ins.altitude_rel_m_min}–${ins.altitude_rel_m_max} m (μ ${ins.altitude_rel_m_mean ?? "—"})`
    : "—";
  const db = ins.db_writes || {};
  const dbRows = Object.keys(db).length
    ? Object.entries(db).sort((a,b)=>b[1]-a[1]).map(([k,v])=>
        `<tr><td><code>${escHtml(k)}</code></td><td>${v}</td></tr>`).join("")
    : '<tr><td colspan="2" class="muted">No <code>db_*</code> events yet</td></tr>';
  return `
<div class="col-12 col-lg-6">
  <table class="table table-sm stats-tbl mb-0">
    <tr><td>Log file</td><td>${fmtBytes(ins.log_file_bytes)} · <b>${ins.jsonl_lines||0}</b> lines</td></tr>
    <tr><td>Telemetry samples</td><td>${ins.telemetry_samples ?? 0}</td></tr>
    <tr><td>Path length (from GPS)</td><td><b>${(ins.path_length_m??0).toFixed(1)}</b> m</td></tr>
    <tr><td>Altitude rel. home</td><td>${altR}</td></tr>
    <tr><td>FSM ticks / transitions</td><td>${ins.fsm_ticks ?? 0} / ${ins.fsm_transitions ?? 0}</td></tr>
    <tr><td>Move commands</td><td>${ins.move_commands ?? 0}</td></tr>
    <tr><td>Lines with frame + detections</td><td>${ins.frames_with_detections ?? 0}</td></tr>
  </table>
</div>
<div class="col-12 col-lg-6">
  <div class="muted small mb-1">DB operations mirrored to <code>mission.jsonl</code></div>
  <table class="table table-sm stats-tbl mb-0"><thead><tr><th>Event</th><th>Count</th></tr></thead><tbody>${dbRows}</tbody></table>
</div>`;
}

function updateMapInfoLine(){
  const el = document.getElementById("mapInfoLine");
  if(!el || !_summary || !_summary.insights) return;
  const i = _summary.insights;
  const alt = (i.altitude_rel_m_min!=null)
    ? `${i.altitude_rel_m_min}–${i.altitude_rel_m_max} m`
    : "—";
  el.innerHTML = `Telemetry <b>${i.telemetry_samples||0}</b> samples · path ~<b>${(i.path_length_m||0).toFixed(1)}</b> m · alt ${alt}`;
}

// ── summary bar ─────────────────────────────────────────────────────────────
let _summary = null;
async function loadSummary(){
  _summary = await api(`/missions/${MID}/summary`);
  const { duration_s, weed_detections, unique_weeds, spray_events, header, insights, event_counts } = _summary;
  const ec = event_counts || {};
  const totalEv = Object.values(ec).reduce((a,b)=>a+b,0);
  document.getElementById("summaryBar").innerHTML = `
    <span class="stat-pill">Duration <span class="val">${fmtDur(duration_s)}</span></span>
    <span class="stat-pill">Weed events <span class="val">${weed_detections}</span></span>
    <span class="stat-pill">Unique weeds <span class="val">${unique_weeds}</span></span>
    <span class="stat-pill">Spray events <span class="val">${spray_events}</span></span>
    <span class="stat-pill">Log events <span class="val">${totalEv}</span></span>
    <span class="stat-pill">${header.is_sim
      ? '<span style="color:#ff9a4a">SIM</span>'
      : '<span style="color:#4adf86">REAL</span>'}</span>
  `;
  const ib = document.getElementById("insightsBody");
  if(ib) ib.innerHTML = `<div class="row g-2">${insightTablesHtml(insights)}</div>`;
  updateMapInfoLine();
  // Auto-select linked truth file
  if(_summary.sim_truth_file){
    const sel = document.getElementById("truthFile");
    for(const opt of sel.options)
      if(opt.value === _summary.sim_truth_file){ sel.value = _summary.sim_truth_file; break; }
  }
}

// ═══════════════════════════ MAP TAB ════════════════════════════════════════
let map, layerPath=null, layerPred=null, layerTruth=null, layerSpray=null, layerBboxGround=null;
let osmTile, satTile, usingSat=false;

function buildFootprintLayerFromFrames(frames, colorForDet){
  const g = L.layerGroup();
  const all = [];
  (frames||[]).forEach(f=>{
    (f.ground_projections||[]).forEach(p=>{
      const col = typeof colorForDet === "function" ? colorForDet(p) : colorForDet;
      const tTag = p.truth_id != null ? ` — truth #${p.truth_id}` : ` — false positive`;
      const c = p.center;
      if(c && c.lat!=null && c.lon!=null){
        L.circleMarker([c.lat,c.lon],{
          radius:5, color:col, fillColor:col, fillOpacity:0.45, weight:1
        }).bindPopup(`${escHtml(p.label||"?")} (center)${tTag}`).addTo(g);
        all.push([c.lat,c.lon]);
      }
      const corners = p.corners||[];
      if(corners.length >= 3){
        const pts = corners.map(q=>[q.lat,q.lon]);
        L.polygon(pts,{
          color:col, fillColor:col, fillOpacity:0.12, weight:2
        }).bindPopup(`<b>${escHtml(p.label||"?")}</b> ground footprint${tTag}`).addTo(g);
        corners.forEach(q=>{ if(q.lat!=null&&q.lon!=null) all.push([q.lat,q.lon]); });
      }
    });
  });
  return { group: g, bounds: all };
}

async function refreshMissionBboxGroundLayer(){
  if(!map) return null;
  if(layerBboxGround){ try{ map.removeLayer(layerBboxGround); }catch(e){} layerBboxGround=null; }
  const frames = await api(`/missions/${MID}/frame_events`);
  let fpCount = 0;
  (frames||[]).forEach(f=>{ fpCount += (f.ground_projections||[]).length; });
  const noteEl = document.getElementById("bboxGroundNote");
  if(noteEl){
    noteEl.classList.remove("d-none");
    if(!frames.length){
      noteEl.innerHTML = "BBox ground: <b>no frame events</b> in this log (only state transitions used to log frames). <span class=\\\"muted\\\">Re-run the mission with the current code — FSM now snapshots frames with detections a few times per second.</span>";
    } else if(!fpCount){
      const hint = (frames[0] && frames[0].ground_projection_note) ? ` ${frames[0].ground_projection_note}` : "";
      noteEl.innerHTML = "BBox ground: frames in log but <b>no ground footprints</b> (need valid GPS and altitude_rel_home &gt; 0 on the same lines)."+hint;
    } else {
      noteEl.textContent = `BBox ground: ${fpCount} projected footprint(s) from frame log.`;
    }
  }
  const { group, bounds } = buildFootprintLayerFromFrames(frames, p=>labelColor(p.label||"?"));
  layerBboxGround = group;
  return bounds;
}

function initMap(){
  map = L.map("map");
  osmTile = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {attribution:"© OpenStreetMap contributors", maxZoom:22}
  );
  satTile = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {attribution:"Tiles © Esri", maxZoom:22}
  );
  osmTile.addTo(map);

  document.getElementById("tileToggle").addEventListener("click", ()=>{
    if(usingSat){ map.removeLayer(satTile); osmTile.addTo(map); usingSat=false; }
    else { map.removeLayer(osmTile); satTile.addTo(map); usingSat=true; }
  });
  // Layer toggles
  for(const [id, getter, setter] of [
    ["layerPath",  ()=>layerPath,  v=>layerPath=v],
    ["layerPred",  ()=>layerPred,  v=>layerPred=v],
    ["layerTruth", ()=>layerTruth, v=>layerTruth=v],
    ["layerSpray", ()=>layerSpray, v=>layerSpray=v],
  ]){
    document.getElementById(id).addEventListener("change", e=>{
      const lyr = getter();
      if(!lyr) return;
      e.target.checked ? lyr.addTo(map) : map.removeLayer(lyr);
    });
  }
  const bb = document.getElementById("layerBboxGround");
  if(bb) bb.addEventListener("change", async e=>{
    const n = document.getElementById("bboxGroundNote");
    if(n && !e.target.checked){ n.classList.add("d-none"); n.textContent=""; }
    if(e.target.checked){
      try{
        await refreshMissionBboxGroundLayer();
        if(layerBboxGround) layerBboxGround.addTo(map);
      }catch(err){ alert(err); e.target.checked=false; if(n){ n.classList.add("d-none"); } }
    } else {
      if(layerBboxGround){ try{ map.removeLayer(layerBboxGround); }catch(x){} }
    }
  });
  document.getElementById("runCompare").addEventListener("click", ()=>{
    loadTruth().catch(err=>alert(err));
  });
}

async function loadMap(){
  const [pathPts, predPts, sprayEvs] = await Promise.all([
    api(`/missions/${MID}/path?stride=1`),
    api(`/missions/${MID}/weeds/pred?dedup=1`),
    api(`/missions/${MID}/spray`),
  ]);

  // Drone path
  if(layerPath) map.removeLayer(layerPath);
  const pathCoords = pathPts.filter(p=>p.lat||p.lon).map(p=>[p.lat,p.lon]);
  layerPath = L.polyline(pathCoords, {color:"#4a9eff", weight:2, opacity:0.65});
  if(document.getElementById("layerPath").checked) layerPath.addTo(map);

  // Predicted weeds
  if(layerPred) map.removeLayer(layerPred);
  layerPred = L.layerGroup(predPts.map(p=>
    L.circleMarker([p.lat,p.lon],{
      radius:5, color:"#4a9eff", fillColor:"#4a9eff", fillOpacity:0.5, weight:1.5
    }).bindPopup(`Weed detected<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`)
  ));
  if(document.getElementById("layerPred").checked) layerPred.addTo(map);

  // Spray events
  if(layerSpray) map.removeLayer(layerSpray);
  const sprayMarkers = [];
  for(const ev of sprayEvs){
    const lat = (ev.weed||{}).lat || ev.lat;
    const lon = (ev.weed||{}).lon || ev.lon;
    if(!lat||!lon) continue;
    const color = ev.event==="weed_sprayed" ? "#4adf86" : "#ff4a4a";
    sprayMarkers.push(L.circleMarker([lat,lon],{
      radius:8, color, fillColor:color, fillOpacity:0.7, weight:2
    }).bindPopup(`${ev.event}<br>${ev.ts||""}`));
  }
  layerSpray = L.layerGroup(sprayMarkers);
  if(document.getElementById("layerSpray").checked) layerSpray.addTo(map);

  // Fit
  const all = [...pathCoords, ...predPts.map(p=>[p.lat,p.lon])].filter(c=>c[0]||c[1]);
  if(all.length) map.fitBounds(L.latLngBounds(all), {padding:[30,30]});
  else map.setView([0,0],2);
}

async function loadTruth(){
  const tf  = document.getElementById("truthFile").value;
  const thr = parseFloat(document.getElementById("threshM").value||"0.5");
  if(layerTruth){ map.removeLayer(layerTruth); layerTruth=null; }
  if(!tf){ document.getElementById("mapStats").innerHTML=""; return; }

  const res = await api(`/missions/${MID}/sim_compare?truth=${encodeURIComponent(tf)}&thresh_m=${thr}`);
  layerTruth = L.layerGroup(res.truth_points.map(p=>
    L.circleMarker([p.lat,p.lon],{
      radius:7, color:"#ffffff", fillColor:"transparent", fillOpacity:0, weight:2
    }).bindPopup(`Truth weed #${p.id}<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`)
  ));
  document.getElementById("layerTruth").checked = true;
  layerTruth.addTo(map);

  const s = res.stats;
  const f1 = (s.precision+s.recall)>0 ? 2*s.precision*s.recall/(s.precision+s.recall) : 0;
  document.getElementById("mapStats").innerHTML =
    `truth=<b>${s.truth}</b> &nbsp; pred=<b>${s.pred}</b> &nbsp; `+
    `TP=<b style="color:#4adf86">${s.tp}</b> &nbsp; `+
    `FP=<b style="color:#ff9a4a">${s.fp}</b> &nbsp; `+
    `FN=<b style="color:#ff4a4a">${s.fn}</b> &nbsp; `+
    `precision=<b>${(s.precision*100).toFixed(1)}%</b> &nbsp; `+
    `recall=<b>${(s.recall*100).toFixed(1)}%</b> &nbsp; `+
    `F1=<b style="color:#7db3ff">${(f1*100).toFixed(1)}%</b>`;
}

// ═══════════════════════ FSM TIMELINE TAB ═══════════════════════════════════
let timelineLoaded = false;
async function loadTimeline(){
  if(timelineLoaded) return;
  timelineLoaded = true;
  const data = await api(`/missions/${MID}/timeline`);
  const { segments, summary } = data;
  if(!segments.length){
    document.getElementById("timelineChart").innerHTML =
      '<div class="muted p-3">No FSM transitions found.</div>';
    return;
  }
  const t0 = segments[0].start_ts;
  const traces = [];
  const seen = new Set();
  for(const seg of segments){
    const color = stateColor(seg.state);
    traces.push({
      type:"bar", orientation:"h",
      name: seg.state,
      legendgroup: seg.state,
      showlegend: !seen.has(seg.state),
      x: [seg.duration_s],
      y: [`${seg.state} #${seg.visit_num}`],
      base: [seg.start_ts - t0],
      marker: {color},
      hovertemplate:`${seg.state} visit #${seg.visit_num}`+
        `<br>+${(seg.start_ts-t0).toFixed(1)}s`+
        `<br>duration: ${fmtDur(seg.duration_s)}<extra></extra>`,
    });
    seen.add(seg.state);
  }
  const cc = chartColors();
  const layout = {
    paper_bgcolor:cc.bg, plot_bgcolor:cc.bg,
    font:{color:cc.text},
    barmode:"overlay",
    xaxis:{title:"Time from mission start (s)", gridcolor:cc.grid, color:cc.axis},
    yaxis:{autorange:"reversed", gridcolor:cc.grid, color:cc.axis},
    legend:{orientation:"h", x:0, y:-0.25},
    margin:{l:140, r:20, t:10, b:70},
  };
  Plotly.newPlot("timelineChart", traces, layout, {displayModeBar:false, responsive:true});

  const totalS = summary.reduce((a,s)=>a+s.total_s,0)||1;
  let html = `<table class="table table-sm stats-tbl" style="color:#e8edf5">
    <thead><tr><th>State</th><th>Visits</th><th>Total time</th><th>% of mission</th></tr></thead>
    <tbody>`;
  for(const s of summary){
    const pct = (s.total_s/totalS*100).toFixed(1);
    const c = stateColor(s.state);
    const barW = Math.max(2, Math.round(parseFloat(pct)*1.5));
    html += `<tr>
      <td><span class="badge-state"
            style="background:${c}22;color:${c};border:1px solid ${c}66">${s.state}</span></td>
      <td>${s.visits}</td>
      <td>${fmtDur(s.total_s)}</td>
      <td>
        <div class="d-flex align-items-center gap-2">
          <div style="background:${c};height:8px;border-radius:4px;width:${barW}px"></div>
          ${pct}%
        </div>
      </td>
    </tr>`;
  }
  html += "</tbody></table>";
  document.getElementById("timelineSummary").innerHTML = html;
}

// ═══════════════════════ FRAMES TAB ═════════════════════════════════════════
let _frameEvents = [];
let framesLoaded = false;
let frameMap = null, frameGroundGrp = null;
let _activeFrame = null;

function renderFrameGround(f){
  const noteEl = document.getElementById("frameGroundNote");
  const tblWrap = document.getElementById("frameGroundTableWrap");
  const el = document.getElementById("frameGroundMap");
  if(!el) return;
  if(!frameMap){
    frameMap = L.map("frameGroundMap");
    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {attribution:"© OpenStreetMap", maxZoom:22}
    ).addTo(frameMap);
    frameGroundGrp = L.layerGroup().addTo(frameMap);
  }
  frameGroundGrp.clearLayers();
  const projs = f.ground_projections || [];
  const rawProjs = f.raw_ground_projections || [];
  const hasProjs = projs.length > 0 || rawProjs.length > 0;
  if(noteEl){
    const n = f.ground_projection_note;
    noteEl.textContent = (!hasProjs && n) ? n : "";
  }
  const rows = [];
  function addRows(list, prefix){
    (list||[]).forEach((p,idx)=>{
      const c = p.center || {};
      const clat = (c.lat!=null&&!Number.isNaN(+c.lat)) ? (+c.lat).toFixed(7) : "—";
      const clon = (c.lon!=null&&!Number.isNaN(+c.lon)) ? (+c.lon).toFixed(7) : "—";
      const cornerLines = (p.corners||[]).map((q,j)=>{
        const la = (q.lat!=null) ? (+q.lat).toFixed(7) : "?";
        const lo = (q.lon!=null) ? (+q.lon).toFixed(7) : "?";
        return `C${j+1}: ${la}, ${lo}`;
      }).join("<br/>");
      rows.push(`<tr><td>${escHtml(prefix)}${idx+1}</td><td>${escHtml(p.label||"")}</td><td>${clat}</td><td>${clon}</td><td style="font-size:11px">${cornerLines||"—"}</td></tr>`);
    });
  }
  addRows(rawProjs, "raw ");
  addRows(projs, "");
  if(tblWrap){
    if(!rows.length && f.ground_projection_note){
      tblWrap.innerHTML = `<div class="muted">${escHtml(f.ground_projection_note)}</div>`;
    } else if(!rows.length){
      tblWrap.innerHTML = '<div class="muted">No ground projections (need drone_state with GPS + altitude &gt; 0).</div>';
    } else {
      tblWrap.innerHTML =
        `<table class="table table-sm stats-tbl mb-0"><thead><tr><th>#</th><th>label</th><th>center lat</th><th>center lon</th><th>corners W→E→E→W</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
    }
  }
  const all = [];
  function drawFootprints(list, dashed, colorFn){
    (list||[]).forEach(p=>{
      const col = typeof colorFn === "function" ? colorFn(p) : colorFn;
      const c = p.center;
      if(c && c.lat!=null && c.lon!=null){
        L.circleMarker([c.lat,c.lon],{
          radius:6, color:col, fillColor:col, fillOpacity:0.55, weight:2
        }).bindPopup(`${escHtml(p.label||"")} center`).addTo(frameGroundGrp);
        all.push([c.lat,c.lon]);
      }
      const corners = p.corners||[];
      if(corners.length >= 3){
        const pts = corners.map(q=>[q.lat,q.lon]);
        L.polygon(pts,{
          color:col, fillColor:col, fillOpacity:0.14, weight:2,
          dashArray: dashed ? "6 5" : null,
        }).bindPopup(`<b>${escHtml(p.label||"")}</b> ground footprint`).addTo(frameGroundGrp);
        corners.forEach(q=>{ if(q.lat!=null&&q.lon!=null) all.push([q.lat,q.lon]); });
      }
    });
  }
  drawFootprints(rawProjs, true, "#ff9a4a");
  drawFootprints(projs, false, p=>labelColor(p.label||"?"));
  if(all.length){
    frameMap.fitBounds(L.latLngBounds(all), {padding:[24,24]});
  } else {
    frameMap.setView([0,0], 2);
  }
  setTimeout(()=>{ try{ frameMap.invalidateSize(); }catch(e){} }, 120);
}

async function loadFrames(){
  if(framesLoaded) return;
  framesLoaded = true;
  const frames = await api(`/missions/${MID}/frame_events`);
  _frameEvents = frames;
  document.getElementById("frameCount").textContent =
    `${frames.length} frame${frames.length===1?"":"s"} with detections`;
  const list = document.getElementById("framelist");
  list.innerHTML = "";
  if(!frames.length){
    list.innerHTML = '<div class="muted p-3">No frames with detections in this log.</div>';
    return;
  }
  frames.forEach((f,i)=>{
    const div = document.createElement("div");
    div.className = "frame-item";
    const state = f.state_to || f.state_from || f.event || "";
    div.innerHTML = `
      <div class="d-flex justify-content-between">
        <span style="color:${stateColor(state)}">${state}</span>
        <span class="muted">${fmtTs(f.ts)}</span>
      </div>
      <div class="muted" style="font-size:11px">${f.detections.length} detection(s)
        &nbsp;${f.photo_path && f.photo_path!=="No photo taken"
          ? '<span style="color:#4adf86">📷 photo</span>'
          : '<span style="color:#9fb0c7">synthetic</span>'}</div>`;
    div.addEventListener("click", ()=>{
      document.querySelectorAll(".frame-item").forEach(el=>el.classList.remove("active"));
      div.classList.add("active");
      _activeFrame = f;
      renderFrame(f);
    });
    list.appendChild(div);
  });
  // Auto-select first frame
  if(frames.length) list.children[0].click();
}

function renderFrame(f){
  const canvas = document.getElementById("frameCanvas");
  const ctx    = canvas.getContext("2d");
  const W=640, H=640;
  canvas.width=W; canvas.height=H;
  const hasPhoto = f.photo_path && f.photo_path !== "No photo taken";
  document.getElementById("frameInfo").innerHTML =
    `<span class="muted">${fmtTs(f.ts)} &nbsp; ${f.event||""} &nbsp; </span>`+
    `<span style="color:${hasPhoto?"#4adf86":"#9fb0c7"}">`+
    `${hasPhoto ? f.photo_path : "synthetic — no photo saved"}</span>`;

  const rawPre = document.getElementById("frameRawPre");
  const rawHint = document.getElementById("frameRawHint");
  if(rawPre){
    rawPre.textContent = JSON.stringify({
      ground_projection_note: f.ground_projection_note || null,
      ground_projections: f.ground_projections || [],
      raw_ground_projections: f.raw_ground_projections || null,
      pixel_detections: f.detections || [],
      raw_detections_pixel: f.raw_detections || null,
    }, null, 2);
    if(rawHint) rawHint.classList.toggle("d-none", !!(f.raw_detections && f.raw_detections.length));
  }

  function drawDetList(list, opts){
    const dashed = opts && opts.dashed;
    const overrideColor = opts && opts.color;
    for(const det of (list||[])){
      if(!det.bbox||det.bbox.length<2) continue;
      const [[x0,y0],[x1,y1]] = det.bbox;
      const color = overrideColor || labelColor(det.label||"?");
      ctx.strokeStyle=color;
      ctx.lineWidth= dashed ? 2 : 2;
      ctx.setLineDash(dashed ? [6,4] : []);
      ctx.strokeRect(x0,y0,x1-x0,y1-y0);
      ctx.setLineDash([]);
      if(dashed) continue;
      const lbl=`${det.label||"?"} ${((det.confidence||0)*100).toFixed(0)}%`;
      ctx.font="12px monospace";
      const tw=ctx.measureText(lbl).width;
      ctx.fillStyle=color+"cc"; ctx.fillRect(x0,y0-16,tw+6,16);
      ctx.fillStyle="#fff";     ctx.fillText(lbl,x0+3,y0-3);
    }
  }

  function drawBoxes(){
    if(f.raw_detections && f.raw_detections.length){
      drawDetList(f.raw_detections, {dashed:true, color:"#ff9a4a"});
    }
    drawDetList(f.detections||[], null);
  }

  if(hasPhoto){
    const img=new Image();
    img.onload=()=>{ ctx.drawImage(img,0,0,W,H); drawBoxes(); };
    img.onerror=()=>{ drawSyntheticBg(ctx,W,H); drawBoxes(); };
    img.src=`/missions/${MID}/image?path=${encodeURIComponent(f.photo_path)}`;
  } else {
    drawSyntheticBg(ctx,W,H);
    drawBoxes();
  }
  const tgf = document.getElementById("toggleFrameGround");
  if(tgf && tgf.checked) renderFrameGround(f);
}

function drawSyntheticBg(ctx,W,H){
  ctx.fillStyle="#0e1728"; ctx.fillRect(0,0,W,H);
  ctx.strokeStyle="#1b2a46"; ctx.lineWidth=1;
  for(let x=0;x<W;x+=64){
    ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke();
  }
  for(let y=0;y<H;y+=64){
    ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
  }
  ctx.strokeStyle="#2a3a5a"; ctx.lineWidth=1;
  ctx.beginPath(); ctx.moveTo(W/2,0); ctx.lineTo(W/2,H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0,H/2); ctx.lineTo(W,H/2); ctx.stroke();
  ctx.fillStyle="#2a3a5a"; ctx.font="13px monospace";
  ctx.fillText("640×640 px  (synthetic – no photo saved)", 12, 22);
}

// ═══════════════════════ REPORT TAB ═════════════════════════════════════════
let reportLoaded = false;
async function loadReport(){
  if(reportLoaded) return;
  reportLoaded = true;
  const el = document.getElementById("reportContent");
  try {
    const [summary, timeline, pred, visionEv] = await Promise.all([
      _summary ? Promise.resolve(_summary) : api(`/missions/${MID}/summary`),
      api(`/missions/${MID}/timeline`),
      api(`/missions/${MID}/weeds/pred?dedup=1`),
      api(`/missions/${MID}/sim_vision`),
    ]);
    el.innerHTML = buildReport(summary, timeline, pred, visionEv);

    // Auto-run accuracy if truth file linked
    if(summary.sim_truth_file){
      const thresh = summary.header?.weed_match_m ?? 0.5;
      const res = await api(
        `/missions/${MID}/sim_compare?truth=${encodeURIComponent(summary.sim_truth_file)}&thresh_m=${thresh}`
      );
      renderAccuracy("accuracyBlock", res.stats, thresh, summary.sim_truth_file);
    }
  } catch(e){
    el.innerHTML = `<div class="muted">Error: ${e}</div>`;
  }
}

function renderAccuracy(elId, s, thresh, tf){
  const f1 = (s.precision+s.recall)>0 ? 2*s.precision*s.recall/(s.precision+s.recall) : 0;
  document.getElementById(elId).innerHTML = `
    <table class="table table-sm stats-tbl mb-2" style="color:#e8edf5">
      <tr><td>Truth weeds</td>          <td><b>${s.truth}</b></td></tr>
      <tr><td>Predicted (dedup)</td>    <td><b>${s.pred}</b></td></tr>
      <tr><td>True positives</td>       <td style="color:#4adf86"><b>${s.tp}</b></td></tr>
      <tr><td>False positives</td>      <td style="color:#ff9a4a"><b>${s.fp}</b></td></tr>
      <tr><td>False negatives</td>      <td style="color:#ff4a4a"><b>${s.fn}</b></td></tr>
      <tr><td>Precision</td>            <td><b>${(s.precision*100).toFixed(1)}%</b></td></tr>
      <tr><td>Recall</td>               <td><b>${(s.recall*100).toFixed(1)}%</b></td></tr>
      <tr><td>F1 score</td>
          <td><b style="color:#7db3ff">${(f1*100).toFixed(1)}%</b></td></tr>
      <tr><td>Match radius</td>         <td>${thresh} m</td></tr>
    </table>
    <div class="muted small">Truth: <code>${tf}</code></div>`;
}

function buildReport(summary, timeline, pred, visionEv){
  const { duration_s, weed_detections, unique_weeds, spray_events, event_counts, header } = summary;
  const flightCard = summary.insights
    ? `<div class="col-12">
         <div class="card p-3">
           <h6>Flight &amp; log</h6>
           <div class="row g-2">${insightTablesHtml(summary.insights)}</div>
         </div>
       </div>`
    : "";

  const evRows = Object.entries(event_counts)
    .sort((a,b)=>b[1]-a[1])
    .map(([k,v])=>`<tr><td><code>${k}</code></td><td>${v}</td></tr>`)
    .join("");

  const totalS = timeline.summary.reduce((a,s)=>a+s.total_s,0)||1;
  const stateRows = timeline.summary.map(s=>{
    const c=stateColor(s.state), pct=(s.total_s/totalS*100).toFixed(1);
    return `<tr>
      <td><span class="badge-state"
            style="background:${c}22;color:${c};border:1px solid ${c}66">${s.state}</span></td>
      <td>${s.visits}</td><td>${fmtDur(s.total_s)}</td><td>${pct}%</td></tr>`;
  }).join("");

  const visionBlock = visionEv && visionEv.vision
    ? `<div class="card p-3">
         <h6>SIM vision parameters</h6>
         <div class="muted small mb-2">From <code>sim_vision_params</code> (${visionEv.ts || ""})</div>
         <pre class="mb-0" style="white-space:pre-wrap">${JSON.stringify(visionEv.vision, null, 2)}</pre>
       </div>`
    : "";

  return `<div class="row g-3">
    <div class="col-12 col-md-6 col-lg-4">
      <div class="card p-3">
        <h6>Mission Info</h6>
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
          <tr><td>Mission ID</td>  <td><b>${header.mission_id||MID}</b></td></tr>
          <tr><td>Type</td>
              <td>${header.is_sim
                ? '<span style="color:#ff9a4a">SIMULATION</span>'
                : '<span style="color:#4adf86">REAL FLIGHT</span>'}</td></tr>
          <tr><td>Duration</td>    <td>${fmtDur(duration_s)}</td></tr>
          <tr><td>Schema</td>      <td>v${header.schema_version||1}</td></tr>
          ${header.sim_truth_file
            ? `<tr><td>Truth file</td><td><code>${header.sim_truth_file}</code></td></tr>`:""}
          ${header.weed_match_m!=null
            ? `<tr><td>weed_match_m (header)</td><td>${header.weed_match_m} m</td></tr>`:""}
          ${header.min_spray_error_m!=null
            ? `<tr><td>min_spray_error_m</td><td>${header.min_spray_error_m} m</td></tr>`:""}
        </table>
      </div>
    </div>
    <div class="col-12 col-md-6 col-lg-4">
      <div class="card p-3">
        <h6>Detection Summary</h6>
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
          <tr><td>Weed detection events</td><td><b>${weed_detections}</b></td></tr>
          <tr><td>Unique weed locations</td><td><b>${unique_weeds}</b></td></tr>
          <tr><td>Spray events</td>         <td><b>${spray_events}</b></td></tr>
          <tr><td>Predictions on map</td>   <td><b>${pred.length}</b></td></tr>
        </table>
      </div>
    </div>
    <div class="col-12 col-md-6 col-lg-4">
      <div class="card p-3">
        <h6>Accuracy vs Ground Truth</h6>
        <div id="accuracyBlock">
          ${summary.sim_truth_file
            ? '<div class="muted small">Loading…</div>'
            : '<div class="muted small">No truth file linked to this mission.<br>'+
              'Run comparison from the Map tab.</div>'}
        </div>
      </div>
    </div>
    ${visionBlock ? `<div class="col-12 col-lg-12">${visionBlock}</div>` : ""}
    ${flightCard}
    <div class="col-12 col-md-6">
      <div class="card p-3">
        <h6>State Time Breakdown</h6>
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
          <thead><tr><th>State</th><th>Visits</th><th>Total time</th><th>%</th></tr></thead>
          <tbody>${stateRows}</tbody>
        </table>
      </div>
    </div>
    <div class="col-12 col-md-6">
      <div class="card p-3">
        <h6>Event Counts</h6>
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
          <thead><tr><th>Event type</th><th>Count</th></tr></thead>
          <tbody>${evRows}</tbody>
        </table>
      </div>
    </div>
  </div>`;
}

// ═══════════════════════ LIVE MODE ══════════════════════════════════════════
let liveTimer=null, liveByte=0, liveActive=false;
const LIVE_MS = 2000;

async function livePoll(){
  try {
    const data = await api(`/missions/${MID}/tail?since_byte=${liveByte}`);
    if(!data.events.length) return;
    liveByte = data.next_byte;
    // Update summary counts
    if(_summary){
      for(const ev of data.events){
        const t=ev.event;
        _summary.event_counts[t] = (_summary.event_counts[t]||0)+1;
        if(t==="weed_detected") _summary.weed_detections++;
      }
      // Recalculate unique weeds (approximate: just increment)
      const newWeeds = data.events.filter(e=>e.event==="weed_detected");
      if(newWeeds.length){
        // Refresh pred layer
        const predPts = await api(`/missions/${MID}/weeds/pred?dedup=1`);
        if(layerPred) map.removeLayer(layerPred);
        layerPred = L.layerGroup(predPts.map(p=>
          L.circleMarker([p.lat,p.lon],{
            radius:5,color:"#4a9eff",fillColor:"#4a9eff",fillOpacity:0.5,weight:1.5
          }).bindPopup(`${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`)
        ));
        if(document.getElementById("layerPred").checked) layerPred.addTo(map);
        _summary.unique_weeds = predPts.length;
      }
      // Refresh summary bar
      const { duration_s, weed_detections, unique_weeds, spray_events, header } = _summary;
      document.getElementById("summaryBar").innerHTML = `
        <span class="stat-pill">Duration <span class="val">${fmtDur(duration_s)}</span></span>
        <span class="stat-pill">Weed events <span class="val">${weed_detections}</span></span>
        <span class="stat-pill">Unique weeds <span class="val">${unique_weeds}</span></span>
        <span class="stat-pill">Spray events <span class="val">${spray_events}</span></span>
        <span class="stat-pill">${header.is_sim
          ? '<span style="color:#ff9a4a">SIM</span>'
          : '<span style="color:#4adf86">REAL</span>'}</span>
      `;
    }
  } catch(e){ console.warn("live poll:", e); }
}

document.getElementById("liveBtn").addEventListener("click", async ()=>{
  liveActive = !liveActive;
  const btn   = document.getElementById("liveBtn");
  const badge = document.getElementById("liveBadge");
  if(liveActive){
    // Seek to current EOF so we only show new events
    try {
      const d = await api(`/missions/${MID}/tail?since_byte=9999999999`);
      liveByte = d.file_size;
    } catch(e){ liveByte=0; }
    liveTimer = setInterval(livePoll, LIVE_MS);
    btn.className="btn btn-sm btn-danger";
    btn.textContent="■ Stop Live";
    badge.classList.remove("d-none");
  } else {
    clearInterval(liveTimer);
    btn.className="btn btn-sm btn-outline-danger";
    btn.textContent="&#9679; Live";
    badge.classList.add("d-none");
  }
});

// ═══════════════════════ TAB ACTIVATION ═════════════════════════════════════
document.querySelectorAll('[data-bs-toggle="tab"]').forEach(btn=>{
  btn.addEventListener("shown.bs.tab", e=>{
    const t = e.target.getAttribute("data-bs-target");
    if(t==="#tabTimeline") loadTimeline().catch(console.error);
    if(t==="#tabFrames"){
      loadFrames().catch(console.error);
      setTimeout(()=>{
        try{
          const tg = document.getElementById("toggleFrameGround");
          if(tg && tg.checked && typeof _activeFrame !== "undefined" && _activeFrame)
            renderFrameGround(_activeFrame);
          if(frameMap) frameMap.invalidateSize();
        }catch(e){}
      }, 250);
    }
    if(t==="#tabReport")   loadReport().catch(console.error);
    if(t==="#tabMap")      { if(map) map.invalidateSize(); }
  });
});

// ═══════════════════════ INIT ════════════════════════════════════════════════
(async ()=>{
  initMap();
  try{
    await loadMap();
  }catch(e){
    const ms = document.getElementById("mapStats");
    if(ms) ms.innerHTML = `<span style="color:#ff9a4a">Map load error:</span> ${e}`;
  }
  try{
    await loadSummary();
  }catch(e){
    const sb = document.getElementById("summaryBar");
    if(sb) sb.innerHTML = `<span class="muted">Summary unavailable: ${e}</span>`;
  }
  const tg = document.getElementById("toggleFrameGround");
  const wrap = document.getElementById("frameGroundWrap");
  if(tg && wrap){
    tg.addEventListener("change", ()=>{
      if(tg.checked) wrap.classList.remove("d-none");
      else wrap.classList.add("d-none");
      setTimeout(()=>{
        try{
          if(frameMap && tg.checked){
            frameMap.invalidateSize();
            if(_activeFrame) renderFrameGround(_activeFrame);
          }
        }catch(e){}
      }, 80);
    });
  }
  // Auto-run truth comparison if linked in mission header
  if(_summary && _summary.sim_truth_file){
    document.getElementById("layerTruth").checked = true;
    try{ await loadTruth(); }catch(e){}
  }
})();

// ═══════════════════════ FRAME REVIEW TAB ═══════════════════════════════════
(function(){
  let frMap = null, frOsmTile = null, frSatTile = null, frUsingSat = false;
  let frFrames = [];
  let frCurrentIdx = 0;
  let frGrpTruth = null, frGrpPred = null, frGrpPath = null;
  let frGrpFootprint = null, frGrpDetections = null;

  const frTab = document.querySelector('[data-bs-target="#tabFrameReview"]');
  if(!frTab) return;

  frTab.addEventListener('shown.bs.tab', initFR);

  async function initFR(){
    if(frMap) return;

    frMap = L.map('frMap');
    frOsmTile = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      {attribution:'&copy; OpenStreetMap contributors', maxZoom:21}).addTo(frMap);
    frSatTile = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      {attribution:'Esri World Imagery', maxZoom:21});

    document.getElementById('frTileToggle').addEventListener('click', ()=>{
      frUsingSat = !frUsingSat;
      if(frUsingSat){ frMap.removeLayer(frOsmTile); frSatTile.addTo(frMap); }
      else { frMap.removeLayer(frSatTile); frOsmTile.addTo(frMap); }
      document.getElementById('frTileToggle').textContent = frUsingSat ? 'Street' : 'Satellite';
    });

    // Load frame data (reuse cached _frameEvents if already populated)
    const loadingEl = document.getElementById('frLoading');
    loadingEl.textContent = 'Loading frames…';
    try{
      frFrames = (_frameEvents && _frameEvents.length)
        ? _frameEvents
        : await api(`/missions/${MID}/frame_events`);
    }catch(e){
      loadingEl.textContent = `Error loading frames: ${e}`;
      return;
    }

    if(!frFrames.length){
      loadingEl.textContent = 'No frames with detections found.';
      return;
    }
    loadingEl.classList.add('d-none');
    document.getElementById('frSliderWrap').classList.remove('d-none');

    const slider = document.getElementById('frSlider');
    slider.max = frFrames.length - 1;
    document.getElementById('frTotal').textContent = frFrames.length - 1;
    slider.addEventListener('input', ()=>{ frCurrentIdx=+slider.value; frRenderFrame(frCurrentIdx); });

    document.getElementById('frPrev').addEventListener('click', ()=>{
      if(frCurrentIdx > 0){ frCurrentIdx--; slider.value=frCurrentIdx; frRenderFrame(frCurrentIdx); }
    });
    document.getElementById('frNext').addEventListener('click', ()=>{
      if(frCurrentIdx < frFrames.length-1){ frCurrentIdx++; slider.value=frCurrentIdx; frRenderFrame(frCurrentIdx); }
    });

    // Layer checkboxes
    function ckToggle(id, getGrp){
      const el = document.getElementById(id);
      if(el) el.addEventListener('change', ()=>{
        const g = getGrp();
        if(!g) return;
        el.checked ? g.addTo(frMap) : frMap.removeLayer(g);
      });
    }
    ckToggle('frCkTruth',      ()=>frGrpTruth);
    ckToggle('frCkPred',       ()=>frGrpPred);
    ckToggle('frCkFootprint',  ()=>frGrpFootprint);
    ckToggle('frCkDetections', ()=>frGrpDetections);
    ckToggle('frCkPath',       ()=>frGrpPath);

    // Truth file button
    document.getElementById('frLoadTruth').addEventListener('click', frLoadTruth);

    // Auto-load truth if linked
    const tf = document.getElementById('frTruthFile');
    if(tf && tf.value) frLoadTruth();

    // Load pred + path eagerly
    frLoadPred();
    // Path loaded lazily on checkbox change
    document.getElementById('frCkPath').addEventListener('change', async function(){
      if(this.checked && !frGrpPath) await frLoadPath();
      if(frGrpPath){ this.checked ? frGrpPath.addTo(frMap) : frMap.removeLayer(frGrpPath); }
    });

    frRenderFrame(0);
  }

  async function frLoadTruth(){
    const tf = document.getElementById('frTruthFile').value;
    if(frGrpTruth){ try{ frMap.removeLayer(frGrpTruth); }catch(e){} frGrpTruth=null; }
    if(!tf) return;
    try{
      const res = await api(`/missions/${MID}/sim_compare?truth=${encodeURIComponent(tf)}&thresh_m=999999`);
      const markers = (res.truth_points||[]).map(p=>
        L.circleMarker([p.lat,p.lon],{
          radius:6, color:"#ffffff", fillColor:"#ffffff", fillOpacity:0.9, weight:1.5
        }).bindPopup(`Truth weed #${p.id}<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`));
      frGrpTruth = L.layerGroup(markers);
      if(document.getElementById('frCkTruth').checked) frGrpTruth.addTo(frMap);
      if(markers.length){
        const lats = res.truth_points.map(p=>p.lat);
        const lons = res.truth_points.map(p=>p.lon);
        frMap.fitBounds([[Math.min(...lats),Math.min(...lons)],[Math.max(...lats),Math.max(...lons)]],{padding:[30,30]});
      }
    }catch(e){ alert('Truth load error: '+e); }
  }

  async function frLoadPred(){
    if(frGrpPred){ try{ frMap.removeLayer(frGrpPred); }catch(e){} frGrpPred=null; }
    try{
      const pred = await api(`/missions/${MID}/weeds/pred`);
      const markers = (pred||[]).map(p=>
        L.circleMarker([p.lat,p.lon],{
          radius:7, color:"#4a9eff", fillColor:"#4a9eff", fillOpacity:0.35, weight:2
        }).bindPopup(`Clustered prediction<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`));
      frGrpPred = L.layerGroup(markers);
      if(document.getElementById('frCkPred').checked) frGrpPred.addTo(frMap);
    }catch(e){}
  }

  async function frLoadPath(){
    try{
      const pts = await api(`/missions/${MID}/path`);
      if(!pts||!pts.length) return;
      const lls = pts.map(p=>[p.lat,p.lon]);
      frGrpPath = L.layerGroup([L.polyline(lls,{color:"#4a9eff",weight:2,opacity:0.6})]);
      if(document.getElementById('frCkPath').checked) frGrpPath.addTo(frMap);
    }catch(e){}
  }

  function frRenderFrame(idx){
    const f = frFrames[idx];
    if(!f) return;
    document.getElementById('frIdxDisplay').textContent = idx;
    document.getElementById('frSlider').value = idx;

    // Info panel
    const ds = f.drone_state || {};
    const alt = ds.altitude_rel_home != null ? ds.altitude_rel_home.toFixed(1)+'m' : '—';
    const lat = ds.latitude != null ? ds.latitude.toFixed(6) : '—';
    const lon = ds.longitude != null ? ds.longitude.toFixed(6) : '—';
    const ts  = f.ts ? new Date(f.ts).toISOString().replace('T',' ').slice(0,23)+'Z' : '—';
    const nDet = (f.detections||[]).length;
    const state = f.state_to || f.state_from || '—';
    document.getElementById('frInfo').innerHTML =
      `<div><b>Frame ${idx}</b></div>`+
      `<div>Time: ${escHtml(ts)}</div>`+
      `<div>State: ${escHtml(state)}</div>`+
      `<div>Alt: ${escHtml(alt)} &nbsp; Detections: <b>${nDet}</b></div>`+
      `<div>Drone: ${escHtml(lat)}, ${escHtml(lon)}</div>`;

    // Remove old per-frame layers
    if(frGrpFootprint){ try{ frMap.removeLayer(frGrpFootprint); }catch(e){} frGrpFootprint=null; }
    if(frGrpDetections){ try{ frMap.removeLayer(frGrpDetections); }catch(e){} frGrpDetections=null; }

    const items = [];

    // Footprint polygon
    const fp = f.frame_footprint || [];
    if(fp.length >= 3){
      const ring = fp.map(p=>[p.lat,p.lon]);
      items.push(L.polygon(ring,{
        color:"#ffe74a", fillColor:"#ffe74a", fillOpacity:0.08, weight:2, dashArray:"6 4"
      }).bindPopup(`Frame ${idx} footprint`));
    }
    frGrpFootprint = L.layerGroup(items);
    if(document.getElementById('frCkFootprint').checked) frGrpFootprint.addTo(frMap);

    // Detection markers
    const detItems = [];
    (f.ground_projections||[]).forEach(gp=>{
      if(!gp.center) return;
      const c = gp.center;
      const truthTag = gp.truth_id != null ? `truth #${gp.truth_id}` : `false positive`;
      detItems.push(L.circleMarker([c.lat,c.lon],{
        radius:5, color:"#ff9a4a", fillColor:"#ff9a4a", fillOpacity:0.9, weight:1.5
      }).bindPopup(`${escHtml(gp.label||'?')} (${((gp.confidence||0)*100).toFixed(0)}%) — ${truthTag}<br>${c.lat.toFixed(6)}, ${c.lon.toFixed(6)}`));
      // Draw projected bbox corners too
      if(gp.corners && gp.corners.length >= 4){
        const ring = gp.corners.map(p=>[p.lat,p.lon]);
        detItems.push(L.polygon(ring,{
          color:"#ff9a4a", fillColor:"#ff9a4a", fillOpacity:0.12, weight:1.5
        }));
      }
    });
    frGrpDetections = L.layerGroup(detItems);
    if(document.getElementById('frCkDetections').checked) frGrpDetections.addTo(frMap);

    // Fit map to footprint (or drone pos fallback)
    if(fp.length >= 3){
      const lats = fp.map(p=>p.lat), lons = fp.map(p=>p.lon);
      frMap.fitBounds(
        [[Math.min(...lats),Math.min(...lons)],[Math.max(...lats),Math.max(...lons)]],
        {padding:[40,40], maxZoom:20}
      );
    } else if(f.drone_pos){
      frMap.setView([f.drone_pos.lat, f.drone_pos.lon], 18);
    }
  }
})();
</script>
{{ TJ | safe }}
</body></html>"""


@app.get("/missions/<mission_id>")
def mission_dashboard(mission_id: str):
    p = _mission_log(mission_id)
    auto_truth = ""
    for ev in _iter_events(p):
        if ev.get("event") == "mission_start":
            raw = ev.get("sim_truth_file", "") or ""
            # Accept either "foo.json" or "sim_data/foo.json"
            auto_truth = Path(str(raw)).name if raw else ""
            break
    return render_template_string(
        _DASHBOARD_HTML,
        mission_id=mission_id,
        log_path=str(p),
        sim_files=_sim_files(),
        mission_id_json=json.dumps(mission_id),
        sim_files_json=json.dumps(_sim_files()),
        auto_truth_json=json.dumps(auto_truth),
        auto_truth=auto_truth,
        SS=_SHARED_STYLE,
        TJ=_THEME_JS,
    )


# ─── existing API endpoints (kept for backwards compat) ───────────────────────

@app.get("/missions/<mission_id>/events")
def mission_events(mission_id: str):
    p = _mission_log(mission_id)
    limit = int(request.args.get("limit", "200"))
    events = []
    for ev in _iter_events(p):
        events.append(ev)
        if len(events) >= limit:
            break
    return jsonify(events)


@app.get("/missions/<mission_id>/fsm")
def mission_fsm(mission_id: str):
    p = _mission_log(mission_id)
    return jsonify([ev for ev in _iter_events(p) if ev.get("event") == "fsm_transition"])


@app.get("/missions/<mission_id>/weeds")
def mission_weeds(mission_id: str):
    p = _mission_log(mission_id)
    kinds = {"weed_detected", "weed_sprayed", "spray_attempt", "spray_miss", "spray_ready"}
    return jsonify([ev for ev in _iter_events(p) if ev.get("event") in kinds])


@app.get("/missions/<mission_id>/weeds/pred")
def mission_weeds_pred(mission_id: str):
    p = _mission_log(mission_id)
    do_dedup = request.args.get("dedup", "0") == "1"
    thresh_m = float(request.args.get("thresh_m", "0.5"))
    pts = []
    for ev in _iter_events(p):
        if ev.get("event") != "weed_detected":
            continue
        lat = ev.get("lat") or (ev.get("weed") or {}).get("lat")
        lon = ev.get("lon") or (ev.get("weed") or {}).get("lon")
        if lat is None or lon is None:
            continue
        pts.append({"lat": float(lat), "lon": float(lon)})
    if do_dedup:
        pts = _grid_dedup(pts, thresh_m)
    return jsonify(pts)


# ─── new API endpoints ────────────────────────────────────────────────────────

@app.get("/missions/<mission_id>/path")
def mission_path(mission_id: str):
    """Drone path from telemetry_sample (GPS ~1 Hz). Use stride=1 for full resolution."""
    p = _mission_log(mission_id)
    stride = max(1, int(request.args.get("stride", "1")))
    pts, count = [], 0
    for ev in _iter_events(p):
        if ev.get("event") != "telemetry_sample":
            continue
        count += 1
        if count % stride != 0:
            continue
        ds = ev.get("drone_state", {})
        lat, lon = ds.get("latitude", 0), ds.get("longitude", 0)
        if lat == 0 and lon == 0:
            continue
        pts.append({"lat": lat, "lon": lon, "alt": ds.get("altitude_rel_home", 0), "ts": ev.get("ts", "")})
    return jsonify(pts)


@app.get("/missions/<mission_id>/spray")
def mission_spray(mission_id: str):
    """All spray-related events."""
    p = _mission_log(mission_id)
    kinds = {"weed_sprayed", "spray_attempt", "spray_miss", "spray_ready", "spray_skipped"}
    return jsonify([ev for ev in _iter_events(p) if ev.get("event") in kinds])


@app.get("/missions/<mission_id>/timeline")
def mission_timeline(mission_id: str):
    """FSM state segments with wall-clock durations and visit counts."""
    p = _mission_log(mission_id)
    transitions = []
    last_ts = None
    for ev in _iter_events(p):
        ts = _parse_ts(ev.get("ts", ""))
        if ts > 0:
            last_ts = ts
        if ev.get("event") == "fsm_transition":
            transitions.append({
                "ts": ts,
                "state_from": ev.get("state_from", "").replace("DroneStateEnum.", ""),
                "state_to":   ev.get("state_to",   "").replace("DroneStateEnum.", ""),
            })

    segments: list[dict] = []
    visit_counts: dict[str, int] = {}
    for i, t in enumerate(transitions):
        state = t["state_to"]
        start_ts = t["ts"]
        end_ts = transitions[i + 1]["ts"] if i + 1 < len(transitions) else (last_ts or start_ts)
        visit_counts[state] = visit_counts.get(state, 0) + 1
        segments.append({
            "state":      state,
            "start_ts":   start_ts,
            "end_ts":     end_ts,
            "duration_s": max(0.0, end_ts - start_ts),
            "visit_num":  visit_counts[state],
        })

    summary: dict[str, dict] = {}
    for seg in segments:
        s = seg["state"]
        if s not in summary:
            summary[s] = {"state": s, "total_s": 0.0, "visits": 0}
        summary[s]["total_s"] += seg["duration_s"]
        summary[s]["visits"]  += 1

    return jsonify({
        "segments": segments,
        "summary":  sorted(summary.values(), key=lambda x: -x["total_s"]),
    })


@app.get("/missions/<mission_id>/summary")
def mission_summary(mission_id: str):
    """One-pass mission summary: header, duration, event counts, weed stats, insights."""
    p = _mission_log(mission_id)
    header: dict = {}
    event_counts: dict[str, int] = {}
    first_ts = last_ts = None
    weed_pts: list[dict] = []
    spray_n = 0
    n_lines = 0
    frames_with_detections = 0
    prev_ll: tuple[float, float] | None = None
    path_length_m = 0.0
    alts: list[float] = []

    for ev in _iter_events(p):
        n_lines += 1
        ev_type = ev.get("event", "")
        event_counts[ev_type] = event_counts.get(ev_type, 0) + 1
        ts = _parse_ts(ev.get("ts", ""))
        if ts > 0:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        if ev_type == "mission_start":
            header = ev
        if ev_type == "weed_detected":
            lat = (ev.get("weed") or {}).get("lat")
            lon = (ev.get("weed") or {}).get("lon")
            if lat and lon:
                weed_pts.append({"lat": float(lat), "lon": float(lon)})
        if ev_type in ("weed_sprayed", "spray_attempt"):
            spray_n += 1
        fr = ev.get("frame")
        if fr and (fr.get("detections") or []):
            frames_with_detections += 1
        if ev_type == "telemetry_sample":
            ds = ev.get("drone_state") or {}
            lat, lon = ds.get("latitude"), ds.get("longitude")
            if lat is not None and lon is not None:
                la, lo = float(lat), float(lon)
                if not (la == 0.0 and lo == 0.0):
                    if prev_ll is not None:
                        path_length_m += _haversine_m(prev_ll[0], prev_ll[1], la, lo)
                    prev_ll = (la, lo)
                alt = ds.get("altitude_rel_home")
                if alt is not None:
                    try:
                        alts.append(float(alt))
                    except (TypeError, ValueError):
                        pass

    duration_s = (last_ts - first_ts) if first_ts and last_ts else 0.0
    unique_weeds = len(_grid_dedup(weed_pts, 0.5))

    sim_truth_raw = header.get("sim_truth_file")
    sim_truth_file = Path(str(sim_truth_raw)).name if sim_truth_raw else None

    alt_min = min(alts) if alts else None
    alt_max = max(alts) if alts else None
    alt_mean = sum(alts) / len(alts) if alts else None
    db_writes = {k: v for k, v in event_counts.items() if k.startswith("db_")}

    insights = {
        "log_file_bytes":      p.stat().st_size,
        "jsonl_lines":         n_lines,
        "telemetry_samples":   event_counts.get("telemetry_sample", 0),
        "fsm_ticks":           event_counts.get("fsm_tick", 0),
        "fsm_transitions":     event_counts.get("fsm_transition", 0),
        "move_commands":       event_counts.get("move_command", 0),
        "frames_with_detections": frames_with_detections,
        "path_length_m":       round(path_length_m, 2),
        "altitude_rel_m_min":  round(alt_min, 3) if alt_min is not None else None,
        "altitude_rel_m_max":  round(alt_max, 3) if alt_max is not None else None,
        "altitude_rel_m_mean": round(alt_mean, 3) if alt_mean is not None else None,
        "db_writes":           db_writes,
    }

    return jsonify({
        "header":          header,
        "duration_s":      duration_s,
        "event_counts":    event_counts,
        "weed_detections": len(weed_pts),
        "unique_weeds":    unique_weeds,
        "spray_events":    spray_n,
        "sim_truth_file":  sim_truth_file,
        "insights":        insights,
    })


@app.get("/missions/<mission_id>/tail")
def mission_tail(mission_id: str):
    """Return new complete JSON lines since a byte offset — used by live mode."""
    p = _mission_log(mission_id)
    since_byte = int(request.args.get("since_byte", "0"))
    file_size = p.stat().st_size

    if since_byte >= file_size:
        return jsonify({"events": [], "next_byte": file_size, "file_size": file_size})

    with open(p, "rb") as f:
        f.seek(since_byte)
        chunk = f.read()

    # Only consume up to the last newline to avoid partial lines
    last_nl = chunk.rfind(b"\n")
    if last_nl == -1:
        return jsonify({"events": [], "next_byte": since_byte, "file_size": file_size})

    complete = chunk[: last_nl + 1]
    next_byte = since_byte + len(complete)

    events = []
    for raw in complete.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw.decode("utf-8", errors="replace")))
        except json.JSONDecodeError:
            pass

    return jsonify({"events": events, "next_byte": next_byte, "file_size": file_size})


@app.get("/missions/<mission_id>/frame_events")
def mission_frame_events(mission_id: str):
    """Events that have frame.detections with at least one detection."""
    p = _mission_log(mission_id)
    results = []
    for ev in _iter_events(p):
        frame = ev.get("frame")
        if not frame:
            continue
        dets = frame.get("detections") or []
        if not dets:
            continue
        raw_dets = frame.get("raw_detections")
        ds_obj = _drone_state_from_dict(ev.get("drone_state"))
        g_logged, g_note = _ground_project_list(dets, ds_obj)
        g_raw: list[dict] | None = None
        g_raw_note: str | None = None
        if raw_dets:
            g_raw, g_raw_note = _ground_project_list(raw_dets, ds_obj)
        note = g_note or g_raw_note

        # Project the 4 image corners to GPS — gives the camera footprint on the ground.
        footprint: list[dict] = []
        if ds_obj and ds_obj.altitude_rel_home > 0:
            W, H = 640, 640
            for u, v in [(0, 0), (W, 0), (W, H), (0, H)]:
                try:
                    pt = Detection(label="", confidence=0.0, bbox=[(u, v), (u, v)])
                    la, lo = detection_to_latlon(ds_obj, pt)
                    footprint.append({"lat": float(la), "lon": float(lo)})
                except Exception:
                    pass

        drone_pos = None
        if ds_obj:
            drone_pos = {"lat": ds_obj.latitude, "lon": ds_obj.longitude}

        results.append({
            "frame_index": len(results),
            "ts":         ev.get("ts"),
            "event":      ev.get("event"),
            "state_from": (ev.get("state_from") or "").replace("DroneStateEnum.", ""),
            "state_to":   (ev.get("state_to")   or "").replace("DroneStateEnum.", ""),
            "photo_path": frame.get("photo_path", ""),
            "detections": dets,
            "raw_detections": raw_dets if raw_dets else None,
            "drone_state": ev.get("drone_state"),
            "ground_projections": g_logged,
            "raw_ground_projections": g_raw if raw_dets else None,
            "ground_projection_note": note,
            "frame_footprint": footprint,
            "drone_pos": drone_pos,
        })
    return jsonify(results)


@app.get("/missions/<mission_id>/sim_vision")
def mission_sim_vision(mission_id: str):
    """Latest sim vision parameters event (if any)."""
    p = _mission_log(mission_id)
    latest = None
    for ev in _iter_events(p):
        if ev.get("event") == "sim_vision_params":
            latest = ev
    if latest is None:
        return jsonify(None)
    return jsonify(latest)


@app.get("/missions/<mission_id>/image")
def mission_image(mission_id: str):
    """Serve a real image file from within the mission directory."""
    if not mission_id.isdigit():
        abort(400)
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    mission_dir = (MISSIONS_ROOT / mission_id).resolve()
    try:
        target = (mission_dir / rel).resolve()
        target.relative_to(mission_dir)          # blocks path traversal
    except (ValueError, OSError):
        abort(403)
    if not target.is_file():
        abort(404)
    return send_file(target)


# ─── sim compare (unchanged logic, kept for compat) ───────────────────────────

@app.get("/missions/<mission_id>/sim_compare")
def mission_sim_compare(mission_id: str):
    truth_name = request.args.get("truth", "")
    thresh_m = float(request.args.get("thresh_m", "0.5"))
    if not truth_name or "/" in truth_name or "\\" in truth_name:
        abort(400)
    truth_path = SIM_DATA_ROOT / truth_name
    if not truth_path.exists():
        abort(404)

    data = json.loads(truth_path.read_text(encoding="utf-8"))
    raw_weeds = data.get("weed_locations", [])
    truth = []
    for i, w in enumerate(raw_weeds):
        if isinstance(w, dict):
            truth.append({"id": w.get("id", i), "lat": float(w["lat"]), "lon": float(w["lon"])})
        else:
            truth.append({"id": i, "lat": float(w[0]), "lon": float(w[1])})

    # Use deduplicated predictions for meaningful precision/recall
    pred = json.loads(mission_weeds_pred(mission_id).get_data(as_text=True))

    used: set[int] = set()
    tp = fp = 0
    for pr in pred:
        best_i, best_d = None, float("inf")
        for i, t in enumerate(truth):
            if i in used:
                continue
            d = _haversine_m(pr["lat"], pr["lon"], t["lat"], t["lon"])
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None and best_d <= thresh_m:
            tp += 1
            used.add(best_i)
        else:
            fp += 1
    fn = len(truth) - len(used)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0

    return jsonify({
        "truth_points": truth,
        "stats": {
            "truth": len(truth), "pred": len(pred),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall,
            "thresh_m": thresh_m,
        },
    })


_COMPARE_HTML = """<!doctype html>
<html><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Compare Missions – Skydock</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
  {{ SS | safe }}
  <style>
    #cmpMap{height:68vh;min-height:520px;max-height:820px;border-radius:8px}
    .col-a{color:#4a9eff}
    .col-b{color:#ff9a4a}
  </style>
</head><body>
<div class="container-fluid py-3" style="max-width:1300px">
  <div class="d-flex align-items-center justify-content-between mb-3">
    <div>
      <h2 class="mb-0">Compare Missions</h2>
      <div class="muted small">Select two missions to compare side-by-side</div>
    </div>
    <div class="d-flex gap-2 align-items-center">
      <a href="{{ url_for('missions_list') }}" class="btn btn-sm btn-outline-secondary">&#9776; All missions</a>
      <button id="themeBtn"></button>
    </div>
  </div>

  <!-- selectors -->
  <div class="card p-3 mb-3">
    <div class="row g-3 align-items-end">
      <div class="col-12 col-sm-auto">
        <label class="form-label muted small mb-1">
          <span class="col-a">■</span> Mission A
        </label>
        <select id="selA" class="form-select form-select-sm" style="min-width:160px">
          <option value="">— select —</option>
          {% for m in missions %}
            <option value="{{ m.id }}"{% if m.id == sel_a %} selected{% endif %}>
              Mission {{ m.id }}
            </option>
          {% endfor %}
        </select>
      </div>
      <div class="col-12 col-sm-auto">
        <label class="form-label muted small mb-1">
          <span class="col-b">■</span> Mission B
        </label>
        <select id="selB" class="form-select form-select-sm" style="min-width:160px">
          <option value="">— select —</option>
          {% for m in missions %}
            <option value="{{ m.id }}"{% if m.id == sel_b %} selected{% endif %}>
              Mission {{ m.id }}
            </option>
          {% endfor %}
        </select>
      </div>
      <div class="col-12 col-sm-auto">
        <label class="form-label muted small mb-1">Truth file (optional)</label>
        <select id="selTruth" class="form-select form-select-sm" style="min-width:180px">
          <option value="">(no truth file)</option>
          {% for f in sim_files %}
            <option value="{{ f }}">{{ f }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-12 col-sm-auto">
        <button id="runBtn" class="btn btn-sm btn-primary">Compare</button>
      </div>
      <div class="col-12 col-sm-auto">
        <div class="form-check mt-4">
          <input class="form-check-input" type="checkbox" id="cmpBboxGround">
          <label class="form-check-label small" for="cmpBboxGround">Show camera bbox on ground</label>
        </div>
      </div>
    </div>
  </div>

  <div id="results" class="d-none">

    <!-- summary cards -->
    <div class="row g-3 mb-3" id="summaryRow"></div>

    <!-- map -->
    <div class="card p-3 mb-3">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <h6 class="mb-0">Weed locations &amp; flight paths</h6>
        <div class="d-flex gap-3 small flex-wrap">
          <span><span class="col-a">&#9679;</span> Mission A weeds</span>
          <span><span class="col-b">&#9679;</span> Mission B weeds</span>
          <span><span style="color:#4a9eff">—</span> Path A</span>
          <span><span style="color:#ff9a4a">—</span> Path B</span>
          <span><span style="color:#ffffff">&#9711;</span> Ground truth</span>
          <span class="d-none" id="cmpBboxLegend"><span style="color:#4a9eff">▢</span> A bbox &nbsp; <span style="color:#ff9a4a">▢</span> B bbox</span>
        </div>
      </div>
      <div id="cmpMap"></div>
      <div id="cmpBboxNote" class="muted small mt-2 d-none" style="min-height:1.3em"></div>
    </div>

    <!-- charts row -->
    <div class="row g-3 mb-3">
      <div class="col-12 col-lg-6">
        <div class="card p-3">
          <h6>FSM state time (seconds)</h6>
          <div id="fsmChart" style="height:300px"></div>
        </div>
      </div>
      <div class="col-12 col-lg-6">
        <div class="card p-3">
          <h6>Event counts</h6>
          <div id="evChart" style="height:300px"></div>
        </div>
      </div>
    </div>

    <!-- detailed stats table -->
    <div class="card p-3 mb-3">
      <h6>Side-by-side stats</h6>
      <div class="table-responsive">
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5" id="statsTable">
        </table>
      </div>
    </div>

    <!-- accuracy (shown only when truth file selected) -->
    <div class="card p-3 mb-3 d-none" id="accuracyCard">
      <h6>Accuracy vs ground truth</h6>
      <div class="table-responsive">
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5" id="accuracyTable">
        </table>
      </div>
    </div>

  </div><!-- /results -->

  <div id="loadingMsg" class="muted small d-none">Loading…</div>
  <div id="errorMsg"   class="text-danger small d-none"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const STATE_COLORS = {
  SCAN:"#4a9eff", SPRAY:"#4adf86", HOMING:"#ff9a4a",
  GOTO:"#bf4aff", OVERRIDE:"#9fb0c7", LAND:"#ff4a4a",
};
function stateColor(s){ return STATE_COLORS[s]||"#7db3ff"; }
async function api(url){ const r=await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json(); }
function fmtDur(s){ const m=Math.floor(s/60),sec=Math.round(s%60); return m?`${m}m ${sec}s`:`${sec}s`; }
function pct(v,t){ return t?((v/t)*100).toFixed(1)+"%" : "—"; }

let cmpMap=null;
let cmpBboxLayerA=null, cmpBboxLayerB=null;

function escCmp(s){
  return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function buildCmpFootprintGroup(frames, baseColor, tag){
  const g = L.layerGroup();
  (frames||[]).forEach(f=>{
    (f.ground_projections||[]).forEach(p=>{
      const c = p.center;
      if(c && c.lat!=null && c.lon!=null){
        L.circleMarker([c.lat,c.lon],{
          radius:4, color:baseColor, fillColor:baseColor, fillOpacity:0.4, weight:1
        }).bindPopup(`Mission ${tag} · ${escCmp(p.label||"?")}`).addTo(g);
      }
      const corners = p.corners||[];
      if(corners.length >= 3){
        const pts = corners.map(q=>[q.lat,q.lon]);
        L.polygon(pts,{
          color:baseColor, fillColor:baseColor, fillOpacity:0.1, weight:1
        }).bindPopup(`Mission ${tag} · ${escCmp(p.label||"?")}`).addTo(g);
      }
    });
  });
  return g;
}

function countFootprints(frames){
  let n = 0;
  (frames||[]).forEach(f=>{ n += (f.ground_projections||[]).length; });
  return n;
}

async function applyCmpBboxGround(){
  const midA = document.getElementById("selA").value;
  const midB = document.getElementById("selB").value;
  const on = document.getElementById("cmpBboxGround") && document.getElementById("cmpBboxGround").checked;
  const leg = document.getElementById("cmpBboxLegend");
  const note = document.getElementById("cmpBboxNote");
  if(leg) leg.classList.toggle("d-none", !on);
  if(!cmpMap) return;
  if(cmpBboxLayerA){ try{ cmpMap.removeLayer(cmpBboxLayerA); }catch(e){} cmpBboxLayerA=null; }
  if(cmpBboxLayerB){ try{ cmpMap.removeLayer(cmpBboxLayerB); }catch(e){} cmpBboxLayerB=null; }
  if(note){ note.classList.add("d-none"); note.textContent=""; }
  if(!on || !midA || !midB) return;
  const [fa, fb] = await Promise.all([
    api(`/missions/${midA}/frame_events`),
    api(`/missions/${midB}/frame_events`),
  ]);
  const na = countFootprints(fa), nb = countFootprints(fb);
  if(note){
    note.classList.remove("d-none");
    if(!fa.length && !fb.length){
      note.innerHTML = "BBox ground: <b>no frame events</b> in either log. Re-run missions with current FSM (frame snapshots on ticks).";
    } else if(!na && !nb){
      const hA = (fa[0] && fa[0].ground_projection_note) ? ` A: ${fa[0].ground_projection_note}` : "";
      const hB = (fb[0] && fb[0].ground_projection_note) ? ` B: ${fb[0].ground_projection_note}` : "";
      note.innerHTML = "BBox ground: frames exist but <b>no footprints</b> (GPS + altitude needed)."+hA+hB;
    } else {
      note.textContent = `BBox ground: Mission A ${na} footprint(s), Mission B ${nb} footprint(s).`;
    }
  }
  cmpBboxLayerA = buildCmpFootprintGroup(fa, "#4a9eff", "A");
  cmpBboxLayerB = buildCmpFootprintGroup(fb, "#ff9a4a", "B");
  cmpBboxLayerA.addTo(cmpMap);
  cmpBboxLayerB.addTo(cmpMap);
}

function initMap(){
  if(cmpMap){ cmpMap.remove(); cmpMap=null; }
  cmpMap = L.map("cmpMap");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {attribution:"© OpenStreetMap",maxZoom:22}).addTo(cmpMap);
}

async function runCompare(){
  const midA  = document.getElementById("selA").value;
  const midB  = document.getElementById("selB").value;
  let truth = document.getElementById("selTruth").value;
  if(!midA||!midB){ alert("Select both missions first."); return; }
  if(midA===midB){ alert("Select two different missions."); return; }

  document.getElementById("loadingMsg").classList.remove("d-none");
  document.getElementById("errorMsg").classList.add("d-none");
  document.getElementById("results").classList.add("d-none");

  try {
    const [sumA,sumB,tlA,tlB,predsA,predsB,pathA,pathB] = await Promise.all([
      api(`/missions/${midA}/summary`),
      api(`/missions/${midB}/summary`),
      api(`/missions/${midA}/timeline`),
      api(`/missions/${midB}/timeline`),
      api(`/missions/${midA}/weeds/pred?dedup=1`),
      api(`/missions/${midB}/weeds/pred?dedup=1`),
      api(`/missions/${midA}/path?stride=1`),
      api(`/missions/${midB}/path?stride=1`),
    ]);

    // Determine truth file per mission: manual selection overrides, else each mission's own
    const manualTruth = document.getElementById("selTruth").value;
    const truthA = manualTruth || sumA.sim_truth_file || "";
    const truthB = manualTruth || sumB.sim_truth_file || "";
    // Update dropdown if both use the same auto-detected file
    if(!manualTruth && truthA && truthA === truthB)
      document.getElementById("selTruth").value = truthA;

    // accuracy — each mission uses its own truth file
    let accA=null, accB=null, truthPtsA=[], truthPtsB=[];
    const [cmpResA, cmpResB] = await Promise.all([
      truthA ? api(`/missions/${midA}/sim_compare?truth=${encodeURIComponent(truthA)}&thresh_m=0.5`).catch(()=>null) : Promise.resolve(null),
      truthB ? api(`/missions/${midB}/sim_compare?truth=${encodeURIComponent(truthB)}&thresh_m=0.5`).catch(()=>null) : Promise.resolve(null),
    ]);
    if(cmpResA){ accA=cmpResA.stats; truthPtsA=cmpResA.truth_points||[]; }
    if(cmpResB){ accB=cmpResB.stats; truthPtsB=cmpResB.truth_points||[]; }

    renderSummaryCards(midA, midB, sumA, sumB);
    renderMap(pathA, pathB, predsA, predsB, truthPtsA, truthPtsB, truthA===truthB);
    renderFsmChart(midA, midB, tlA.summary, tlB.summary);
    renderEvChart(midA, midB, sumA.event_counts, sumB.event_counts);
    renderStatsTable(midA, midB, sumA, sumB, tlA.summary, tlB.summary);
    if(accA || accB){
      renderAccuracy(midA, midB, accA, accB, truthA, truthB);
      document.getElementById("accuracyCard").classList.remove("d-none");
    } else {
      document.getElementById("accuracyCard").classList.add("d-none");
    }

    document.getElementById("results").classList.remove("d-none");
    if(cmpMap) cmpMap.invalidateSize();
  } catch(e){
    document.getElementById("errorMsg").textContent = "Error: "+e;
    document.getElementById("errorMsg").classList.remove("d-none");
  } finally {
    document.getElementById("loadingMsg").classList.add("d-none");
  }
}

// ── summary cards ─────────────────────────────────────────────────────────────
function renderSummaryCards(midA, midB, sumA, sumB){
  function card(mid, sum, colorClass){
    const h = sum.header||{};
    return `<div class="col-12 col-md-6">
      <div class="card p-3">
        <h6 class="${colorClass}">Mission ${mid}
          <span class="muted" style="font-weight:400;font-size:12px">
            &nbsp;${h.is_sim?'SIM':'REAL'}</span></h6>
        <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
          <tr><td>Duration</td>          <td><b>${fmtDur(sum.duration_s)}</b></td></tr>
          <tr><td>Weed detections</td>   <td><b>${sum.weed_detections}</b></td></tr>
          <tr><td>Unique weeds</td>      <td><b>${sum.unique_weeds}</b></td></tr>
          <tr><td>Spray events</td>      <td><b>${sum.spray_events}</b></td></tr>
          <tr><td>Total events</td>
              <td><b>${Object.values(sum.event_counts||{}).reduce((a,v)=>a+v,0)}</b></td></tr>
          ${h.sim_truth_file?`<tr><td>Truth file</td>
              <td><code style="font-size:11px">${h.sim_truth_file}</code></td></tr>`:""}
        </table>
      </div>
    </div>`;
  }
  document.getElementById("summaryRow").innerHTML =
    card(midA, sumA, "col-a") + card(midB, sumB, "col-b");
}

// ── map ───────────────────────────────────────────────────────────────────────
function renderMap(pathA, pathB, predsA, predsB, truthPtsA, truthPtsB, sameTruth){
  initMap();
  const coordsA = pathA.filter(p=>p.lat||p.lon).map(p=>[p.lat,p.lon]);
  const coordsB = pathB.filter(p=>p.lat||p.lon).map(p=>[p.lat,p.lon]);
  if(coordsA.length) L.polyline(coordsA,{color:"#4a9eff",weight:2,opacity:0.7}).addTo(cmpMap);
  if(coordsB.length) L.polyline(coordsB,{color:"#ff9a4a",weight:2,opacity:0.7}).addTo(cmpMap);
  for(const p of predsA)
    L.circleMarker([p.lat,p.lon],{radius:5,color:"#4a9eff",fillColor:"#4a9eff",fillOpacity:0.5,weight:1.5})
     .bindPopup(`A weed<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`).addTo(cmpMap);
  for(const p of predsB)
    L.circleMarker([p.lat,p.lon],{radius:5,color:"#ff9a4a",fillColor:"#ff9a4a",fillOpacity:0.5,weight:1.5})
     .bindPopup(`B weed<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`).addTo(cmpMap);
  // Truth points: white hollow if same file, else A=blue outline, B=orange outline
  const shownTruth = new Set();
  for(const p of truthPtsA){
    const key = `${p.lat.toFixed(7)},${p.lon.toFixed(7)}`;
    const color = sameTruth ? "#ffffff" : "#4a9eff";
    L.circleMarker([p.lat,p.lon],{radius:7,color,fillColor:"transparent",fillOpacity:0,weight:2})
     .bindPopup(`Truth weed<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`).addTo(cmpMap);
    shownTruth.add(key);
  }
  if(!sameTruth) for(const p of truthPtsB){
    const key = `${p.lat.toFixed(7)},${p.lon.toFixed(7)}`;
    if(shownTruth.has(key)) continue;
    L.circleMarker([p.lat,p.lon],{radius:7,color:"#ff9a4a",fillColor:"transparent",fillOpacity:0,weight:2})
     .bindPopup(`Truth weed<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`).addTo(cmpMap);
  }
  const all = [...coordsA,...coordsB,...predsA.map(p=>[p.lat,p.lon]),...predsB.map(p=>[p.lat,p.lon]),...truthPtsA.map(p=>[p.lat,p.lon])];
  if(all.length) cmpMap.fitBounds(L.latLngBounds(all),{padding:[30,30]});
  else cmpMap.setView([0,0],2);
  const cb = document.getElementById("cmpBboxGround");
  if(cb && cb.checked) applyCmpBboxGround().catch(console.error);
}

// ── FSM grouped bar ───────────────────────────────────────────────────────────
function renderFsmChart(midA, midB, sumA, sumB){
  const statesA = Object.fromEntries(sumA.map(s=>[s.state,s.total_s]));
  const statesB = Object.fromEntries(sumB.map(s=>[s.state,s.total_s]));
  const allStates = [...new Set([...Object.keys(statesA),...Object.keys(statesB)])];
  allStates.sort();
  const trA = {
    name:`Mission ${midA}`, type:"bar",
    x: allStates, y: allStates.map(s=>statesA[s]||0),
    marker:{color:"#4a9eff"},
    hovertemplate:"%{x}<br>%{y:.1f}s<extra>A</extra>",
  };
  const trB = {
    name:`Mission ${midB}`, type:"bar",
    x: allStates, y: allStates.map(s=>statesB[s]||0),
    marker:{color:"#ff9a4a"},
    hovertemplate:"%{x}<br>%{y:.1f}s<extra>B</extra>",
  };
  const cc1 = chartColors();
  Plotly.newPlot("fsmChart",[trA,trB],{
    paper_bgcolor:cc1.bg, plot_bgcolor:cc1.bg,
    font:{color:cc1.text}, barmode:"group",
    xaxis:{gridcolor:cc1.grid,color:cc1.axis},
    yaxis:{title:"seconds",gridcolor:cc1.grid,color:cc1.axis},
    legend:{orientation:"h",x:0,y:-0.25},
    margin:{l:50,r:10,t:10,b:60},
  },{displayModeBar:false,responsive:true});
}

// ── event count bar ───────────────────────────────────────────────────────────
function renderEvChart(midA, midB, evA, evB){
  const interested = ["telemetry_sample","fsm_tick","fsm_transition",
                      "move_command","weed_detected","weed_sprayed",
                      "spray_attempt","spray_miss"];
  const keys = interested.filter(k=>(evA[k]||0)+(evB[k]||0)>0);
  const trA={name:`Mission ${midA}`,type:"bar",
    x:keys,y:keys.map(k=>evA[k]||0),marker:{color:"#4a9eff"},
    hovertemplate:"%{x}<br>%{y}<extra>A</extra>"};
  const trB={name:`Mission ${midB}`,type:"bar",
    x:keys,y:keys.map(k=>evB[k]||0),marker:{color:"#ff9a4a"},
    hovertemplate:"%{x}<br>%{y}<extra>B</extra>"};
  const cc2 = chartColors();
  Plotly.newPlot("evChart",[trA,trB],{
    paper_bgcolor:cc2.bg, plot_bgcolor:cc2.bg,
    font:{color:cc2.text}, barmode:"group",
    xaxis:{gridcolor:cc2.grid,color:cc2.axis,tickangle:-30},
    yaxis:{gridcolor:cc2.grid,color:cc2.axis},
    legend:{orientation:"h",x:0,y:-0.35},
    margin:{l:50,r:10,t:10,b:80},
  },{displayModeBar:false,responsive:true});
}

// ── detailed stats table ──────────────────────────────────────────────────────
function renderStatsTable(midA, midB, sumA, sumB, tlA, tlB){
  const statesA = Object.fromEntries(tlA.map(s=>[s.state,s]));
  const statesB = Object.fromEntries(tlB.map(s=>[s.state,s]));
  const allStates = [...new Set([...Object.keys(statesA),...Object.keys(statesB)])];

  function diff(a,b,higherIsBetter=true){
    if(a===b) return '<span class="same">→</span>';
    if((higherIsBetter && b>a)||(!higherIsBetter && b<a))
      return `<span class="better">▲ ${b>a?"+":""}${typeof a==="number"?(b-a).toFixed(1):""}</span>`;
    return `<span class="worse">▼ ${typeof a==="number"?(b-a).toFixed(1):""}</span>`;
  }

  let html = `<thead><tr>
    <th>Metric</th>
    <th class="col-a">Mission ${midA}</th>
    <th class="col-b">Mission ${midB}</th>
    <th>Δ (B vs A)</th>
  </tr></thead><tbody>`;

  const rows = [
    ["Duration",         fmtDur(sumA.duration_s),      fmtDur(sumB.duration_s),      diff(sumA.duration_s,sumB.duration_s,false)],
    ["Weed detections",  sumA.weed_detections,          sumB.weed_detections,          diff(sumA.weed_detections,sumB.weed_detections,true)],
    ["Unique weeds",     sumA.unique_weeds,             sumB.unique_weeds,             diff(sumA.unique_weeds,sumB.unique_weeds,true)],
    ["Spray events",     sumA.spray_events,             sumB.spray_events,             diff(sumA.spray_events,sumB.spray_events,true)],
  ];

  for(const state of allStates){
    const sA = statesA[state], sB = statesB[state];
    const tA = sA?sA.total_s:0, tB = sB?sB.total_s:0;
    const vA = sA?`${fmtDur(tA)} (${sA.visits} visit${sA.visits!==1?"s":""})`:"—";
    const vB = sB?`${fmtDur(tB)} (${sB.visits} visit${sB.visits!==1?"s":""})`:"—";
    const c  = stateColor(state);
    rows.push([
      `<span class="badge-state" style="background:${c}22;color:${c};border:1px solid ${c}66">${state}</span>`,
      vA, vB, sA&&sB ? diff(tA,tB,false) : "—",
    ]);
  }

  for(const [label,vA,vB,delta] of rows)
    html += `<tr><td>${label}</td><td>${vA}</td><td>${vB}</td><td>${delta}</td></tr>`;

  html += "</tbody>";
  document.getElementById("statsTable").innerHTML = html;
}

// ── accuracy table ────────────────────────────────────────────────────────────
function renderAccuracy(midA, midB, accA, accB, truthA, truthB){
  function fmtPct(v){ return (v*100).toFixed(1)+"%"; }
  function f1(s){ return (s&&s.precision+s.recall>0) ? 2*s.precision*s.recall/(s.precision+s.recall):0; }
  function diffPct(a,b){
    const d = ((b-a)*100).toFixed(1);
    if(Math.abs(b-a)<0.001) return '<span class="same">→</span>';
    return b>a ? `<span class="better">▲ +${d}%</span>` : `<span class="worse">▼ ${d}%</span>`;
  }
  const na = "—";
  function val(s, fn){ return s ? fn(s) : na; }

  const diffTruth = truthA && truthB && truthA !== truthB;
  const truthLabel = diffTruth
    ? `<span class="col-a">${truthA}</span> / <span class="col-b">${truthB}</span>`
    : `<code>${truthA || truthB}</code>`;

  let html = `<div class="muted small mb-2">Truth: ${truthLabel} &nbsp; match radius: 0.5 m</div>
  <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
  <thead><tr>
    <th>Metric</th>
    <th class="col-a">Mission ${midA}${diffTruth?` <span class="muted" style="font-size:10px">(${truthA})</span>`:""}</th>
    <th class="col-b">Mission ${midB}${diffTruth?` <span class="muted" style="font-size:10px">(${truthB})</span>`:""}</th>
    <th>Δ (B vs A)</th>
  </tr></thead><tbody>`;

  const rows = [
    ["Truth weeds",    val(accA,s=>s.truth),      val(accB,s=>s.truth),      na],
    ["Predictions",    val(accA,s=>s.pred),        val(accB,s=>s.pred),       na],
    ["True positives", val(accA,s=>s.tp),          val(accB,s=>s.tp),         (accA&&accB)?diffPct(accA.tp/accA.truth,accB.tp/accB.truth):na],
    ["False positives",val(accA,s=>s.fp),          val(accB,s=>s.fp),         (accA&&accB)?diffPct(accA.fp/(accA.pred||1),accB.fp/(accB.pred||1)):na],
    ["False negatives",val(accA,s=>s.fn),          val(accB,s=>s.fn),         na],
    ["Precision",      val(accA,s=>fmtPct(s.precision)), val(accB,s=>fmtPct(s.precision)), (accA&&accB)?diffPct(accA.precision,accB.precision):na],
    ["Recall",         val(accA,s=>fmtPct(s.recall)),    val(accB,s=>fmtPct(s.recall)),    (accA&&accB)?diffPct(accA.recall,accB.recall):na],
    ["F1 score",       val(accA,s=>fmtPct(f1(s))),       val(accB,s=>fmtPct(f1(s))),       (accA&&accB)?diffPct(f1(accA),f1(accB)):na],
  ];
  for(const [l,a,b,d] of rows)
    html += `<tr><td>${l}</td><td>${a}</td><td>${b}</td><td>${d}</td></tr>`;
  html += "</tbody></table>";
  document.getElementById("accuracyCard").innerHTML = "<h6>Accuracy vs ground truth</h6>" + html;
}

// ── init ─────────────────────────────────────────────────────────────────────
document.getElementById("runBtn").addEventListener("click", ()=>{
  runCompare().catch(e=>{
    document.getElementById("errorMsg").textContent="Error: "+e;
    document.getElementById("errorMsg").classList.remove("d-none");
    document.getElementById("loadingMsg").classList.add("d-none");
  });
});

const cmpBboxChk = document.getElementById("cmpBboxGround");
if(cmpBboxChk) cmpBboxChk.addEventListener("change", ()=>{
  applyCmpBboxGround().catch(console.error);
});

// Auto-run if both pre-selected via URL
const selA = document.getElementById("selA").value;
const selB = document.getElementById("selB").value;
if(selA && selB) runCompare();
</script>
{{ TJ | safe }}
</body></html>"""


@app.get("/compare")
def compare_page():
    missions = [
        {"id": d.name}
        for d in _mission_paths()
        if (d / "mission.jsonl").exists()
    ]
    sel_a = request.args.get("a", "")
    sel_b = request.args.get("b", "")
    # Default: pre-select the two most recent missions
    if not sel_a and not sel_b and len(missions) >= 2:
        sel_a = missions[-2]["id"]
        sel_b = missions[-1]["id"]
    return render_template_string(
        _COMPARE_HTML,
        missions=missions,
        sim_files=_sim_files(),
        sel_a=sel_a,
        sel_b=sel_b,
        SS=_SHARED_STYLE,
        TJ=_THEME_JS,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    missions = sorted(MISSIONS_ROOT.glob("*/mission.jsonl")) if MISSIONS_ROOT.exists() else []
    print(f"\n  MISSIONS_ROOT : {MISSIONS_ROOT}  ({'exists' if MISSIONS_ROOT.exists() else 'MISSING'})")
    print(f"  SIM_DATA_ROOT : {SIM_DATA_ROOT}  ({'exists' if SIM_DATA_ROOT.exists() else 'missing'})")
    if missions:
        print(f"  Mission files :")
        for m in missions:
            size_kb = m.stat().st_size // 1024
            print(f"    {m}  ({size_kb} KB)")
    else:
        print(f"  Mission files : (none found)")
    print()
    app.run(host="0.0.0.0", port=port, debug=True)
