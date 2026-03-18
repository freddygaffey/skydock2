import json
import math
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # skydock2/

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
                  <span class="muted small">{{ m.path }}</span>
                </div>
              </a>
            {% else %}
              <div class="list-group-item">
                <b>{{ m.id }}</b> <span class="muted small">(no mission.jsonl)</span>
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
        <div class="muted small mb-2">Files in <code>sim_data/</code>:</div>
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
  <div id="summaryBar" class="mb-3">
    <span class="muted small">Loading…</span>
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
          <button id="tileToggle" class="btn btn-sm btn-outline-secondary">Satellite</button>
        </div>
      </div>
      <div id="map"></div>
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
          <div id="frameInfo" class="muted small mb-2" style="min-height:1.4em">
            Click a frame in the list to view
          </div>
          <canvas id="frameCanvas" width="640" height="640"></canvas>
        </div>
      </div>
    </div>

    <!-- ── REPORT ─────────────────────────────────────────────────────── -->
    <div class="tab-pane fade" id="tabReport">
      <div id="reportContent">
        <div class="muted small">Open this tab to load the report.</div>
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

// ── summary bar ─────────────────────────────────────────────────────────────
let _summary = null;
async function loadSummary(){
  _summary = await api(`/missions/${MID}/summary`);
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
  // Auto-select linked truth file
  if(_summary.sim_truth_file){
    const sel = document.getElementById("truthFile");
    for(const opt of sel.options)
      if(opt.value === _summary.sim_truth_file){ sel.value = _summary.sim_truth_file; break; }
  }
}

// ═══════════════════════════ MAP TAB ════════════════════════════════════════
let map, layerPath=null, layerPred=null, layerTruth=null, layerSpray=null;
let osmTile, satTile, usingSat=false;

function initMap(){
  map = L.map("map");
  osmTile = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {attribution:"© OpenStreetMap contributors", maxZoom:19}
  );
  satTile = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {attribution:"Tiles © Esri", maxZoom:19}
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
  document.getElementById("runCompare").addEventListener("click", ()=>{
    loadTruth().catch(err=>alert(err));
  });
}

async function loadMap(){
  const [pathPts, predPts, sprayEvs] = await Promise.all([
    api(`/missions/${MID}/path?stride=5`),
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
    }).bindPopup(`Truth weed<br>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`)
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

  function drawBoxes(){
    for(const det of (f.detections||[])){
      if(!det.bbox||det.bbox.length<2) continue;
      const [[x0,y0],[x1,y1]] = det.bbox;
      const color = labelColor(det.label||"?");
      ctx.strokeStyle=color; ctx.lineWidth=2;
      ctx.strokeRect(x0,y0,x1-x0,y1-y0);
      const lbl=`${det.label||"?"} ${((det.confidence||0)*100).toFixed(0)}%`;
      ctx.font="12px monospace";
      const tw=ctx.measureText(lbl).width;
      ctx.fillStyle=color+"cc"; ctx.fillRect(x0,y0-16,tw+6,16);
      ctx.fillStyle="#fff";     ctx.fillText(lbl,x0+3,y0-3);
    }
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
    if(t==="#tabFrames")   loadFrames().catch(console.error);
    if(t==="#tabReport")   loadReport().catch(console.error);
    if(t==="#tabMap")      { if(map) map.invalidateSize(); }
  });
});

// ═══════════════════════ INIT ════════════════════════════════════════════════
(async ()=>{
  await loadSummary();
  initMap();
  await loadMap();
  // Auto-run truth comparison if linked in mission header
  if(_summary && _summary.sim_truth_file){
    document.getElementById("layerTruth").checked = true;
    await loadTruth();
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
    """Downsampled drone path from telemetry_sample events."""
    p = _mission_log(mission_id)
    stride = max(1, int(request.args.get("stride", "10")))
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
    """One-pass mission summary: header, duration, event counts, weed stats."""
    p = _mission_log(mission_id)
    header: dict = {}
    event_counts: dict[str, int] = {}
    first_ts = last_ts = None
    weed_pts: list[dict] = []
    spray_n = 0

    for ev in _iter_events(p):
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

    duration_s = (last_ts - first_ts) if first_ts and last_ts else 0.0
    unique_weeds = len(_grid_dedup(weed_pts, 0.5))

    sim_truth_raw = header.get("sim_truth_file")
    sim_truth_file = Path(str(sim_truth_raw)).name if sim_truth_raw else None

    return jsonify({
        "header":          header,
        "duration_s":      duration_s,
        "event_counts":    event_counts,
        "weed_detections": len(weed_pts),
        "unique_weeds":    unique_weeds,
        "spray_events":    spray_n,
        "sim_truth_file":  sim_truth_file,
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
        results.append({
            "ts":         ev.get("ts"),
            "event":      ev.get("event"),
            "state_from": (ev.get("state_from") or "").replace("DroneStateEnum.", ""),
            "state_to":   (ev.get("state_to")   or "").replace("DroneStateEnum.", ""),
            "photo_path": frame.get("photo_path", ""),
            "detections": dets,
            "drone_state": ev.get("drone_state"),
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
    truth = [{"lat": float(la), "lon": float(lo)} for la, lo in data.get("weed_locations", [])]

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
    </div>
  </div>

  <div id="results" class="d-none">

    <!-- summary cards -->
    <div class="row g-3 mb-3" id="summaryRow"></div>

    <!-- map -->
    <div class="card p-3 mb-3">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <h6 class="mb-0">Weed locations &amp; flight paths</h6>
        <div class="d-flex gap-3 small">
          <span><span class="col-a">&#9679;</span> Mission A weeds</span>
          <span><span class="col-b">&#9679;</span> Mission B weeds</span>
          <span><span style="color:#4a9eff">—</span> Path A</span>
          <span><span style="color:#ff9a4a">—</span> Path B</span>
        </div>
      </div>
      <div id="cmpMap"></div>
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

function initMap(){
  if(cmpMap){ cmpMap.remove(); cmpMap=null; }
  cmpMap = L.map("cmpMap");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {attribution:"© OpenStreetMap",maxZoom:19}).addTo(cmpMap);
}

async function runCompare(){
  const midA  = document.getElementById("selA").value;
  const midB  = document.getElementById("selB").value;
  const truth = document.getElementById("selTruth").value;
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
      api(`/missions/${midA}/path?stride=5`),
      api(`/missions/${midB}/path?stride=5`),
    ]);

    // accuracy
    let accA=null, accB=null;
    if(truth){
      [accA,accB] = await Promise.all([
        api(`/missions/${midA}/sim_compare?truth=${encodeURIComponent(truth)}&thresh_m=0.5`).then(r=>r.stats).catch(()=>null),
        api(`/missions/${midB}/sim_compare?truth=${encodeURIComponent(truth)}&thresh_m=0.5`).then(r=>r.stats).catch(()=>null),
      ]);
    }

    renderSummaryCards(midA, midB, sumA, sumB);
    renderMap(pathA, pathB, predsA, predsB);
    renderFsmChart(midA, midB, tlA.summary, tlB.summary);
    renderEvChart(midA, midB, sumA.event_counts, sumB.event_counts);
    renderStatsTable(midA, midB, sumA, sumB, tlA.summary, tlB.summary);
    if(truth && accA && accB){
      renderAccuracy(midA, midB, accA, accB, truth);
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
function renderMap(pathA, pathB, predsA, predsB){
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
  const all = [...coordsA,...coordsB,...predsA.map(p=>[p.lat,p.lon]),...predsB.map(p=>[p.lat,p.lon])];
  if(all.length) cmpMap.fitBounds(L.latLngBounds(all),{padding:[30,30]});
  else cmpMap.setView([0,0],2);
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
function renderAccuracy(midA, midB, accA, accB, truth){
  function fmtPct(v){ return (v*100).toFixed(1)+"%"; }
  function f1(s){ return (s.precision+s.recall)>0 ? 2*s.precision*s.recall/(s.precision+s.recall):0; }

  function diffPct(a,b){
    const d = ((b-a)*100).toFixed(1);
    if(Math.abs(b-a)<0.001) return '<span class="same">→</span>';
    return b>a ? `<span class="better">▲ +${d}%</span>` : `<span class="worse">▼ ${d}%</span>`;
  }

  let html = `<div class="muted small mb-2">Truth: <code>${truth}</code> &nbsp; match radius: 0.5 m</div>
  <table class="table table-sm stats-tbl mb-0" style="color:#e8edf5">
  <thead><tr>
    <th>Metric</th>
    <th class="col-a">Mission ${midA}</th>
    <th class="col-b">Mission ${midB}</th>
    <th>Δ (B vs A)</th>
  </tr></thead><tbody>`;

  const rows = [
    ["Truth weeds",    accA.truth,          accB.truth,          "—"],
    ["Predictions",    accA.pred,           accB.pred,           "—"],
    ["True positives", accA.tp,             accB.tp,             diffPct(accA.tp/accA.truth,accB.tp/accB.truth)],
    ["False positives",accA.fp,             accB.fp,             diffPct(accA.fp/(accA.pred||1),accB.fp/(accB.pred||1))],
    ["False negatives",accA.fn,             accB.fn,             "—"],
    ["Precision",      fmtPct(accA.precision), fmtPct(accB.precision), diffPct(accA.precision,accB.precision)],
    ["Recall",         fmtPct(accA.recall),    fmtPct(accB.recall),    diffPct(accA.recall,accB.recall)],
    ["F1 score",       fmtPct(f1(accA)),       fmtPct(f1(accB)),       diffPct(f1(accA),f1(accB))],
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
    app.run(host="0.0.0.0", port=port, debug=False)
