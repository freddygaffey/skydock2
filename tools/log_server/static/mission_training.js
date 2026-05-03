/* Training data review UI */
'use strict';

// Set by inline boot in mission_training.html (JSON.parse — avoids HTML escaping bugs).
const MISSION_ID = String(window.MISSION_ID || '');
const SRC = String(window.SRC || 'sim');
const TRAINING_AUTO_SETUP =
  window.TRAINING_AUTO_SETUP != null ? String(window.TRAINING_AUTO_SETUP) : '';

// State
let frames = [];         // all frame result dicts from server
let decisions = {};      // timestamp_ns -> 'approved' | 'skipped'
let decisionHistory = []; // { ts, prev: 'approved'|'skipped'|null } for undo (null = had no decision)
let currentIdx = -1;

// Thresholds (mirrored from sliders — re-evaluate locally without re-running inference)
let confThresh = 0.60;
let distThresh = 80;
let frameStride = 1;

// Elements
const canvas      = document.getElementById('mainCanvas');
const ctx2d       = canvas.getContext('2d');
let canvasLoadToken = 0;
let canvasBaseImage = null;

/** Filmstrip: small decode. Main canvas: longest edge (matches labeling grid after drawImage stretch). */
const FILMSTRIP_MAX_SIDE = 128;
const CANVAS_MAX_SIDE = 640;
const CANVAS_IMAGE_CACHE_MAX = 32;

function frameImageSrcFilmstrip(f) {
  return (
    `/missions/${MISSION_ID}/image?path=${encodeURIComponent(f.frame_path)}&src=${SRC}` +
    `&max_side=${FILMSTRIP_MAX_SIDE}`
  );
}

function frameImageSrcCanvas(f) {
  return (
    `/missions/${MISSION_ID}/image?path=${encodeURIComponent(f.frame_path)}&src=${SRC}` +
    `&max_side=${CANVAS_MAX_SIDE}`
  );
}

/** frame_path → decoded Image for main canvas only; LRU by Map insertion order (evict oldest). */
const canvasImageLRU = new Map();

function canvasImageCacheGet(path) {
  const img = canvasImageLRU.get(path);
  if (!img) return undefined;
  canvasImageLRU.delete(path);
  canvasImageLRU.set(path, img);
  return img;
}

function canvasImageCacheSet(path, img) {
  if (canvasImageLRU.has(path)) canvasImageLRU.delete(path);
  canvasImageLRU.set(path, img);
  while (canvasImageLRU.size > CANVAS_IMAGE_CACHE_MAX) {
    const k = canvasImageLRU.keys().next().value;
    canvasImageLRU.delete(k);
  }
}

function canvasImageCacheClear() {
  canvasImageLRU.clear();
}

/** 1×1 GIF so filmstrip cells keep size when real thumbnails are released (saves RAM). */
const FILMSTRIP_IMG_PLACEHOLDER =
  'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

let filmstripImgObserver = null;

function teardownFilmstripImageObserver() {
  if (filmstripImgObserver) {
    filmstripImgObserver.disconnect();
    filmstripImgObserver = null;
  }
}

function filmstripThumbWrapAt(idx) {
  return idx >= 0 && idx < filmstrip.children.length ? filmstrip.children[idx] : null;
}

function filmstripImgAlreadyShowingFrame(img, f) {
  if (!img || !f) return false;
  try {
    const cur = img.currentSrc || img.src || '';
    const u = new URL(cur, window.location.href);
    if (u.protocol === 'data:') return false;
    const want = new URL(frameImageSrcFilmstrip(f), window.location.href);
    return u.pathname === want.pathname && u.search === want.search;
  } catch (_e) {
    return false;
  }
}

function filmstripEnsureImgForIndex(idx) {
  if (idx < 0 || idx >= frames.length) return;
  const wrap = filmstripThumbWrapAt(idx);
  if (!wrap) return;
  const img = wrap.querySelector('img');
  if (!img) return;
  const f = frames[idx];
  if (filmstripImgAlreadyShowingFrame(img, f)) return;
  img.src = frameImageSrcFilmstrip(f);
}

function filmstripReleaseImgIfAllowed(idx) {
  if (idx < 0 || idx >= frames.length) return;
  if (idx === currentIdx) return;
  const wrap = filmstripThumbWrapAt(idx);
  if (!wrap) return;
  const img = wrap.querySelector('img');
  if (!img) return;
  img.src = FILMSTRIP_IMG_PLACEHOLDER;
}

function setupFilmstripImageObserver() {
  teardownFilmstripImageObserver();
  if (!filmstrip || frames.length === 0) return;
  filmstripImgObserver = new IntersectionObserver(
    entries => {
      for (const ent of entries) {
        const idx = parseInt(ent.target.dataset.idx, 10);
        if (!Number.isFinite(idx)) continue;
        if (ent.isIntersecting) filmstripEnsureImgForIndex(idx);
        else filmstripReleaseImgIfAllowed(idx);
      }
    },
    { root: filmstrip, rootMargin: '120px', threshold: 0.01 }
  );
  filmstrip.querySelectorAll('.fs-thumb').forEach(el => filmstripImgObserver.observe(el));
}

/** @type {{ x0: number, y0: number, x1: number, y1: number } | null} */
let dragSelect = null;
const filmstrip   = document.getElementById('filmstrip');
const frameCounter = document.getElementById('frameCounter');
const frameInfo   = document.getElementById('frameInfo');
const runBtn      = document.getElementById('runBtn');
const stopAnalyzeBtn = document.getElementById('stopAnalyzeBtn');
const compareModelsBtn = document.getElementById('compareModelsBtn');
const modelComparePanel = document.getElementById('modelComparePanel');
const compareOverlaySelect = document.getElementById('compareOverlaySelect');
const modelCompareSummary = document.getElementById('modelCompareSummary');
const runProgress = document.getElementById('runProgress');
const saveBtn     = document.getElementById('saveBtn');
const assembleBtn = document.getElementById('assembleBtn');
const saveResult  = document.getElementById('saveResult');
const approveBtn  = document.getElementById('approveBtn');
const skipBtn     = document.getElementById('skipBtn');
const undoBtn     = document.getElementById('undoBtn');
const prevBtn     = document.getElementById('prevBtn');
const nextBtn     = document.getElementById('nextBtn');
const nextReviewBtn = document.getElementById('nextReviewBtn');
const confSlider  = document.getElementById('confSlider');
const distSlider  = document.getElementById('distSlider');
const strideSlider = document.getElementById('strideSlider');
const confVal     = document.getElementById('confVal');
const distVal     = document.getElementById('distVal');
const strideVal   = document.getElementById('strideVal');
const errorBanner = document.getElementById('errorBanner');
const realMissionSelect = document.getElementById('realMissionSelect');
const progressHint  = document.getElementById('progressHint');
const trainingAnalyticsBar = document.getElementById('trainingAnalyticsBar');
const yoloModelSelect = document.getElementById('yoloModelSelect');
const yoloModelCustomWrap = document.getElementById('yoloModelCustomWrap');
const yoloModelInput = document.getElementById('yoloModelInput');
const yoloBatchInput = document.getElementById('yoloBatchInput');
const yoloPrefetchBtn = document.getElementById('yoloPrefetchBtn');
const yoloPrefetchResult = document.getElementById('yoloPrefetchResult');
const progressiveStrideChk = document.getElementById('progressiveStrideChk');
const focusNearCurrentChk = document.getElementById('focusNearCurrentChk');
const manualFromYoloBtn = document.getElementById('manualFromYoloBtn');
const clearAiPredsBtn = document.getElementById('clearAiPredsBtn');
const manualClearBtn = document.getElementById('manualClearBtn');
/** Default label/conf for canvas-drawn boxes (no form UI). */
const DEFAULT_MANUAL_LABEL = 'sports ball';
const DEFAULT_MANUAL_CONF = 0.99;

const LS_YOLO_MODEL = 'sd_training_yolo_model';
const LS_YOLO_SELECT = 'sd_training_yolo_select';
const LS_YOLO_BATCH = 'sd_training_yolo_batch';
const LS_PROGRESSIVE_STRIDE = 'sd_training_progressive_stride';
const LS_FOCUS_NEAR_CURRENT = 'sd_training_focus_near_current';

/** Set while a training analyze request is in flight (frame count + analyze fetch). */
let trainingAnalyzeAbort = null;

// Labeler speed metrics (session since frames load; pace since first Approve/Skip)
let labelerSessionStartMs = null;
let labelerFirstActionMs = null;
let labelerActionCount = 0;
let labelerPrevActionMs = null;
/** @type {number[]} */
let labelerInterActionGapsMs = [];
const LABELER_GAP_HISTORY = 40;
let labelerMetricsInterval = null;

/** @type {null | Array<{model_spec:string,ok:boolean,error?:string,dets:Array,n_dets:number}>} */
let modelCompareRows = null;
let compareOverlayChoice = 'main';
/** Canvas overlay: draw every successful compare run with distinct colors + model name on each box. */
const COMPARE_OVERLAY_ALL = '__all_compare__';
/** Same floor as server compare (conf 0.05); training slider must not hide compare boxes. */
const COMPARE_VIS_CONF_MIN = 0.05;

function syncAnalyzeStopButton(visible) {
  if (!stopAnalyzeBtn) return;
  if (visible) {
    stopAnalyzeBtn.style.display = '';
    stopAnalyzeBtn.disabled = false;
  } else {
    stopAnalyzeBtn.style.display = 'none';
    stopAnalyzeBtn.disabled = true;
  }
}

if (stopAnalyzeBtn) {
  stopAnalyzeBtn.addEventListener('click', () => {
    if (trainingAnalyzeAbort) trainingAnalyzeAbort.abort();
  });
}

function resetModelCompareForNewFrame() {
  modelCompareRows = null;
  compareOverlayChoice = 'main';
  if (compareOverlaySelect) {
    compareOverlaySelect.innerHTML = '<option value="main">Analysis (current run)</option>';
    compareOverlaySelect.value = 'main';
    compareOverlaySelect.disabled = true;
  }
  if (modelComparePanel) modelComparePanel.style.display = 'none';
  if (modelCompareSummary) modelCompareSummary.innerHTML = '';
}

function syncCompareModelsBtn() {
  if (!compareModelsBtn) return;
  compareModelsBtn.disabled = currentIdx < 0 || currentIdx >= frames.length;
}

/** @returns {undefined | { mode:'one', dets: Array, modelSpec: string } | { mode:'all', rows: Array }} */
function compareDetsForOverlay() {
  if (compareOverlayChoice === 'main' || !modelCompareRows) return undefined;
  if (compareOverlayChoice === COMPARE_OVERLAY_ALL) {
    return {
      mode: 'all',
      rows: modelCompareRows.filter(r => r && r.ok && Array.isArray(r.dets)),
    };
  }
  const spec = compareOverlayChoice;
  const row = modelCompareRows.find(r => r.model_spec === spec);
  if (!row || !row.ok) return { mode: 'one', dets: [], modelSpec: spec };
  return { mode: 'one', dets: row.dets || [], modelSpec: row.model_spec || spec };
}

if (compareOverlaySelect) {
  compareOverlaySelect.addEventListener('change', () => {
    compareOverlayChoice = compareOverlaySelect.value || 'main';
    if (currentIdx >= 0) renderFrame(currentIdx);
  });
}

if (compareModelsBtn) {
  compareModelsBtn.addEventListener('click', async () => {
    if (currentIdx < 0 || currentIdx >= frames.length) return;
    const f = frames[currentIdx];
    compareModelsBtn.disabled = true;
    if (modelCompareSummary) {
      modelCompareSummary.innerHTML =
        '<span class="muted">Running YOLO for each preset model (server)…</span>';
    }
    if (modelComparePanel) modelComparePanel.style.display = '';
    try {
      const cmpBody = { frame_path: f.frame_path };
      const cmpModels = collectYoloModelsForCompare();
      if (cmpModels) cmpBody.models = cmpModels;
      const resp = await fetch(
        `/missions/${MISSION_ID}/training/compare_models?src=${encodeURIComponent(SRC)}`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(cmpBody),
        }
      );
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        showError(data.error || 'Compare failed');
        if (modelCompareSummary) modelCompareSummary.innerHTML = '';
        if (modelComparePanel) modelComparePanel.style.display = 'none';
        return;
      }
      errorBanner.style.display = 'none';
      modelCompareRows = data.results || [];
      compareOverlayChoice = COMPARE_OVERLAY_ALL;
      if (compareOverlaySelect) {
        compareOverlaySelect.innerHTML = '<option value="main">Analysis (current run)</option>';
        const allOpt = document.createElement('option');
        allOpt.value = COMPARE_OVERLAY_ALL;
        allOpt.textContent = 'All compare models (labeled)';
        compareOverlaySelect.appendChild(allOpt);
        for (const r of modelCompareRows) {
          const opt = document.createElement('option');
          opt.value = r.model_spec;
          const n = r.ok ? r.n_dets : 'err';
          const tlab = r.ok ? formatInferSeconds(r.predict_s) : '—';
          opt.textContent = r.model_spec + ' (' + n + ' · ' + tlab + ')';
          compareOverlaySelect.appendChild(opt);
        }
        compareOverlaySelect.value = COMPARE_OVERLAY_ALL;
        compareOverlaySelect.disabled = false;
      }
      if (modelCompareSummary) {
        const blocks = [];
        let sumPred = 0;
        let sumCount = 0;
        for (const r of modelCompareRows) {
          if (!r.ok) {
            blocks.push(
              '<div class="mb-2 pb-2" style="border-bottom:1px solid var(--sd-border,#333)">' +
                escapeHtml(r.model_spec) +
                ' — <span style="color:#f66">FAIL</span> ' +
                escapeHtml(String(r.error || '')) +
 '</div>'
            );
            continue;
          }
          if (r.predict_s != null && Number.isFinite(Number(r.predict_s))) {
            sumPred += Number(r.predict_s);
            sumCount += 1;
            cacheModelTiming(r.model_spec, r.predict_s, r.inference_device, 'compare');
          }
          const headerBits = [
            '<strong>' + escapeHtml(r.model_spec) + '</strong>',
            '<span class="muted">' + r.n_dets + ' det</span>',
            '<span class="muted">infer ' + escapeHtml(formatInferSeconds(r.predict_s)) + '</span>',
          ];
          if (r.inference_device) headerBits.push('<span class="muted">' + escapeHtml(String(r.inference_device)) + '</span>');
          const sorted = (r.dets || []).slice().sort((a, b) => b.conf - a.conf);
          let guessList = '';
          if (sorted.length === 0) {
            guessList =
              '<div class="muted small mt-1 mb-0">No detections (server runs YOLO at conf ≥ 0.05).</div>';
          } else {
            const items = sorted.map((d, i) => {
              const lab =
                d.label != null && String(d.label).trim() !== ''
                  ? String(d.label).trim()
                  : d.cls != null
                    ? 'class_' + d.cls
                    : '?';
              const bbox =
                ' [' +
                Number(d.x1).toFixed(0) +
                ',' +
                Number(d.y1).toFixed(0) +
                '–' +
                Number(d.x2).toFixed(0) +
                ',' +
                Number(d.y2).toFixed(0) +
                ']';
              return (
                '<li class="mb-0" style="line-height:1.45">' +
                '<span class="muted">' +
                (i + 1) +
                '.</span> ' +
                '<strong>' +
                escapeHtml(lab) +
                '</strong> ' +
                (d.conf * 100).toFixed(1) +
                '%' +
                (d.cls != null ? ' <span class="muted">cls ' + escapeHtml(String(d.cls)) + '</span>' : '') +
                '<span class="muted">' +
                escapeHtml(bbox) +
                '</span>' +
                '</li>'
              );
            });
            guessList =
              '<div class="small fw-semibold mt-2 mb-0" style="color:var(--sd-muted,#888)">Guessed on this frame</div>' +
              '<ul class="small ps-3 mb-0 mt-1" style="list-style:disc">' +
              items.join('') +
              '</ul>';
          }
          blocks.push(
            '<div class="mb-2 pb-2" style="border-bottom:1px solid var(--sd-border,#333)">' +
              '<div class="d-flex flex-wrap gap-2 align-items-baseline">' +
              headerBits.join(' · ') +
              '</div>' +
              guessList +
              '</div>'
          );
        }
        const foot =
          sumCount > 0
            ? 'Per-model times are wall clock for this frame (first model may include loading weights). ' +
              'Sum of successful runs: <strong>' +
              escapeHtml(formatInferSeconds(sumPred)) +
              '</strong>. Compare overlay uses server conf ≥ ' +
              COMPARE_VIS_CONF_MIN +
              ' (not the training slider). Default canvas view: <strong>All compare models</strong>.'
            : 'Per-model times are wall clock for this frame (first model may include loading weights). ' +
              'Compare overlay uses server conf ≥ ' +
              COMPARE_VIS_CONF_MIN +
              ' (not the training slider).';
        blocks.push('<div class="muted small mt-2">' + foot + '</div>');
        modelCompareSummary.innerHTML = blocks.join('');
      }
      if (currentIdx >= 0) renderFrame(currentIdx);
    } catch (e) {
      showError(String(e));
      if (modelCompareSummary) modelCompareSummary.innerHTML = '';
      if (modelComparePanel) modelComparePanel.style.display = 'none';
    } finally {
      syncCompareModelsBtn();
    }
  });
}

if (manualFromYoloBtn) {
  manualFromYoloBtn.addEventListener('click', () => {
    if (currentIdx < 0 || currentIdx >= frames.length) return;
    const f = frames[currentIdx];
    const m = bestMatch(f);
    if (!m || !m.yolo_bbox) {
      if (saveResult) saveResult.textContent = 'No YOLO box on this frame.';
      return;
    }
    errorBanner.style.display = 'none';
    addManualBboxFromUser(f, yoloDetToManualNorm(m.yolo_bbox), false);
    syncManualBboxFormFromFrame();
    if (saveResult) saveResult.textContent = '';
    if (canvasBaseImage) paintCanvas(currentIdx);
    else renderFrame(currentIdx);
  });
}
if (clearAiPredsBtn) {
  clearAiPredsBtn.addEventListener('click', () => {
    clearAiPredictionsOnCurrentFrame();
    if (saveResult) saveResult.textContent = '';
  });
}
if (manualClearBtn) {
  manualClearBtn.addEventListener('click', () => {
    if (currentIdx < 0 || currentIdx >= frames.length) return;
    clearManualAllCurrentFrame();
    if (saveResult) saveResult.textContent = '';
  });
}

// ---------------------------------------------------------------------------
// Threshold sliders
// ---------------------------------------------------------------------------
confSlider.addEventListener('input', () => {
  confThresh = parseFloat(confSlider.value);
  confVal.textContent = confThresh.toFixed(2);
  reEvaluateStatuses();
  if (currentIdx >= 0) {
    if (canvasBaseImage) paintCanvas(currentIdx);
    else renderFrame(currentIdx);
  }
  updateCounts();
  refreshAllFilmstripBadges();
});

distSlider.addEventListener('input', () => {
  distThresh = parseFloat(distSlider.value);
  distVal.textContent = Math.round(distThresh);
  reEvaluateStatuses();
  if (currentIdx >= 0) {
    if (canvasBaseImage) paintCanvas(currentIdx);
    else renderFrame(currentIdx);
  }
  updateCounts();
  refreshAllFilmstripBadges();
});

if (strideSlider && strideVal) {
  let _strideTimer = null;
  strideSlider.addEventListener('input', () => {
    frameStride = Math.max(1, parseInt(strideSlider.value, 10) || 1);
    strideVal.textContent = String(frameStride);
    clearTimeout(_strideTimer);
    _strideTimer = setTimeout(() => showModelTimeEstimate(), 300);
  });
}

function syncRunBtnFromSelect() {
  // Button is enabled only when a real_missions/*.json name is selected (not "— select —").
  runBtn.disabled = !realMissionSelect.value;
}

function refreshIdleFrameInfo() {
  if (frames.length > 0) return;
  const v = realMissionSelect.value;
  if (v) {
    frameInfo.innerHTML =
      '<span class="muted">Setup <code>' + escapeHtml(v) + '</code> selected — click <strong>Run analysis</strong> to scan <code>frames/</code>, match the log, and run YOLO.</span>';
  } else {
    frameInfo.innerHTML =
      '<span class="muted">Choose a real mission JSON under <strong>Setup</strong>, then click <strong>Run analysis</strong>.</span>';
  }
}

realMissionSelect.addEventListener('change', () => {
  syncRunBtnFromSelect();
  refreshIdleFrameInfo();
});

const yoloTimeEstimate = document.getElementById('yoloTimeEstimate');

// model_spec → { predict_s, device, source }
const modelTimingCache = {};
let _lastFrameCount = 0;
let _benchmarkAbort = null;

function cacheModelTiming(modelSpec, predictS, device, source) {
  if (!modelSpec || predictS == null || !Number.isFinite(Number(predictS))) return;
  modelTimingCache[modelSpec] = {
    predict_s: Number(predictS),
    device: device || null,
    source: source || 'unknown',
  };
}

function getSelectedModelSpec() {
  const sel = yoloModelSelect ? yoloModelSelect.value : '';
  return sel === '__custom__'
    ? (yoloModelInput ? yoloModelInput.value.trim() : '')
    : sel;
}

// stride → n_frames cache so we don't re-fetch for the same stride
const _frameCountByStride = {};

function _renderTimeEstimate(modelSpec, cached, nFrames) {
  const perFrame = cached.predict_s;
  const totalMs = perFrame * nFrames * 1000;
  const perFrameStr = formatInferSeconds(perFrame);
  const totalStr = formatElapsed(totalMs);
  const src = cached.source === 'compare' ? 'compare' : cached.source === 'analysis' ? 'last run' : 'benchmark';
  yoloTimeEstimate.style.display = '';
  yoloTimeEstimate.innerHTML =
    '<strong>' + escapeHtml(modelSpec) + '</strong>: ' +
    perFrameStr + '/frame' +
    (nFrames > 0 ? ' × ' + nFrames + ' frames (stride ' + frameStride + ') ≈ <strong>' + totalStr + '</strong>' : '') +
    (cached.device ? ' <span class="muted">(' + escapeHtml(String(cached.device)) + ')</span>' : '') +
    ' <span class="muted">(from ' + src + ')</span>';
}

async function showModelTimeEstimate() {
  if (!yoloTimeEstimate) return;
  const modelSpec = getSelectedModelSpec();
  if (!modelSpec) { yoloTimeEstimate.style.display = 'none'; return; }

  const cached = modelTimingCache[modelSpec];
  if (!cached) {
    yoloTimeEstimate.style.display = 'none';
    return;
  }

  const stride = Math.max(1, parseInt(String(frameStride), 10) || 1);

  // Use stride-specific frame count cache if available
  if (_frameCountByStride[stride] != null) {
    _renderTimeEstimate(modelSpec, cached, _frameCountByStride[stride]);
    return;
  }

  // Show immediately with best available count, then fetch accurate count
  const fallback = _lastFrameCount > 0 ? _lastFrameCount : (frames.length || 0);
  _renderTimeEstimate(modelSpec, cached, fallback);

  try {
    const resp = await fetch(
      `/missions/${MISSION_ID}/training/frame_count?src=${encodeURIComponent(SRC)}&stride=${stride}`
    );
    const data = await resp.json();
    if (resp.ok && data.ok && typeof data.n_frames === 'number') {
      _frameCountByStride[stride] = data.n_frames;
      _lastFrameCount = data.n_frames;
      // Re-check the model hasn't changed while we were fetching
      if (getSelectedModelSpec() === modelSpec && modelTimingCache[modelSpec]) {
        _renderTimeEstimate(modelSpec, modelTimingCache[modelSpec], data.n_frames);
      }
    }
  } catch (_e) { /* keep fallback */ }
}

async function benchmarkSelectedModel() {
  if (_benchmarkAbort) { _benchmarkAbort.abort(); _benchmarkAbort = null; }
  if (!yoloTimeEstimate) return;

  const modelSpec = getSelectedModelSpec();
  if (!modelSpec) { yoloTimeEstimate.style.display = 'none'; return; }

  // Already cached — just show it
  if (modelTimingCache[modelSpec]) { showModelTimeEstimate(); return; }

  // Need a frame to benchmark against
  let benchFrame = null;
  if (frames.length > 0 && currentIdx >= 0 && frames[currentIdx]) {
    benchFrame = frames[currentIdx].frame_path;
  } else if (frames.length > 0) {
    benchFrame = frames[0].frame_path;
  }
  if (!benchFrame) {
    yoloTimeEstimate.style.display = '';
    yoloTimeEstimate.innerHTML =
      '<span class="muted">Run analysis first to get timing for <code>' +
      escapeHtml(modelSpec) + '</code>.</span>';
    return;
  }

  yoloTimeEstimate.style.display = '';
  yoloTimeEstimate.innerHTML =
    '<span class="muted">Timing <code>' + escapeHtml(modelSpec) + '</code> (1 frame)…</span>';

  _benchmarkAbort = new AbortController();
  try {
    const stride = Math.max(1, parseInt(String(frameStride), 10) || 1);
    // Fetch frame count in parallel with benchmark
    const countP = fetch(
      `/missions/${MISSION_ID}/training/frame_count?src=${encodeURIComponent(SRC)}&stride=${stride}`,
      { signal: _benchmarkAbort.signal }
    ).then(r => r.json()).catch(() => null);

    const resp = await fetch(
      `/missions/${MISSION_ID}/training/compare_models?src=${encodeURIComponent(SRC)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frame_path: benchFrame, models: [modelSpec] }),
        signal: _benchmarkAbort.signal,
      }
    );
    const data = await resp.json();
    const cd = await countP;
    if (cd && cd.ok && typeof cd.n_frames === 'number') {
      _lastFrameCount = cd.n_frames;
      _frameCountByStride[stride] = cd.n_frames;
    }

    if (!resp.ok || !data.ok || !data.results || !data.results.length) {
      const err = (data.results && data.results[0] && data.results[0].error) || data.error || 'failed';
      yoloTimeEstimate.innerHTML =
        '<span style="color:#f66">Benchmark failed: ' + escapeHtml(String(err)) + '</span>';
      return;
    }
    const r = data.results[0];
    if (!r.ok || r.predict_s == null) {
      yoloTimeEstimate.innerHTML =
        '<span style="color:#f66">Benchmark failed: ' + escapeHtml(String(r.error || '?')) + '</span>';
      return;
    }
    cacheModelTiming(modelSpec, r.predict_s, r.inference_device, 'benchmark');
    showModelTimeEstimate();
  } catch (e) {
    if (e.name === 'AbortError') return;
    yoloTimeEstimate.innerHTML =
      '<span style="color:#f66">' + escapeHtml(String(e)) + '</span>';
  } finally {
    _benchmarkAbort = null;
  }
}

if (yoloModelSelect) {
  yoloModelSelect.addEventListener('change', () => {
    syncYoloCustomInputVisible();
    benchmarkSelectedModel();
  });
}

if (yoloModelInput) {
  yoloModelInput.addEventListener('change', () => benchmarkSelectedModel());
}

if (yoloPrefetchBtn) {
  yoloPrefetchBtn.addEventListener('click', async () => {
    yoloPrefetchBtn.disabled = true;
    if (yoloPrefetchResult) yoloPrefetchResult.textContent = 'Downloading hub weights to server cache…';
    try {
      const resp = await fetch('/training/yolo_prefetch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        const detail = data.results ? JSON.stringify(data.results) : (data.error || 'failed');
        if (yoloPrefetchResult) yoloPrefetchResult.textContent = 'Prefetch issue: ' + detail;
      } else {
        const r = data.results || {};
        const bad = Object.entries(r).filter(([, v]) => !v.ok);
        if (yoloPrefetchResult) {
          yoloPrefetchResult.textContent = bad.length
            ? 'Partial: ' + bad.map(([k, v]) => k + ': ' + (v.error || '?')).join('; ')
            : 'Cached ' + Object.keys(r).length + ' hub weight(s).';
        }
      }
    } catch (e) {
      if (yoloPrefetchResult) yoloPrefetchResult.textContent = String(e);
    } finally {
      yoloPrefetchBtn.disabled = false;
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  try {
    const sk = localStorage.getItem(LS_YOLO_SELECT);
    if (yoloModelSelect && sk != null && sk !== undefined) {
      const ok = Array.from(yoloModelSelect.options).some(o => o.value === sk);
      if (ok) yoloModelSelect.value = sk;
    }
    const sm = localStorage.getItem(LS_YOLO_MODEL);
    if (yoloModelInput && sm) yoloModelInput.value = sm;
    const sb = localStorage.getItem(LS_YOLO_BATCH);
    if (yoloBatchInput && sb && /^\d+$/.test(sb)) yoloBatchInput.value = sb;
    const ps = localStorage.getItem(LS_PROGRESSIVE_STRIDE);
    if (progressiveStrideChk && ps === '0') progressiveStrideChk.checked = false;
    if (progressiveStrideChk && ps === '1') progressiveStrideChk.checked = true;
    const fn = localStorage.getItem(LS_FOCUS_NEAR_CURRENT);
    if (focusNearCurrentChk && fn === '0') focusNearCurrentChk.checked = false;
    if (focusNearCurrentChk && fn === '1') focusNearCurrentChk.checked = true;
  } catch (_e) { /* private mode */ }
  syncYoloCustomInputVisible();
  if (strideSlider && strideVal) {
    frameStride = Math.max(1, parseInt(strideSlider.value, 10) || 1);
    strideVal.textContent = String(frameStride);
  }
  // Prefer setup file recorded in mission.jsonl (real flights store it in sim_truth_file).
  if (typeof TRAINING_AUTO_SETUP === 'string' && TRAINING_AUTO_SETUP && realMissionSelect) {
    const has = Array.from(realMissionSelect.options).some(o => o.value === TRAINING_AUTO_SETUP);
    if (has) realMissionSelect.value = TRAINING_AUTO_SETUP;
  }
  syncRunBtnFromSelect();
  refreshIdleFrameInfo();
  syncManualBboxFormFromFrame();
  if (progressiveStrideChk) {
    progressiveStrideChk.addEventListener('change', persistYoloInputs);
  }
  if (focusNearCurrentChk) {
    focusNearCurrentChk.addEventListener('change', persistYoloInputs);
  }
});

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function formatElapsed(ms) {
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 3600000) {
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return `${m}m ${s}s`;
  }
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  return `${h}h ${m}m`;
}

/** Live analysis status: updates ``frameInfo`` + ``runProgress`` until cleared. */
function startAnalysisStatusUI(realMission, nFramesKnown) {
  const t0 = performance.now();
  const tick = () => {
    const elapsed = formatElapsed(performance.now() - t0);
    const confP = confThresh.toFixed(2);
    const distP = Math.round(distThresh);
    const strideNote = frameStride > 1
      ? ' <strong>Stride</strong> ' + frameStride + ' (every Nth frame; fewer YOLO runs).'
      : '';
    const frameLine =
      nFramesKnown != null && nFramesKnown >= 0
        ? '<strong>Frames</strong> ' + nFramesKnown + ' JPEGs queued (after stride).' + strideNote
        : '<strong>Frames</strong> counting JPEGs in <code>frames/</code>…';
    frameInfo.innerHTML =
      '<div class="analysis-progress" style="line-height:1.55;max-width:820px">' +
      '<div class="fw-semibold mb-1" style="color:var(--sd-accent)">Analysis running</div>' +
      '<div class="muted small mb-2">' +
      '<strong>Mission</strong> ' + escapeHtml(String(MISSION_ID)) +
      ' · <strong>Setup</strong> <code>' + escapeHtml(realMission) + '</code>' +
      ' · <strong>Log source</strong> <code>' + escapeHtml(String(SRC)) + '</code><br>' +
      frameLine +
      '</div>' +
      '<ul class="small ps-3 mb-2" style="margin-bottom:0">' +
      '<li>Load weed GPS from <code>real_missions/</code> and list JPEGs in this mission\'s <code>frames/</code> folder</li>' +
      '<li>Build an <code>fsm_tick</code> time index from <code>mission.jsonl</code> and snap each frame timestamp to the nearest tick for drone pose</li>' +
      '<li>Project each weed into pixel coordinates (camera model inverse, rangefinder / altitude)</li>' +
      '<li>Run <strong>batched Ultralytics YOLO</strong> over every frame (low internal conf; your sliders apply after). ' +
      'Uses <strong>GPU (CUDA)</strong> if PyTorch sees one, else <strong>CPU</strong>; set env <code>SKYDOCK_YOLO_DEVICE=cpu</code> to force CPU or <code>cuda:0</code> for a specific GPU.</li>' +
      '<li>For each weed in view, pick the nearest detection; frame is <strong>auto</strong> only if <em>every</em> weed passes (conf ≥ ' + confP + ', GPS–bbox centre ≤ ' + distP + ' px)</li>' +
      '</ul>' +
      '<div class="small"><span class="stat-pill">Elapsed: ' + elapsed + '</span> ' +
      '<span class="muted">The server streams YOLO in batches (~24 frames); the filmstrip and Auto/Review counts update after each batch.</span></div>' +
      '</div>';
    const nf =
      nFramesKnown != null && nFramesKnown >= 0 ? nFramesKnown + ' frames · ' : '';
    runProgress.innerHTML =
      '<strong>Working…</strong> ' + elapsed + ' — ' + nf + 'YOLO + log matching on server.';
  };
  tick();
  return setInterval(tick, 400);
}

// ---------------------------------------------------------------------------
// Re-evaluate auto/review status client-side when thresholds change
// ---------------------------------------------------------------------------
/** @param {Set<string>|null} onlyWeedIds — if provided, only re-evaluate frames containing those weeds */
function reEvaluateStatuses(onlyWeedIds) {
  for (const f of frames) {
    if (onlyWeedIds) {
      let relevant = false;
      for (const m of f.matches) { if (onlyWeedIds.has(m.weed_id)) { relevant = true; break; } }
      if (!relevant) continue;
    }
    reEvaluateFrameStatus(f);
  }
}

function reEvaluateFrameStatus(f) {
  let any_auto = false, any_review = false, has_weed = false;
  for (const m of f.matches) {
    has_weed = true;
    const bbox = m.yolo_bbox && !isIgnoredTrainingDet(m.yolo_bbox) ? m.yolo_bbox : null;
    if (!bbox) {
      // No YOLO det — but if a confident prediction exists, surface as review
      const streak = weedSkipStreak.get(m.weed_id) || 0;
      if (streak < 2 && weedDetIndex.has(m.weed_id) && f.drone_state) {
        m._status_live = 'review';
        any_review = true;
      } else {
        m._status_live = 'no_det';
      }
      continue;
    }
    const streak = weedSkipStreak.get(m.weed_id) || 0;
    const isAuto = bbox.conf >= confThresh && m.dist_px <= distThresh && streak < 2;
    if (isAuto) any_auto = true;
    else any_review = true;
    m._status_live = isAuto ? 'auto' : 'review';
  }
  if (!has_weed) {
    f._status_live = 'no_weed';
  } else if (f.matches.every(m => m._status_live === 'auto')) {
    f._status_live = 'auto';
  } else if (any_review) {
    f._status_live = 'review';
  } else if (any_auto) {
    f._status_live = 'review';
  } else {
    f._status_live = 'no_det';
  }
}

function effectiveStatus(f) {
  // User decision overrides auto status
  const d = decisions[f.timestamp_ns];
  if (d === 'approved') return 'approved';
  if (d === 'skipped')  return 'skipped';
  return f._status_live || f.status;
}

function bestMatch(f) {
  // Return the match with the best (lowest) dist that has a yolo_bbox
  let best = null;
  for (const m of f.matches) {
    if (!m.yolo_bbox || isIgnoredTrainingDet(m.yolo_bbox)) continue;
    if (!best || m.dist_px < best.dist_px) best = m;
  }
  return best;
}

function syncYoloCustomInputVisible() {
  if (!yoloModelSelect || !yoloModelCustomWrap) return;
  yoloModelCustomWrap.style.display = yoloModelSelect.value === '__custom__' ? '' : 'none';
}

function buildAnalyzeRequestBody(realMission, frameStrideOverride, opts) {
  const st =
    frameStrideOverride != null
      ? Math.max(1, Math.min(500, Math.floor(Number(frameStrideOverride)) || 1))
      : frameStride;
  const body = {
    real_mission: realMission,
    conf_thresh: confThresh,
    dist_thresh: distThresh,
    frame_stride: st,
  };
  const sel = yoloModelSelect && yoloModelSelect.value;
  if (sel === '__custom__') {
    const mp = yoloModelInput && yoloModelInput.value.trim();
    if (mp) body.model_path = mp;
  } else if (sel) {
    body.model_path = sel;
  }
  if (yoloBatchInput) {
    const bs = yoloBatchInput.value.trim();
    if (bs !== '') {
      const n = parseInt(bs, 10);
      if (Number.isFinite(n) && n >= 1) body.batch_size = Math.min(256, n);
    }
  }
  const o = opts || {};
  if (o.focus_timestamp_ns != null && Number.isFinite(Number(o.focus_timestamp_ns))) {
    body.focus_timestamp_ns = Math.trunc(Number(o.focus_timestamp_ns));
  }
  return body;
}

/** Format server `predict_s` (seconds, one image) for display. */
function formatInferSeconds(s) {
  if (s == null || s === '' || !Number.isFinite(Number(s))) return '—';
  const x = Number(s);
  if (x < 0.995) return `${Math.max(1, Math.round(x * 1000))}ms`;
  return `${x.toFixed(2)}s`;
}

function collectYoloModelsForCompare() {
  if (!yoloModelSelect) return null;
  const seen = new Set();
  const out = [];
  for (let i = 0; i < yoloModelSelect.options.length; i++) {
    const v = yoloModelSelect.options[i].value;
    if (!v || v === '__custom__') continue;
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  if (yoloModelSelect.value === '__custom__' && yoloModelInput) {
    const c = yoloModelInput.value.trim();
    if (c && !seen.has(c)) out.push(c);
  }
  return out.length ? out : null;
}

function persistYoloInputs() {
  try {
    if (yoloModelSelect) localStorage.setItem(LS_YOLO_SELECT, yoloModelSelect.value);
    if (yoloModelInput) localStorage.setItem(LS_YOLO_MODEL, yoloModelInput.value);
    if (yoloBatchInput) localStorage.setItem(LS_YOLO_BATCH, yoloBatchInput.value.trim());
    if (progressiveStrideChk) {
      localStorage.setItem(LS_PROGRESSIVE_STRIDE, progressiveStrideChk.checked ? '1' : '0');
    }
    if (focusNearCurrentChk) {
      localStorage.setItem(LS_FOCUS_NEAR_CURRENT, focusNearCurrentChk.checked ? '1' : '0');
    }
  } catch (_e) { /* ignore */ }
}

function syncUndoButton() {
  if (!undoBtn) return;
  undoBtn.disabled = decisionHistory.length === 0 || frames.length === 0;
}

function resetLabelerMetrics() {
  labelerSessionStartMs = null;
  labelerFirstActionMs = null;
  labelerActionCount = 0;
  labelerPrevActionMs = null;
  labelerInterActionGapsMs = [];
  if (labelerMetricsInterval != null) {
    clearInterval(labelerMetricsInterval);
    labelerMetricsInterval = null;
  }
  refreshTrainingAnalytics();
}

function ensureLabelerSessionClock() {
  if (frames.length === 0) return;
  if (labelerSessionStartMs == null) {
    labelerSessionStartMs = performance.now();
    if (labelerMetricsInterval == null) {
      labelerMetricsInterval = setInterval(refreshTrainingAnalytics, 1000);
    }
  }
}

function noteLabelerAction() {
  ensureLabelerSessionClock();
  const now = performance.now();
  if (labelerFirstActionMs == null) labelerFirstActionMs = now;
  if (labelerPrevActionMs != null) {
    labelerInterActionGapsMs.push(now - labelerPrevActionMs);
    while (labelerInterActionGapsMs.length > LABELER_GAP_HISTORY) {
      labelerInterActionGapsMs.shift();
    }
  }
  labelerPrevActionMs = now;
  labelerActionCount++;
  refreshTrainingAnalytics();
}

function noteLabelerUndo() {
  if (labelerActionCount > 0) labelerActionCount--;
  labelerPrevActionMs = performance.now();
  refreshTrainingAnalytics();
}

function formatDurationMs(ms) {
  if (ms < 0 || !Number.isFinite(ms)) return '0s';
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  }
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/** Top bar: decided/total, pace (A·S per min), ETA to clear review queue at current pace. */
function refreshTrainingAnalytics() {
  if (!trainingAnalyticsBar) return;
  if (frames.length === 0) {
    trainingAnalyticsBar.style.display = 'none';
    trainingAnalyticsBar.innerHTML = '';
    return;
  }
  let decided = 0;
  let reviewLeft = 0;
  for (const f of frames) {
    const d = decisions[f.timestamp_ns];
    if (d === 'approved' || d === 'skipped') {
      decided++;
      continue;
    }
    if (effectiveStatus(f) === 'review') reviewLeft++;
  }
  const total = frames.length;
  const now = performance.now();
  let paceStr = 'Pace: — (Approve/Skip to start)';
  let perMin = 0;
  if (labelerActionCount > 0 && labelerFirstActionMs != null) {
    const activeMs = Math.max(now - labelerFirstActionMs, 500);
    perMin = labelerActionCount / (activeMs / 60000);
    paceStr = `~${perMin.toFixed(1)} per minute`;
  }
  let etaStr;
  if (reviewLeft === 0) {
    etaStr = 'Review queue clear';
  } else if (perMin > 0.05) {
    const minutes = reviewLeft / perMin;
    if (minutes < 1) {
      etaStr = `~${Math.max(1, Math.ceil(minutes * 60))} s to go at this rate`;
    } else if (minutes < 120) {
      etaStr = `~${minutes.toFixed(1)} min to go at this rate`;
    } else {
      etaStr = `~${(minutes / 60).toFixed(1)} h to go at this rate`;
    }
  } else {
    etaStr = `${reviewLeft} review left — rate starts after your first A/S`;
  }
  let sessionLine = '';
  if (labelerSessionStartMs != null) {
    const sessionMs = now - labelerSessionStartMs;
    let gapBit = '';
    if (labelerInterActionGapsMs.length > 0) {
      const sum = labelerInterActionGapsMs.reduce((a, b) => a + b, 0);
      gapBit =
        ' · avg gap between A/S: ' + (sum / labelerInterActionGapsMs.length / 1000).toFixed(1) + 's';
    }
    sessionLine =
      '<div class="small muted mt-1 mb-0">' +
      escapeHtml(formatDurationMs(sessionMs)) +
      ' on this load' +
      escapeHtml(gapBit) +
      '</div>';
  }
  const tip =
    'Decided = frames you approved or skipped. Pace = Approve+Skip per minute since first A/S. Time to go = remaining review frames divided by that pace.';
  trainingAnalyticsBar.style.display = '';
  trainingAnalyticsBar.innerHTML =
    '<div class="fw-semibold mb-1" style="color:var(--sd-muted);font-size:11px">Labeling</div>' +
    '<div class="d-flex flex-wrap align-items-center gap-2" title="' +
    escapeHtml(tip) +
    '">' +
    '<span class="stat-pill"><span class="val">' +
    decided +
    '</span> / <span class="val">' +
    total +
    '</span> decided</span> ' +
    '<span class="stat-pill">' +
    escapeHtml(paceStr) +
    '</span> ' +
    '<span class="stat-pill">' +
    escapeHtml(etaStr) +
    '</span>' +
    '</div>' +
    sessionLine;
}

function pushDecisionHistory(ts) {
  const had = Object.prototype.hasOwnProperty.call(decisions, ts);
  decisionHistory.push({ ts, prev: had ? decisions[ts] : null });
  syncUndoButton();
}

function refreshAllFilmstripBadges() {
  const thumbs = filmstrip.querySelectorAll('.fs-thumb');
  thumbs.forEach((t, i) => {
    if (i >= frames.length) return;
    const badge = t.querySelector('.fs-badge');
    if (!badge) return;
    const st = effectiveStatus(frames[i]);
    badge.className = `fs-badge badge-${st}`;
    badge.textContent = st === 'auto' ? 'A' : st === 'review' ? '?' : st === 'approved' ? '\u2713' : st === 'skipped' ? '\u2717' : '\u2014';
  });
}

function undoLastDecision() {
  const item = decisionHistory.pop();
  if (!item) return;
  if (item.prev === null) delete decisions[item.ts];
  else decisions[item.ts] = item.prev;
  noteLabelerUndo();
  syncUndoButton();
  updateCounts();
  const idx = frames.findIndex(f => f.timestamp_ns === item.ts);
  if (idx >= 0) refreshFilmstripThumbBadge(idx);
  else refreshAllFilmstripBadges();
  if (idx >= 0) jumpTo(idx);
  else if (currentIdx >= 0) renderFrame(currentIdx);
}

// ---------------------------------------------------------------------------
// Frame ordering: only COCO weed-proxy names (exact match); giraffe etc. never count.
// ---------------------------------------------------------------------------
const TRAINING_WEED_PROXY_LABELS = new Set(['sports ball', 'frisbee']);
/** Detections with these COCO labels are ignored for matching, counts, and drawing (aerial FPs). */
const TRAINING_IGNORE_DET_LABELS = new Set(['dog']);

function isIgnoredTrainingDet(det) {
  if (!det) return false;
  const s = det.label != null ? String(det.label).trim().toLowerCase() : '';
  return TRAINING_IGNORE_DET_LABELS.has(s);
}

function isWeedProxyTrainingDet(det) {
  if (!det) return false;
  const s = det.label != null ? String(det.label).trim().toLowerCase() : '';
  return TRAINING_WEED_PROXY_LABELS.has(s);
}

/** Draw any model output at least this confident (matches typical NMS floor); conf slider only gates auto/review. */
const YOLO_DISPLAY_CONF_MIN = 0.05;

// ---------------------------------------------------------------------------
// Camera geometry (mirrors utils.py detection_to_ned / latlon_to_pixel)
// ---------------------------------------------------------------------------
const CAM_FOV_X = 27.4, CAM_FOV_Y = 21.0, CAM_PIX = 640;
const CAM_FX = CAM_PIX / (2 * Math.tan(CAM_FOV_X * Math.PI / 360));
const CAM_FY = CAM_PIX / (2 * Math.tan(CAM_FOV_Y * Math.PI / 360));
const CAM_CX = CAM_PIX / 2, CAM_CY = CAM_PIX / 2;

function _dsRot(ds) {
  const rot = ds.rotaion || {};
  return { roll: rot.x || 0, pitch: rot.y || 0, yaw: rot.z || 0 };
}

function _buildR(roll, pitch, yaw) {
  const cr = Math.cos(roll), sr = Math.sin(roll);
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const cy = Math.cos(yaw), sy = Math.sin(yaw);
  // Rz @ Ry @ Rx  (row-major 3x3 flattened)
  return [
    cy*cp,  cy*sp*sr - sy*cr,  cy*sp*cr + sy*sr,
    sy*cp,  sy*sp*sr + cy*cr,  sy*sp*cr - cy*sr,
    -sp,    cp*sr,             cp*cr,
  ];
}

function _mv3(R, v) {
  return [
    R[0]*v[0] + R[1]*v[1] + R[2]*v[2],
    R[3]*v[0] + R[4]*v[1] + R[5]*v[2],
    R[6]*v[0] + R[7]*v[1] + R[8]*v[2],
  ];
}

function _transposeR(R) {
  return [R[0],R[3],R[6], R[1],R[4],R[7], R[2],R[5],R[8]];
}

function _dsAltitude(ds, R) {
  if (ds.rangefinder_m > 0.3) {
    const rng = _mv3(R, [0, 0, 1]);
    return ds.rangefinder_m * rng[2];
  }
  return ds.altitude_rel_home || 0;
}

/** Back-project pixel (px,py) to ground lat/lon using drone state dict. */
function pixelToLatLon(ds, px, py) {
  if (!ds) return null;
  const { roll, pitch, yaw } = _dsRot(ds);
  const R = _buildR(roll, pitch, yaw);
  const h = _dsAltitude(ds, R);
  if (h <= 0) return null;

  const xc = (px - CAM_CX) / CAM_FX;
  const yc = (py - CAM_CY) / CAM_FY;
  const ray = [xc, yc, 1];
  const len = Math.sqrt(xc*xc + yc*yc + 1);
  ray[0] /= len; ray[1] /= len; ray[2] /= len;
  const rNED = _mv3(R, ray);
  if (rNED[2] <= 0.01) return null;
  const t = h / rNED[2];
  const N = t * rNED[0];
  const E = t * rNED[1];
  const lat = (ds.latitude || 0) + N / 111320;
  const lon = (ds.longitude || 0) + E / (111320 * Math.cos((ds.latitude || 0) * Math.PI / 180));
  return { lat, lon };
}

/** Project ground lat/lon to pixel (px,py) using drone state dict. null if behind camera or out of frame. */
function latLonToPixel(ds, lat, lon) {
  if (!ds) return null;
  const { roll, pitch, yaw } = _dsRot(ds);
  const R = _buildR(roll, pitch, yaw);
  const h = _dsAltitude(ds, R);
  if (h <= 0) return null;

  const N = (lat - (ds.latitude || 0)) * 111320;
  const E = (lon - (ds.longitude || 0)) * (111320 * Math.cos((ds.latitude || 0) * Math.PI / 180));
  const ned = [N, E, h];
  const rb = _mv3(_transposeR(R), ned);
  if (rb[2] <= 0) return null;
  const px = CAM_CX + CAM_FX * (rb[0] / rb[2]);
  const py = CAM_CY + CAM_FY * (rb[1] / rb[2]);
  if (px < -50 || px > CAM_PIX + 50 || py < -50 || py > CAM_PIX + 50) return null;
  return { px, py };
}

// ---------------------------------------------------------------------------
// Cross-frame weed prediction index (uses camera geometry, not GPS dot)
// ---------------------------------------------------------------------------
/**
 * Map<weed_id, Array<{frameIdx, bbox:{x1,y1,x2,y2,cx,cy}, label, ds, ts}>>
 * Stores the actual YOLO bbox + drone state so we can re-project corners.
 */
let weedDetIndex = new Map();
let weedSkipStreak = new Map();  // weed_id → number of consecutive recent skips
let currentPredictedBoxes = [];

/** @param {Set<string>|null} onlyWeedIds — full rebuild if null, incremental if provided */
function buildWeedDetectionIndex(onlyWeedIds) {
  const idx = onlyWeedIds ? weedDetIndex : new Map();
  if (onlyWeedIds) {
    for (const wid of onlyWeedIds) idx.delete(wid);
  }

  for (let fi = 0; fi < frames.length; fi++) {
    const f = frames[fi];
    // Quick skip: if scoped, only process frames that contain a relevant weed
    if (onlyWeedIds) {
      let relevant = false;
      for (const m of f.matches || []) { if (onlyWeedIds.has(m.weed_id)) { relevant = true; break; } }
      if (!relevant) continue;
    }
    const ts = Number(f.timestamp_ns) || 0;
    const ds = f.drone_state;

    if (decisions[f.timestamp_ns] === 'approved') {
      const manuals = getManualBboxes(f).filter(m => manualBboxIsValid(m));
      for (const mb of manuals) {
        const b = normalizeManualBbox(mb);
        for (const m of f.matches || []) {
          if (onlyWeedIds && !onlyWeedIds.has(m.weed_id)) continue;
          const wid = m.weed_id;
          if (!idx.has(wid)) idx.set(wid, []);
          idx.get(wid).push({
            frameIdx: fi, ts, manual: true,
            bbox: { x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2, cx: (b.x1+b.x2)/2, cy: (b.y1+b.y2)/2 },
            label: b.label || DEFAULT_MANUAL_LABEL,
            ds,
          });
          break;
        }
      }
      continue;
    }

    for (const m of f.matches || []) {
      if (onlyWeedIds && !onlyWeedIds.has(m.weed_id)) continue;
      if (!m.yolo_bbox || isIgnoredTrainingDet(m.yolo_bbox)) continue;
      if (!isWeedProxyTrainingDet(m.yolo_bbox)) continue;
      const b = m.yolo_bbox;
      const wid = m.weed_id;
      if (!idx.has(wid)) idx.set(wid, []);
      idx.get(wid).push({
        frameIdx: fi, ts, manual: false,
        bbox: { x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2, cx: b.cx, cy: b.cy },
        label: b.label || '',
        ds,
      });
    }
  }
  weedDetIndex = idx;

  // Skip-streak: only rebuild for affected weeds if scoped
  const weedFrames = new Map();
  for (const f of frames) {
    const ts = Number(f.timestamp_ns) || 0;
    const dec = decisions[f.timestamp_ns] || null;
    for (const m of f.matches || []) {
      if (onlyWeedIds && !onlyWeedIds.has(m.weed_id)) continue;
      if (!weedFrames.has(m.weed_id)) weedFrames.set(m.weed_id, []);
      weedFrames.get(m.weed_id).push({ ts, dec });
    }
  }
  for (const [wid, entries] of weedFrames) {
    entries.sort((a, b) => b.ts - a.ts);
    let streak = 0;
    for (const e of entries) {
      if (e.dec === 'skipped') streak++;
      else break;
    }
    weedSkipStreak.set(wid, streak);
  }
  if (!onlyWeedIds) {
    // Full rebuild: clear streaks for weeds not found
    const newStreaks = new Map();
    for (const [wid, s] of weedSkipStreak) {
      if (weedFrames.has(wid)) newStreaks.set(wid, s);
    }
    weedSkipStreak = newStreaks;
  }
}

/**
 * Predict bbox in current frame for a weed by re-projecting the nearest
 * detected bbox through camera geometry: prev-pixel → ground lat/lon → cur-pixel.
 */
function predictBboxForWeed(weedId, curDs, curTs) {
  const entries = weedDetIndex.get(weedId);
  if (!entries || !entries.length || !curDs) return null;
  let best = null, bestDt = Infinity;
  for (const e of entries) {
    const dt = Math.abs(e.ts - curTs);
    const better = dt < bestDt || (dt === bestDt && e.manual && (!best || !best.manual));
    if (better) { bestDt = dt; best = e; }
  }
  if (!best || !best.ds) return null;

  const corners = [
    [best.bbox.x1, best.bbox.y1],
    [best.bbox.x2, best.bbox.y1],
    [best.bbox.x2, best.bbox.y2],
    [best.bbox.x1, best.bbox.y2],
  ];
  const projected = [];
  for (const [px, py] of corners) {
    const ll = pixelToLatLon(best.ds, px, py);
    if (!ll) return null;
    const pp = latLonToPixel(curDs, ll.lat, ll.lon);
    if (!pp) return null;
    projected.push(pp);
  }
  const xs = projected.map(p => p.px);
  const ys = projected.map(p => p.py);
  const x1 = Math.min(...xs), y1 = Math.min(...ys);
  const x2 = Math.max(...xs), y2 = Math.max(...ys);
  if (x2 - x1 < 2 || y2 - y1 < 2) return null;
  return {
    x1, y1, x2, y2,
    cx: (x1 + x2) / 2, cy: (y1 + y2) / 2,
    w: x2 - x1, h: y2 - y1,
    label: best.label,
  };
}

function scoreCandidateMatch(det, predCx, predCy, predicted) {
  const dx = det.cx - predCx;
  const dy = det.cy - predCy;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (!predicted) return dist;

  const detW = det.x2 - det.x1, detH = det.y2 - det.y1;
  const sizeRatio = Math.max(detW, 1) / Math.max(predicted.w, 1);
  const sizeScore = Math.abs(Math.log(Math.max(sizeRatio, 0.01)));

  const labelMatch = predicted.label &&
    det.label != null &&
    String(det.label).trim().toLowerCase() === String(predicted.label).trim().toLowerCase();
  const labelPenalty = labelMatch ? 0 : 1;

  return dist * 0.6 + sizeScore * 80 * 0.25 + labelPenalty * 40 * 0.15;
}

function buildPredictedBoxesForFrame(f) {
  currentPredictedBoxes = [];
  if (!f || !f.matches || !f.drone_state) return;
  const curDs = f.drone_state;
  const ts = Number(f.timestamp_ns) || 0;
  for (const m of f.matches) {
    if (m.yolo_bbox && !isIgnoredTrainingDet(m.yolo_bbox)) continue;
    const pred = predictBboxForWeed(m.weed_id, curDs, ts);
    if (!pred) continue;
    const streak = weedSkipStreak.get(m.weed_id) || 0;
    const uncertain = streak >= 2;
    currentPredictedBoxes.push({
      weed_id: m.weed_id,
      x1: pred.x1, y1: pred.y1,
      x2: pred.x2, y2: pred.y2,
      cx: pred.cx, cy: pred.cy,
      w: pred.w, h: pred.h,
      label: pred.label || DEFAULT_MANUAL_LABEL,
      conf: DEFAULT_MANUAL_CONF,
      skipStreak: streak,
      uncertain,
    });
  }
}

function findPredictedBoxAt(x, y) {
  for (const pb of currentPredictedBoxes) {
    if (x >= pb.x1 && x <= pb.x2 && y >= pb.y1 && y <= pb.y2) return pb;
  }
  return null;
}

function findBetterCandidateForMatch(f, m) {
  if (!m.yolo_bbox || isIgnoredTrainingDet(m.yolo_bbox)) return null;
  if (!f.drone_state) return null;
  const curDs = f.drone_state;
  const ts = Number(f.timestamp_ns) || 0;
  const pred = predictBboxForWeed(m.weed_id, curDs, ts);
  if (!pred) return null;

  const currentScore = scoreCandidateMatch(m.yolo_bbox, pred.cx, pred.cy, pred);
  let bestAlt = null, bestAltScore = currentScore;
  for (const det of f.all_yolo_dets || []) {
    if (isIgnoredTrainingDet(det)) continue;
    if (det === m.yolo_bbox) continue;
    if (det.x1 === m.yolo_bbox.x1 && det.y1 === m.yolo_bbox.y1) continue;
    const s = scoreCandidateMatch(det, pred.cx, pred.cy, pred);
    if (s < bestAltScore * 0.75) {
      bestAltScore = s;
      bestAlt = det;
    }
  }
  return bestAlt;
}

/** Auto-reassign matches to better candidates using prediction scoring.
 *  Also drops non-weed-proxy matches when no weed-proxy alternative exists.
 *  Skips the frame the user is currently viewing to avoid disruption.
 *  @param {Set<string>|null} onlyWeedIds — if provided, only process matches for these weed_ids */
function autoReassignMatches(onlyWeedIds) {
  if (weedDetIndex.size === 0) return;
  const curTs = currentIdx >= 0 && frames[currentIdx]
    ? frames[currentIdx].timestamp_ns : null;
  for (const f of frames) {
    if (!f.drone_state) continue;
    if (decisions[f.timestamp_ns]) continue;
    if (f.timestamp_ns === curTs) continue;
    // Quick skip: if scoped, check if this frame has any relevant weed_id
    if (onlyWeedIds) {
      let relevant = false;
      for (const m of f.matches) { if (onlyWeedIds.has(m.weed_id)) { relevant = true; break; } }
      if (!relevant) continue;
    }
    for (const m of f.matches) {
      if (onlyWeedIds && !onlyWeedIds.has(m.weed_id)) continue;
      if (!m.yolo_bbox || isIgnoredTrainingDet(m.yolo_bbox)) continue;

      const streak = weedSkipStreak.get(m.weed_id) || 0;
      if (streak >= 2) continue;

      if (!isWeedProxyTrainingDet(m.yolo_bbox)) {
        let proxyFound = null;
        for (const det of f.all_yolo_dets || []) {
          if (isIgnoredTrainingDet(det) || !isWeedProxyTrainingDet(det)) continue;
          const dx = det.cx - m.gps_px, dy = det.cy - m.gps_py;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d <= distThresh) {
            if (!proxyFound || d < proxyFound.d) proxyFound = { det, d };
          }
        }
        if (proxyFound) {
          m.yolo_bbox = proxyFound.det;
          m.dist_px = Math.round(proxyFound.d * 10) / 10;
        } else {
          m.yolo_bbox = null;
          m.dist_px = null;
        }
        continue;
      }

      const better = findBetterCandidateForMatch(f, m);
      if (better) {
        const dx = better.cx - m.gps_px;
        const dy = better.cy - m.gps_py;
        m.yolo_bbox = better;
        m.dist_px = Math.round(Math.sqrt(dx * dx + dy * dy) * 10) / 10;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Manual bbox override (640×640, same as canvas).
// ---------------------------------------------------------------------------
function roundCoord1(x) {
  return Math.round(Number(x) * 10) / 10;
}

function manualBboxIsValid(m) {
  if (!m) return false;
  const x1 = Number(m.x1), y1 = Number(m.y1), x2 = Number(m.x2), y2 = Number(m.y2);
  if (![x1, y1, x2, y2].every(Number.isFinite)) return false;
  if (x2 - x1 < 2 || y2 - y1 < 2) return false;
  if (x1 < 0 || y1 < 0 || x2 > 640 || y2 > 640) return false;
  return true;
}

function normalizeManualBbox(m) {
  let x1 = Number(m.x1), y1 = Number(m.y1), x2 = Number(m.x2), y2 = Number(m.y2);
  if (x2 < x1) {
    const t = x1;
    x1 = x2;
    x2 = t;
  }
  if (y2 < y1) {
    const t = y1;
    y1 = y2;
    y2 = t;
  }
  x1 = Math.max(0, Math.min(640, x1));
  x2 = Math.max(0, Math.min(640, x2));
  y1 = Math.max(0, Math.min(640, y1));
  y2 = Math.max(0, Math.min(640, y2));
  if (x2 - x1 < 2) x2 = Math.min(640, x1 + 2);
  if (y2 - y1 < 2) y2 = Math.min(640, y1 + 2);
  const label =
    m.label != null && String(m.label).trim() !== '' ? String(m.label).trim() : 'sports ball';
  let conf = Number(m.conf);
  if (!Number.isFinite(conf)) conf = 0.99;
  conf = Math.min(1, Math.max(0, conf));
  return {
    x1: roundCoord1(x1),
    y1: roundCoord1(y1),
    x2: roundCoord1(x2),
    y2: roundCoord1(y2),
    cx: roundCoord1((x1 + x2) / 2),
    cy: roundCoord1((y1 + y2) / 2),
    label,
    conf,
  };
}

function migrateManualBboxesOnFrame(f) {
  if (!f._manual_bboxes) {
    if (f._manual_bbox && manualBboxIsValid(f._manual_bbox)) {
      f._manual_bboxes = [normalizeManualBbox(f._manual_bbox)];
    } else {
      f._manual_bboxes = [];
    }
  }
  if (f._manual_bbox) delete f._manual_bbox;
}

function getManualBboxes(f) {
  if (!f) return [];
  migrateManualBboxesOnFrame(f);
  return f._manual_bboxes && f._manual_bboxes.length ? f._manual_bboxes : [];
}

function yoloDetToManualNorm(det) {
  if (!det) return null;
  return normalizeManualBbox({
    x1: det.x1,
    y1: det.y1,
    x2: det.x2,
    y2: det.y2,
    label: det.label,
    conf: det.conf,
  });
}

function bboxesNearlyEqual(a, b) {
  if (!a || !b) return false;
  const tol = 1.5;
  return (
    Math.abs(a.x1 - b.x1) < tol &&
    Math.abs(a.y1 - b.y1) < tol &&
    Math.abs(a.x2 - b.x2) < tol &&
    Math.abs(a.y2 - b.y2) < tol
  );
}

function addManualBboxFromUser(f, norm, append) {
  if (!f || !norm) return;
  f._explicit_empty = false;
  migrateManualBboxesOnFrame(f);
  if (!append) {
    f._manual_bboxes = [norm];
  } else {
    const list = (f._manual_bboxes || []).slice();
    if (!list.some(b => bboxesNearlyEqual(b, norm))) list.push(norm);
    f._manual_bboxes = list;
  }
  delete f._manual_bbox;
}

/** Remove YOLO boxes from frame data (GPS weed dots stay). Sets _ai_predictions_removed. */
function stripYoloPredictionsFromFrame(f) {
  if (!f) return;
  f.all_yolo_dets = [];
  for (const m of f.matches || []) {
    m.yolo_bbox = null;
  }
  f._ai_predictions_removed = true;
}

/** Clear manual boxes, strip all on-canvas detections (YOLO + extras), mark empty — then A for negative. */
function clearManualAllCurrentFrame() {
  if (currentIdx < 0 || currentIdx >= frames.length) return;
  const f = frames[currentIdx];
  f._manual_bboxes = [];
  delete f._manual_bbox;
  f._explicit_empty = true;
  stripYoloPredictionsFromFrame(f);
  errorBanner.style.display = 'none';
  reEvaluateFrameStatus(f);
  updateCounts();
  refreshFilmstripThumbBadge(currentIdx);
  syncManualBboxFormFromFrame();
  updateFrameInfo(f);
  if (saveResult) saveResult.textContent = '';
  if (canvasBaseImage) paintCanvas(currentIdx);
  else renderFrame(currentIdx);
}

/** Drop server YOLO boxes on this frame only (GPS weed dots stay). Del key / Clear AI. */
function clearAiPredictionsOnCurrentFrame() {
  if (currentIdx < 0 || currentIdx >= frames.length) return;
  const f = frames[currentIdx];
  stripYoloPredictionsFromFrame(f);
  errorBanner.style.display = 'none';
  reEvaluateFrameStatus(f);
  updateCounts();
  refreshFilmstripThumbBadge(currentIdx);
  updateFrameInfo(f);
  if (saveResult) saveResult.textContent = '';
  if (canvasBaseImage) paintCanvas(currentIdx);
  else renderFrame(currentIdx);
}

function findYoloDetAt(f, x, y) {
  let best = null;
  let bestConf = -1;
  const tryDet = det => {
    if (!det || isIgnoredTrainingDet(det)) return;
    const b = det;
    if (x >= b.x1 && x <= b.x2 && y >= b.y1 && y <= b.y2) {
      const c = Number(b.conf) || 0;
      if (c > bestConf) {
        bestConf = c;
        best = det;
      }
    }
  };
  for (const m of f.matches || []) {
    if (m.yolo_bbox) tryDet(m.yolo_bbox);
  }
  for (const det of f.all_yolo_dets || []) tryDet(det);
  return best;
}

function canvasPointerCoords(e) {
  const r = canvas.getBoundingClientRect();
  const sx = 640 / Math.max(1, r.width);
  const sy = 640 / Math.max(1, r.height);
  let px = (e.clientX - r.left) * sx;
  let py = (e.clientY - r.top) * sy;
  px = Math.max(0, Math.min(640, px));
  py = Math.max(0, Math.min(640, py));
  return [px, py];
}

function rectFromDrag(x0, y0, x1, y1) {
  return {
    x1: Math.min(x0, x1),
    y1: Math.min(y0, y1),
    x2: Math.max(x0, x1),
    y2: Math.max(y0, y1),
    label: DEFAULT_MANUAL_LABEL,
    conf: DEFAULT_MANUAL_CONF,
  };
}

function abortCanvasDrag() {
  document.removeEventListener('mousemove', onCanvasDragMove);
  document.removeEventListener('mouseup', onCanvasDragUp);
  dragSelect = null;
}

function syncManualBboxFormFromFrame() {
  const can = currentIdx >= 0 && currentIdx < frames.length;
  if (manualFromYoloBtn) manualFromYoloBtn.disabled = !can;
  if (clearAiPredsBtn) clearAiPredsBtn.disabled = !can;
  if (manualClearBtn) manualClearBtn.disabled = !can;
}

function getYoloFallbackApproveBbox(f) {
  const match = bestMatch(f);
  return match && match.yolo_bbox ? match.yolo_bbox : null;
}

function frameHasWeedProxyDetection(fr) {
  const dets = fr && fr.all_yolo_dets;
  if (!Array.isArray(dets) || dets.length === 0) return false;
  for (let i = 0; i < dets.length; i++) {
    const d = dets[i];
    const raw = d && d.label != null ? String(d.label) : '';
    const s = raw.trim().toLowerCase();
    if (TRAINING_WEED_PROXY_LABELS.has(s)) return true;
  }
  return false;
}

/** In-place sort: proxy detections first, then chronological. */
function sortFramesProxyFirst(arr) {
  arr.sort((a, b) => {
    const pa = frameHasWeedProxyDetection(a) ? 0 : 1;
    const pb = frameHasWeedProxyDetection(b) ? 0 : 1;
    if (pa !== pb) return pa - pb;
    const ta = Number(a.timestamp_ns) || 0;
    const tb = Number(b.timestamp_ns) || 0;
    return ta - tb;
  });
}

function applyProxySortAndRemapCurrentFrame() {
  const prevTs = currentIdx >= 0 && frames[currentIdx] ? frames[currentIdx].timestamp_ns : null;
  sortFramesProxyFirst(frames);
  if (prevTs != null) {
    const ni = frames.findIndex((f) => Number(f.timestamp_ns) === Number(prevTs));
    if (ni >= 0) currentIdx = ni;
  }
  reEvaluateStatuses();
  renderFilmstrip();
  updateCounts();
  if (currentIdx >= 0) {
    frameCounter.textContent = `${currentIdx + 1} / ${frames.length}`;
    filmstripEnsureImgForIndex(currentIdx);
    renderFrame(currentIdx);
  }
}

/** Coarse-to-fine: first pass uses a high stride, then halves until ``targetStride`` (slider value). */
const STRIDE_PROGRESS_MAX = 50;

function buildStrideSequence(targetStride) {
  const t = Math.max(1, Math.min(500, Math.floor(Number(targetStride)) || 1));
  const cap = STRIDE_PROGRESS_MAX;
  let s = Math.min(cap, Math.max(t * 8, t));
  const out = [];
  while (s > t) {
    out.push(s);
    const next = Math.floor(s / 2);
    s = Math.max(t, next);
  }
  out.push(t);
  const seen = new Set();
  const dedup = [];
  for (const x of out) {
    if (seen.has(x)) continue;
    seen.add(x);
    dedup.push(x);
  }
  return dedup;
}

let _frameTsIndex = null; // Map<timestamp_ns_number, index_in_frames> — rebuilt on sort

function _ensureFrameTsIndex() {
  if (_frameTsIndex && _frameTsIndex._len === frames.length) return;
  _frameTsIndex = new Map();
  for (let i = 0; i < frames.length; i++) _frameTsIndex.set(Number(frames[i].timestamp_ns), i);
  _frameTsIndex._len = frames.length;
}

function mergeBatchIntoFrames(acc, batch) {
  if (!batch || !batch.length) return;
  _ensureFrameTsIndex();
  let needsSort = false;
  for (const f of batch) {
    const ts = Number(f.timestamp_ns);
    const idx = _frameTsIndex.has(ts) ? _frameTsIndex.get(ts) : -1;
    if (idx >= 0) {
      const old = acc[idx];
      const manList = old._manual_bboxes;
      const manOne = old._manual_bbox;
      const ex = old._explicit_empty;
      acc[idx] = f;
      if (manList && manList.length) {
        acc[idx]._manual_bboxes = manList.slice();
        delete acc[idx]._manual_bbox;
      } else if (manOne && manualBboxIsValid(manOne)) {
        acc[idx]._manual_bboxes = [normalizeManualBbox(manOne)];
        delete acc[idx]._manual_bbox;
      }
      if (ex) acc[idx]._explicit_empty = true;
    } else {
      acc.push(f);
      needsSort = true;
    }
  }
  if (needsSort) {
    acc.sort((a, b) => Number(a.timestamp_ns) - Number(b.timestamp_ns));
  }
  _frameTsIndex = null;
}

function enableTrainingNavButtons() {
  saveBtn.disabled = false;
  approveBtn.disabled = false;
  skipBtn.disabled = false;
  if (undoBtn) undoBtn.disabled = decisionHistory.length === 0;
  prevBtn.disabled = false;
  nextBtn.disabled = false;
  if (nextReviewBtn) nextReviewBtn.disabled = false;
  syncCompareModelsBtn();
  syncManualBboxFormFromFrame();
  ensureLabelerSessionClock();
}

// ---------------------------------------------------------------------------
// Run analysis
// ---------------------------------------------------------------------------
runBtn.addEventListener('click', async () => {
  const realMission = realMissionSelect.value;
  if (!realMission) return;

  const focusTsThisRun =
    focusNearCurrentChk && focusNearCurrentChk.checked && currentIdx >= 0 && frames[currentIdx]
      ? Number(frames[currentIdx].timestamp_ns)
      : null;

  trainingAnalyzeAbort = new AbortController();
  const { signal } = trainingAnalyzeAbort;
  syncAnalyzeStopButton(true);
  resetModelCompareForNewFrame();
  syncCompareModelsBtn();

  runBtn.disabled = true;
  runProgress.style.display = '';
  errorBanner.style.display = 'none';
  frames = [];
  canvasImageCacheClear();
  decisions = {};
  decisionHistory = [];
  resetLabelerMetrics();
  syncUndoButton();
  currentIdx = -1;
  teardownFilmstripImageObserver();
  filmstrip.innerHTML = '';
  ctx2d.clearRect(0, 0, 640, 640);
  frameCounter.textContent = '— / —';

  const targetStride = Math.max(1, Math.min(500, parseInt(String(frameStride), 10) || 1));
  const useProgressiveStride = !progressiveStrideChk || progressiveStrideChk.checked;
  const strideSeq = useProgressiveStride ? buildStrideSequence(targetStride) : [targetStride];
  const t0 = performance.now();
  let statusTimer = startAnalysisStatusUI(realMission, null);

  persistYoloInputs();

  let lastInfer = 'unknown';
  let lastDeviceOverride = null;
  let lastModelSpec = null;
  let anyCached = false;
  let analysisStoppedBad = false;

  try {
    passLoop:
    for (let pi = 0; pi < strideSeq.length; pi++) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const passStride = strideSeq[pi];
      const mergeRefine = pi > 0;

      if (progressHint) {
        progressHint.style.display = '';
        if (strideSeq.length > 1) {
          progressHint.innerHTML =
            '<strong>Progressive stride ' + (pi + 1) + '/' + strideSeq.length + '.</strong> ' +
            'Step <strong>' + passStride + '</strong> → target <strong>' + targetStride + '</strong>. ' +
            (mergeRefine
              ? 'Refining: more frames and updated YOLO…'
              : 'Starting with a coarse step (fewer frames); quality improves on later passes.');
        } else {
          const near =
            focusTsThisRun != null && Number.isFinite(focusTsThisRun)
              ? ' <span class="muted">YOLO batches favor the timeline around where you were.</span>'
              : '';
          progressHint.innerHTML =
            '<strong>Streaming.</strong> Filmstrip and counts update as each YOLO batch finishes.' + near;
        }
      }

      let nFramesKnownPass = null;
      try {
        const cr = await fetch(
          `/missions/${MISSION_ID}/training/frame_count?src=${encodeURIComponent(SRC)}&stride=${encodeURIComponent(String(passStride))}`,
          { signal }
        );
        const cd = await cr.json();
        if (cr.ok && cd.ok && typeof cd.n_frames === 'number') {
          nFramesKnownPass = cd.n_frames;
          _lastFrameCount = cd.n_frames;
          _frameCountByStride[passStride] = cd.n_frames;
        }
      } catch (_e) { /* optional preflight */ }

      const resp = await fetch(
        `/missions/${MISSION_ID}/training/analyze?src=${encodeURIComponent(SRC)}&stream=1`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(
            buildAnalyzeRequestBody(realMission, passStride, {
              focus_timestamp_ns: focusTsThisRun,
            })
          ),
          signal,
        }
      );

      const ctype = (resp.headers.get('content-type') || '').toLowerCase();

      if (!resp.ok) {
        if (statusTimer != null) {
          clearInterval(statusTimer);
          statusTimer = null;
        }
        let errMsg = 'Analysis failed';
        try {
          const j = await resp.json();
          errMsg = j.error || errMsg;
        } catch (_e) {
          try {
            errMsg = (await resp.text()) || errMsg;
          } catch (_e2) { /* keep default */ }
        }
        showError(errMsg);
        frameInfo.innerHTML = '<span class="muted">Analysis failed.</span>';
        if (progressHint) progressHint.style.display = 'none';
        analysisStoppedBad = true;
        break passLoop;
      }

      if (!ctype.includes('ndjson')) {
        if (statusTimer != null) {
          clearInterval(statusTimer);
          statusTimer = null;
        }
        const data = await resp.json();
        if (!data.ok) {
          showError(data.error || 'Analysis failed');
          frameInfo.innerHTML = '<span class="muted">Analysis failed.</span>';
          if (progressHint) progressHint.style.display = 'none';
          analysisStoppedBad = true;
          break passLoop;
        }
        const inc = data.results || [];
        if (mergeRefine) mergeBatchIntoFrames(frames, inc);
        else frames = inc.slice();
        if (data.inference_device != null) lastInfer = String(data.inference_device);
        if (data.device_override !== undefined) lastDeviceOverride = data.device_override;
        anyCached = anyCached || !!data.cached;
        if (frames.length === 0 && !mergeRefine) {
          frameInfo.innerHTML = '<span class="muted">No frames returned — check <code>frames/</code> for JPEGs.</span>';
          if (progressHint) progressHint.style.display = 'none';
          analysisStoppedBad = true;
          break passLoop;
        }
        applyProxySortAndRemapCurrentFrame();
        enableTrainingNavButtons();
        continue;
      }

      let buf = '';
      let nTarget = nFramesKnownPass;
      let inferDev = 'unknown';
      let streamModelSpec = null;
      let deviceOverride = null;
      let cached = false;
      let streamFailed = false;
      let clearedStatusTimer = false;
      const reader = resp.body.getReader();
      const dec = new TextDecoder();

      const passTag =
        strideSeq.length > 1
          ? ' <span class="muted">(stride ' + passStride + ', pass ' + (pi + 1) + '/' + strideSeq.length + ')</span>'
          : '';

      const handleStreamObject = obj => {
        if (obj.type === 'meta') {
          if (typeof obj.n_frames === 'number') nTarget = obj.n_frames;
          if (obj.diagnostics) {
            const d = obj.diagnostics;
            let hwNote = '';
            if (d.cuda_available) {
              hwNote = 'CUDA is on — YOLO usually runs on the <strong>GPU</strong>. Expect load in <code>nvidia-smi</code>; <strong>CPU % can stay low</strong> and RAM only rises modestly.';
              if (d.cuda_device) hwNote += ' Device: <code>' + escapeHtml(String(d.cuda_device)) + '</code>.';
            } else if (d.mps_available) {
              hwNote = 'Apple Metal available — watch GPU in Activity Monitor; CPU may look quiet.';
            } else {
              hwNote = 'No CUDA in this PyTorch build — inference uses <strong>CPU</strong>; you should see Python CPU spike during each batch. If CPU stays flat, inference may not be running (check terminal for errors).';
            }
            if (d.model) streamModelSpec = String(d.model);
            hwNote += ' Batch size ' + (d.batch_size != null ? d.batch_size : '?') + ', model <code>' + escapeHtml(String(d.model || '?')) + '</code>, server PID <code>' + escapeHtml(String(d.pid || '?')) + '</code>.';
            hwNote += ' Tip: <code>SKYDOCK_TRAINING_VERBOSE=1 python3 tools/log_server/app.py</code> logs each batch to the terminal.';
            frameInfo.innerHTML = '<div class="small muted" style="line-height:1.5;max-width:820px">' + hwNote + '</div>';
          }
        }
        if (obj.type === 'batch' && Array.isArray(obj.frames)) {
          const prevTs = currentIdx >= 0 && frames[currentIdx]
            ? Number(frames[currentIdx].timestamp_ns) : null;
          if (mergeRefine) mergeBatchIntoFrames(frames, obj.frames);
          else frames.push(...obj.frames);
          for (const bf of obj.frames) reEvaluateFrameStatus(bf);
          if (prevTs != null) {
            _ensureFrameTsIndex();
            const ni = _frameTsIndex.has(prevTs) ? _frameTsIndex.get(prevTs) : -1;
            if (ni >= 0) currentIdx = ni;
          }
          updateCounts();
          renderFilmstrip();
          if (currentIdx >= 0) filmstripEnsureImgForIndex(currentIdx);
          {
            const elapsed = formatElapsed(performance.now() - t0);
            const loaded = frames.length;
            const total = nTarget || '?';
            const pct = nTarget ? Math.round(loaded / nTarget * 100) : 0;
            const barW = nTarget ? Math.min(100, Math.max(2, pct)) : 0;
            let etaStr = '';
            if (nTarget && loaded > 0 && loaded < nTarget) {
              const msPerFrame = (performance.now() - t0) / loaded;
              const remain = (nTarget - loaded) * msPerFrame;
              etaStr = ' · ETA ' + formatElapsed(remain);
            }
            const bar = nTarget
              ? '<div style="background:var(--sd-border);border-radius:4px;height:8px;width:100%;max-width:400px;margin:4px 0">' +
                '<div style="background:var(--sd-accent);border-radius:4px;height:100%;width:' + barW + '%;transition:width .3s"></div></div>'
              : '';
            frameInfo.innerHTML =
              '<div class="small">' +
              '<span class="stat-pill" style="font-size:13px;font-weight:600">' +
              'YOLO running — ' + loaded + ' / ' + total + ' frames (' + pct + '%)' +
              '</span> ' +
              '<span class="muted">' + elapsed + etaStr + '</span>' +
              passTag + bar + '</div>';
            runProgress.innerHTML =
              '<strong>YOLO running</strong> ' + loaded + '/' + total +
              ' (' + pct + '%) · ' + elapsed + etaStr;
          }
          if (currentIdx < 0 && frames.length > 0 && !mergeRefine) {
            let j = 0;
            if (focusTsThisRun != null && Number.isFinite(focusTsThisRun)) {
              let best = 0;
              let bestD = Infinity;
              for (let k = 0; k < frames.length; k++) {
                const d = Math.abs(Number(frames[k].timestamp_ns) - focusTsThisRun);
                if (d < bestD) {
                  bestD = d;
                  best = k;
                }
              }
              j = best;
            }
            jumpTo(j);
          } else if (currentIdx >= 0) {
            renderFrame(currentIdx);
          }
        }
        if (obj.type === 'done') {
          inferDev = obj.inference_device != null ? String(obj.inference_device) : 'unknown';
          deviceOverride = obj.device_override;
          cached = !!obj.cached;
        }
        if (obj.type === 'error' || obj.ok === false) {
          streamFailed = true;
          showError(obj.error || 'Analysis failed');
          frameInfo.innerHTML = '<span class="muted">Analysis failed.</span>';
          return false;
        }
        return true;
      };

      const consumeBufLines = () => {
        for (;;) {
          const nl = buf.indexOf('\n');
          if (nl < 0) break;
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          let obj;
          try {
            obj = JSON.parse(line);
          } catch (_e) {
            streamFailed = true;
            showError('Bad line from analysis stream');
            return false;
          }
          if (!clearedStatusTimer) {
            if (statusTimer != null) {
              clearInterval(statusTimer);
              statusTimer = null;
            }
            clearedStatusTimer = true;
          }
          if (!handleStreamObject(obj)) return false;
        }
        return true;
      };

      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (value && value.byteLength) buf += dec.decode(value, { stream: true });
          if (!consumeBufLines()) break;
          if (done) {
            buf += dec.decode();
            if (!consumeBufLines()) break;
            const tail = buf.trim();
            if (tail) {
              try {
                const obj = JSON.parse(tail);
                if (!clearedStatusTimer) {
                  if (statusTimer != null) {
                    clearInterval(statusTimer);
                    statusTimer = null;
                  }
                  clearedStatusTimer = true;
                }
                if (!handleStreamObject(obj)) break;
              } catch (_e) {
                streamFailed = true;
                showError('Bad trailing data from analysis stream');
              }
            }
            break;
          }
        }
      } finally {
        if (!clearedStatusTimer && statusTimer != null) {
          clearInterval(statusTimer);
          statusTimer = null;
        }
        try {
          reader.releaseLock();
        } catch (_e) { /* ignore */ }
      }

      if (streamFailed) {
        if (progressHint) progressHint.style.display = 'none';
        analysisStoppedBad = true;
        break passLoop;
      }

      if (frames.length === 0 && !mergeRefine) {
        frameInfo.innerHTML = '<span class="muted">No frames returned — check <code>frames/</code> for JPEGs.</span>';
        if (progressHint) progressHint.style.display = 'none';
        analysisStoppedBad = true;
        break passLoop;
      }

      lastInfer = inferDev;
      lastDeviceOverride = deviceOverride;
      if (streamModelSpec) lastModelSpec = streamModelSpec;
      anyCached = anyCached || cached;

      applyProxySortAndRemapCurrentFrame();
      enableTrainingNavButtons();
    }

    if (!analysisStoppedBad && frames.length > 0 && !signal.aborted) {
      finishAnalyzeSuccess(t0, lastInfer, lastDeviceOverride, anyCached, {
        progressivePasses: strideSeq.length,
        targetStride: targetStride,
        modelSpec: lastModelSpec,
      });
    } else if (!analysisStoppedBad && frames.length === 0 && !signal.aborted) {
      frameInfo.innerHTML = '<span class="muted">No frames returned — check <code>frames/</code> for JPEGs.</span>';
      if (progressHint) progressHint.style.display = 'none';
    }
  } catch(e) {
    if (statusTimer != null) {
      clearInterval(statusTimer);
      statusTimer = null;
    }
    if (e && e.name === 'AbortError') {
      errorBanner.style.display = 'none';
      if (progressHint) progressHint.style.display = 'none';
      if (frames.length > 0) {
        applyProxySortAndRemapCurrentFrame();
        frameInfo.innerHTML =
          '<div class="small" style="line-height:1.5;max-width:820px">' +
          '<span class="fw-semibold" style="color:var(--sd-warn, #c9a227)">Stopped.</span> ' +
          'Kept <strong>' + frames.length + '</strong> frame' + (frames.length === 1 ? '' : 's') +
          ' received before cancel. Server may still finish the current batch — that is normal.</div>';
      } else {
        frameInfo.innerHTML = '<span class="muted">Analysis stopped.</span>';
      }
    } else {
      showError(String(e));
      frameInfo.innerHTML = '<span class="muted">Request error — details in red banner or box above.</span>';
    }
  } finally {
    trainingAnalyzeAbort = null;
    syncAnalyzeStopButton(false);
    syncCompareModelsBtn();
    runBtn.disabled = false;
    runProgress.style.display = 'none';
    runProgress.innerHTML = '';
    if (progressHint) {
      progressHint.style.display = 'none';
      progressHint.innerHTML = '';
    }
  }
});

function finishAnalyzeSuccess(t0, inferDev, deviceOverride, cached, progressiveOpts) {
  const totalMs = performance.now() - t0;
  const n = frames.length;
  if (!cached && n > 0 && progressiveOpts && progressiveOpts.modelSpec) {
    const perFrame = totalMs / 1000 / n;
    cacheModelTiming(progressiveOpts.modelSpec, perFrame, inferDev, 'analysis');
    _lastFrameCount = n;
    showModelTimeEstimate();
  }
  let devExtra = ' Inference device: <code>' + escapeHtml(String(inferDev)) + '</code>.';
  if (deviceOverride != null && deviceOverride !== '') {
    devExtra += ' Override: <code>' + escapeHtml(String(deviceOverride)) + '</code>.';
  }
  let progNote = '';
  if (
    progressiveOpts &&
    progressiveOpts.progressivePasses > 1 &&
    progressiveOpts.targetStride != null
  ) {
    progNote =
      ' <span class="muted">Progressive stride: ' +
      progressiveOpts.progressivePasses +
      ' passes down to step ' +
      escapeHtml(String(progressiveOpts.targetStride)) +
      '.</span>';
  }
  frameInfo.innerHTML =
    '<div class="small" style="line-height:1.5;max-width:820px">' +
    '<span class="fw-semibold" style="color:var(--sd-better)">Done.</span> ' +
    n + ' frame' + (n === 1 ? '' : 's') + ' in ' + formatElapsed(totalMs) +
    (cached ? ' <span class="muted">(server cache — no new YOLO run)</span>' : '') +
    '.' +
    progNote +
    ' Review queue opens on the first frame that needs attention.' +
    devExtra + '</div>';

  saveBtn.disabled = false;
  approveBtn.disabled = false;
  skipBtn.disabled = false;
  if (undoBtn) undoBtn.disabled = decisionHistory.length === 0;
  prevBtn.disabled = false;
  nextBtn.disabled = false;
  syncCompareModelsBtn();

  buildWeedDetectionIndex();
  autoReassignMatches();
  reEvaluateStatuses();
  updateCounts();
  const firstReview = frames.findIndex(f => (f._status_live || f.status) === 'review');
  jumpTo(firstReview >= 0 ? firstReview : 0);
}

// ---------------------------------------------------------------------------
// Filmstrip
// ---------------------------------------------------------------------------
function renderFilmstrip() {
  teardownFilmstripImageObserver();
  filmstrip.innerHTML = '';
  for (let i = 0; i < frames.length; i++) {
    const f = frames[i];
    const st = effectiveStatus(f);
    const div = document.createElement('div');
    div.className = 'fs-thumb' + (i === currentIdx ? ' active' : '');
    div.dataset.idx = String(i);

    const img = document.createElement('img');
    img.alt = '';
    img.src = FILMSTRIP_IMG_PLACEHOLDER;
    div.appendChild(img);

    const badge = document.createElement('span');
    badge.className = `fs-badge badge-${st}`;
    badge.textContent = st === 'auto' ? 'A' : st === 'review' ? '?' : st === 'approved' ? '✓' : st === 'skipped' ? '✗' : '—';
    div.appendChild(badge);

    div.addEventListener('click', () => jumpTo(i));
    filmstrip.appendChild(div);
  }
  setupFilmstripImageObserver();
}

function setFilmstripActive(prevIdx, nextIdx) {
  if (prevIdx >= 0 && prevIdx < filmstrip.children.length) {
    filmstrip.children[prevIdx].classList.remove('active');
  }
  if (nextIdx >= 0 && nextIdx < filmstrip.children.length) {
    filmstrip.children[nextIdx].classList.add('active');
  }
}

function refreshFilmstripThumbBadge(idx) {
  if (idx < 0 || idx >= frames.length) return;
  const t = filmstrip.children[idx];
  if (!t) return;
  const badge = t.querySelector('.fs-badge');
  if (!badge) return;
  const st = effectiveStatus(frames[idx]);
  badge.className = `fs-badge badge-${st}`;
  badge.textContent = st === 'auto' ? 'A' : st === 'review' ? '?' : st === 'approved' ? '✓' : st === 'skipped' ? '✗' : '—';
}

// ---------------------------------------------------------------------------
// Frame rendering
// ---------------------------------------------------------------------------
function jumpTo(idx) {
  if (idx < 0 || idx >= frames.length) return;
  abortCanvasDrag();
  resetModelCompareForNewFrame();
  const prevIdx = currentIdx;
  currentIdx = idx;
  frameCounter.textContent = `${idx + 1} / ${frames.length}`;
  renderFrame(idx);
  setFilmstripActive(prevIdx, idx);
  filmstripEnsureImgForIndex(idx);
  // Scroll filmstrip to show active thumb
  const thumb = filmstrip.children[idx];
  if (thumb) thumb.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' });
  syncCompareModelsBtn();
  syncManualBboxFormFromFrame();
}

function renderFrame(idx) {
  const f = frames[idx];
  const token = ++canvasLoadToken;

  buildPredictedBoxesForFrame(f);

  const paintFromBitmap = img => {
    if (token !== canvasLoadToken || idx !== currentIdx) return;
    canvasBaseImage = img;
    paintCanvas(idx);
    updateFrameInfo(f);
    syncManualBboxFormFromFrame();
  };

  const cached = canvasImageCacheGet(f.frame_path);
  if (cached && cached.complete && cached.naturalWidth > 0) {
    paintFromBitmap(cached);
    return;
  }

  const img = new Image();
  img.src = frameImageSrcCanvas(f);
  img.onload = () => {
    if (img.naturalWidth > 0) canvasImageCacheSet(f.frame_path, img);
    paintFromBitmap(img);
  };
  img.onerror = () => {
    if (token !== canvasLoadToken || idx !== currentIdx) return;
    canvasBaseImage = null;
    ctx2d.clearRect(0, 0, 640, 640);
    ctx2d.fillStyle = '#222';
    ctx2d.fillRect(0, 0, 640, 640);
    ctx2d.fillStyle = '#888';
    ctx2d.font = '14px monospace';
    ctx2d.fillText('Image not found', 20, 320);
  };
}

if (canvas) {
  canvas.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    if (currentIdx < 0 || currentIdx >= frames.length) return;
    const [px, py] = canvasPointerCoords(e);
    dragSelect = { x0: px, y0: py, x1: px, y1: py };
    document.addEventListener('mousemove', onCanvasDragMove);
    document.addEventListener('mouseup', onCanvasDragUp);
    if (canvasBaseImage) paintCanvas(currentIdx);
  });
}

function yoloLabelText(b) {
  const lab = (b.label != null && String(b.label).trim() !== '') ? String(b.label).trim() : '';
  const pct = `${(b.conf * 100).toFixed(0)}%`;
  return lab ? `${lab} ${pct}` : pct;
}

/** Short display name for compare overlay (basename, max length). */
function shortModelSpecForCanvas(spec) {
  if (spec == null || spec === '') return '';
  let s = String(spec);
  const i = s.lastIndexOf('/');
  if (i >= 0) s = s.slice(i + 1);
  const j = s.lastIndexOf('\\');
  if (j >= 0) s = s.slice(j + 1);
  return s.length > 26 ? s.slice(0, 23) + '…' : s;
}

function drawYoloTag(b, color) {
  const text = yoloLabelText(b);
  ctx2d.fillStyle = color;
  ctx2d.font = 'bold 11px monospace';
  let ty = b.y1 - 3;
  if (ty < 11) ty = Math.min(638, b.y2 + 11);
  ctx2d.fillText(text, b.x1 + 2, ty);
}

function drawOverlays(f) {
  const hasManual = getManualBboxes(f).some(m => manualBboxIsValid(m));
  // Dim factor: full opacity when no manual; ghosted when manual exists so boxes stay clickable
  const dim = hasManual ? 0.3 : 1.0;

  {
    for (const m of f.matches) {
      const gx = m.gps_px, gy = m.gps_py;

      // GPS projected point — yellow circle
      ctx2d.globalAlpha = dim;
      ctx2d.beginPath();
      ctx2d.arc(gx, gy, 6, 0, Math.PI * 2);
      ctx2d.strokeStyle = '#ffcc00';
      ctx2d.lineWidth = 2;
      ctx2d.stroke();
      ctx2d.beginPath();
      ctx2d.arc(gx, gy, 2, 0, Math.PI * 2);
      ctx2d.fillStyle = '#ffcc00';
      ctx2d.fill();

      if (m.yolo_bbox && !isIgnoredTrainingDet(m.yolo_bbox)) {
        const b = m.yolo_bbox;
        const isAuto = b.conf >= confThresh && m.dist_px <= distThresh;
        const color = isAuto ? '#4adf86' : '#ff9900';

        ctx2d.globalAlpha = dim;
        ctx2d.strokeStyle = color;
        ctx2d.lineWidth = 2;
        ctx2d.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);

        drawYoloTag(b, color);

        ctx2d.beginPath();
        ctx2d.moveTo(gx, gy);
        ctx2d.lineTo(b.cx, b.cy);
        ctx2d.strokeStyle = 'rgba(255,200,0,0.4)';
        ctx2d.lineWidth = 1;
        ctx2d.setLineDash([3, 3]);
        ctx2d.stroke();
        ctx2d.setLineDash([]);
      }
    }

    // Unmatched YOLO dets — dim blue (display floor; slider gates auto/review only)
    for (const det of f.all_yolo_dets || []) {
      if (isIgnoredTrainingDet(det)) continue;
      const matched = f.matches.some(
        m =>
          m.yolo_bbox === det ||
          (m.yolo_bbox && m.yolo_bbox.x1 === det.x1 && m.yolo_bbox.y1 === det.y1)
      );
      if (!matched && Number(det.conf) >= YOLO_DISPLAY_CONF_MIN) {
        ctx2d.globalAlpha = dim;
        ctx2d.strokeStyle = 'rgba(100,150,255,0.5)';
        ctx2d.lineWidth = 1;
        ctx2d.strokeRect(det.x1, det.y1, det.x2 - det.x1, det.y2 - det.y1);
        ctx2d.fillStyle = 'rgba(150,190,255,0.85)';
        ctx2d.font = '10px monospace';
        const t = yoloLabelText(det);
        let ty = det.y1 - 2;
        if (ty < 10) ty = Math.min(637, det.y2 + 10);
        ctx2d.fillText(t, det.x1 + 1, ty);
      }
    }

    // Predicted boxes (built by renderFrame, not here — avoid recomputing on every repaint)
    for (const pb of currentPredictedBoxes) {
      if (pb.uncertain) {
        // Recently skipped — very faint dotted box, click to adopt
        ctx2d.globalAlpha = dim * 0.35;
        ctx2d.strokeStyle = 'rgba(255,140,0,0.5)';
        ctx2d.lineWidth = 1;
        ctx2d.setLineDash([2, 6]);
        ctx2d.strokeRect(pb.x1, pb.y1, pb.w, pb.h);
        ctx2d.setLineDash([]);
        const tag = 'skip×' + pb.skipStreak + ' · click to use';
        ctx2d.fillStyle = 'rgba(255,140,0,0.55)';
        ctx2d.font = '9px monospace';
        let pty = pb.y1 - 3;
        if (pty < 11) pty = Math.min(638, pb.y2 + 11);
        ctx2d.fillText(tag, pb.x1 + 2, pty);
      } else {
        ctx2d.globalAlpha = dim;
        ctx2d.strokeStyle = 'rgba(255,180,0,0.7)';
        ctx2d.lineWidth = 2;
        ctx2d.setLineDash([4, 4]);
        ctx2d.strokeRect(pb.x1, pb.y1, pb.w, pb.h);
        ctx2d.setLineDash([]);
        const tag = 'pred · ' + (pb.label || '?') + ' ' + Math.round(pb.w) + '×' + Math.round(pb.h);
        ctx2d.fillStyle = 'rgba(255,180,0,0.85)';
        ctx2d.font = 'bold 10px monospace';
        let pty = pb.y1 - 3;
        if (pty < 11) pty = Math.min(638, pb.y2 + 11);
        ctx2d.fillText(tag, pb.x1 + 2, pty);
      }
    }

    // Better-candidate hints removed — autoReassignMatches applies them already.
    ctx2d.globalAlpha = 1.0;
  }

  for (const mb of getManualBboxes(f)) {
    if (!manualBboxIsValid(mb)) continue;
    const b = normalizeManualBbox(mb);
    ctx2d.strokeStyle = '#00e5ff';
    ctx2d.lineWidth = 2;
    ctx2d.setLineDash([5, 4]);
    ctx2d.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);
    ctx2d.setLineDash([]);
    drawYoloTag(b, '#00e5ff');
  }

  // User decision overlay
  const d = decisions[f.timestamp_ns];
  if (d === 'approved') {
    ctx2d.fillStyle = 'rgba(74,223,134,0.15)';
    ctx2d.fillRect(0, 0, 640, 640);
    ctx2d.fillStyle = '#4adf86';
    ctx2d.font = 'bold 28px monospace';
    ctx2d.fillText('✓ APPROVED', 200, 340);
  } else if (d === 'skipped') {
    ctx2d.fillStyle = 'rgba(255,96,96,0.15)';
    ctx2d.fillRect(0, 0, 640, 640);
    ctx2d.fillStyle = '#ff6060';
    ctx2d.font = 'bold 28px monospace';
    ctx2d.fillText('✗ SKIPPED', 210, 340);
  }
}

/** GPS + optional weed lines from analysis run; YOLO boxes from compare-model result(s). */
function drawCompareOverlays(f, overlay) {
  const hasManual = getManualBboxes(f).some(m => manualBboxIsValid(m));
  const COMPARE_PALETTE = [
    { stroke: 'rgba(224,64,251,0.95)', fill: '#e040fb' },
    { stroke: 'rgba(79,195,247,0.95)', fill: '#4fc3f7' },
    { stroke: 'rgba(255,183,77,0.95)', fill: '#ffb74d' },
    { stroke: 'rgba(129,199,132,0.95)', fill: '#81c784' },
    { stroke: 'rgba(239,83,80,0.95)', fill: '#ef5350' },
    { stroke: 'rgba(171,71,188,0.95)', fill: '#ab47bc' },
  ];

  function drawGpsAndWeedLines() {
    for (const m of f.matches) {
      const gx = m.gps_px, gy = m.gps_py;
      ctx2d.beginPath();
      ctx2d.arc(gx, gy, 6, 0, Math.PI * 2);
      ctx2d.strokeStyle = '#ffcc00';
      ctx2d.lineWidth = 2;
      ctx2d.stroke();
      ctx2d.beginPath();
      ctx2d.arc(gx, gy, 2, 0, Math.PI * 2);
      ctx2d.fillStyle = '#ffcc00';
      ctx2d.fill();

      if (m.yolo_bbox && !isIgnoredTrainingDet(m.yolo_bbox)) {
        const b = m.yolo_bbox;
        ctx2d.beginPath();
        ctx2d.moveTo(gx, gy);
        ctx2d.lineTo(b.cx, b.cy);
        ctx2d.strokeStyle = 'rgba(255,200,0,0.35)';
        ctx2d.lineWidth = 1;
        ctx2d.setLineDash([3, 3]);
        ctx2d.stroke();
        ctx2d.setLineDash([]);
      }
    }
  }

  function detPassesCompareVis(det) {
    if (isIgnoredTrainingDet(det)) return false;
    const c = Number(det.conf);
    return Number.isFinite(c) && c >= COMPARE_VIS_CONF_MIN;
  }

  if (!hasManual) {
    drawGpsAndWeedLines();

    if (overlay && overlay.mode === 'all' && Array.isArray(overlay.rows)) {
    let legendY = 14;
    for (let ri = 0; ri < overlay.rows.length; ri++) {
      const row = overlay.rows[ri];
      const pal = COMPARE_PALETTE[ri % COMPARE_PALETTE.length];
      const modelShort = shortModelSpecForCanvas(row.model_spec);
      ctx2d.fillStyle = pal.fill;
      ctx2d.font = 'bold 11px monospace';
      ctx2d.fillText(modelShort || row.model_spec, 6, legendY);
      legendY += 14;
      for (const det of row.dets || []) {
        if (!detPassesCompareVis(det)) continue;
        ctx2d.strokeStyle = pal.stroke;
        ctx2d.lineWidth = 2;
        ctx2d.strokeRect(det.x1, det.y1, det.x2 - det.x1, det.y2 - det.y1);
        ctx2d.fillStyle = pal.fill;
        ctx2d.font = 'bold 10px monospace';
        const clsPart = yoloLabelText(det);
        const t = modelShort ? modelShort + ' · ' + clsPart : clsPart;
        let ty = det.y1 - 3;
        if (ty < 11) ty = Math.min(638, det.y2 + 11);
        ctx2d.fillText(t, det.x1 + 2, ty);
      }
    }
    } else {
    const compareDets = overlay && overlay.dets ? overlay.dets : [];
    const modelSpec = overlay && overlay.modelSpec != null ? String(overlay.modelSpec) : '';
    const modelShort = shortModelSpecForCanvas(modelSpec);
    const pal = COMPARE_PALETTE[0];
    for (const det of compareDets) {
      if (!detPassesCompareVis(det)) continue;
      ctx2d.strokeStyle = pal.stroke;
      ctx2d.lineWidth = 2;
      ctx2d.strokeRect(det.x1, det.y1, det.x2 - det.x1, det.y2 - det.y1);
      ctx2d.fillStyle = pal.fill;
      ctx2d.font = 'bold 10px monospace';
      const clsPart = yoloLabelText(det);
      const t = modelShort ? modelShort + ' · ' + clsPart : clsPart;
      let ty = det.y1 - 3;
      if (ty < 11) ty = Math.min(638, det.y2 + 11);
      ctx2d.fillText(t, det.x1 + 2, ty);
    }
    if (modelShort) {
      ctx2d.fillStyle = 'rgba(224,64,251,0.92)';
      ctx2d.font = 'bold 11px monospace';
      ctx2d.fillText('Compare: ' + modelShort, 6, 14);
    }
  }
  }

  for (const mb of getManualBboxes(f)) {
    if (!manualBboxIsValid(mb)) continue;
    const b = normalizeManualBbox(mb);
    ctx2d.strokeStyle = '#00e5ff';
    ctx2d.lineWidth = 2;
    ctx2d.setLineDash([5, 4]);
    ctx2d.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);
    ctx2d.setLineDash([]);
    drawYoloTag(b, '#00e5ff');
  }

  const d = decisions[f.timestamp_ns];
  if (d === 'approved') {
    ctx2d.fillStyle = 'rgba(74,223,134,0.15)';
    ctx2d.fillRect(0, 0, 640, 640);
    ctx2d.fillStyle = '#4adf86';
    ctx2d.font = 'bold 28px monospace';
    ctx2d.fillText('✓ APPROVED', 200, 340);
  } else if (d === 'skipped') {
    ctx2d.fillStyle = 'rgba(255,96,96,0.15)';
    ctx2d.fillRect(0, 0, 640, 640);
    ctx2d.fillStyle = '#ff6060';
    ctx2d.font = 'bold 28px monospace';
    ctx2d.fillText('✗ SKIPPED', 210, 340);
  }
}

function paintCanvas(idx) {
  if (idx < 0 || idx >= frames.length || !canvasBaseImage) return;
  const f = frames[idx];
  ctx2d.clearRect(0, 0, 640, 640);
  ctx2d.drawImage(canvasBaseImage, 0, 0, 640, 640);
  const overlayPack = compareDetsForOverlay();
  if (overlayPack !== undefined) drawCompareOverlays(f, overlayPack);
  else drawOverlays(f);
  if (dragSelect !== null) {
    const x0 = Math.min(dragSelect.x0, dragSelect.x1);
    const y0 = Math.min(dragSelect.y0, dragSelect.y1);
    const x1 = Math.max(dragSelect.x0, dragSelect.x1);
    const y1 = Math.max(dragSelect.y0, dragSelect.y1);
    if (x1 - x0 >= 2 && y1 - y0 >= 2) {
      ctx2d.strokeStyle = 'rgba(0,229,255,0.92)';
      ctx2d.lineWidth = 2;
      ctx2d.setLineDash([6, 4]);
      ctx2d.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx2d.setLineDash([]);
    }
  }
}

function onCanvasDragMove(e) {
  if (!dragSelect) return;
  const [x, y] = canvasPointerCoords(e);
  dragSelect.x1 = x;
  dragSelect.y1 = y;
  if (currentIdx >= 0) paintCanvas(currentIdx);
}

function onCanvasDragUp(e) {
  document.removeEventListener('mousemove', onCanvasDragMove);
  document.removeEventListener('mouseup', onCanvasDragUp);
  if (!dragSelect || currentIdx < 0 || currentIdx >= frames.length) {
    dragSelect = null;
    if (currentIdx >= 0 && canvasBaseImage) paintCanvas(currentIdx);
    return;
  }
  const f = frames[currentIdx];
  const x0 = dragSelect.x0;
  const y0 = dragSelect.y0;
  const [x, y] = canvasPointerCoords(e);
  const dx = Math.abs(x - x0);
  const dy = Math.abs(y - y0);
  const moved = dx > 4 || dy > 4;
  dragSelect = null;
  if (!moved) {
    const det = findYoloDetAt(f, x0, y0);
    if (det) {
      addManualBboxFromUser(f, yoloDetToManualNorm(det), e.ctrlKey);
      syncManualBboxFormFromFrame();
    } else {
      const pb = findPredictedBoxAt(x0, y0);
      if (pb) {
        addManualBboxFromUser(f, normalizeManualBbox(pb), e.ctrlKey);
        syncManualBboxFormFromFrame();
      }
    }
  } else {
    const raw = rectFromDrag(x0, y0, x, y);
    if (manualBboxIsValid(raw)) {
      addManualBboxFromUser(f, normalizeManualBbox(raw), e.ctrlKey);
      syncManualBboxFormFromFrame();
    }
  }
  if (canvasBaseImage) paintCanvas(currentIdx);
}

function updateFrameInfo(f) {
  const ds = f.drone_state || {};
  const match = bestMatch(f);
  const parts = [];
  if (ds.altitude_rel_home != null) parts.push(`Alt: ${ds.altitude_rel_home.toFixed(1)}m`);
  if (ds.heading != null) parts.push(`Hdg: ${Math.round(ds.heading)}°`);
  if (ds.rangefinder_m != null) parts.push(`Rng: ${ds.rangefinder_m.toFixed(1)}m`);
  const mlist = getManualBboxes(f);
  if (mlist.length === 1 && manualBboxIsValid(mlist[0])) {
    const mb = normalizeManualBbox(mlist[0]);
    parts.push(`Manual box: ${escapeHtml(mb.label)} ${(mb.conf * 100).toFixed(0)}%`);
  } else if (mlist.length > 1) {
    parts.push(`Manual boxes: ${mlist.length}`);
  } else if (f._explicit_empty) {
    parts.push('Marked empty (D) — A approves no-object');
  }
  if (f._ai_predictions_removed) {
    parts.push('YOLO predictions cleared (Del)');
  }
  const hasManual = mlist.some(m => manualBboxIsValid(m));
  if (match) {
    parts.push(`GPS dist: ${match.dist_px.toFixed(0)}px`);
    if (!hasManual && match.yolo_bbox && isWeedProxyTrainingDet(match.yolo_bbox)) {
      const bb = match.yolo_bbox;
      if (bb.label) parts.push(`Class: ${escapeHtml(String(bb.label))}`);
      parts.push(`YOLO conf: ${(bb.conf * 100).toFixed(0)}%`);
    }
  }
  parts.push(`Weeds in FOV: ${f.matches.length}`);
  frameInfo.innerHTML = parts.map(p => `<span class="stat-pill">${p}</span>`).join('');
}

// ---------------------------------------------------------------------------
// Approve / Skip
// ---------------------------------------------------------------------------
function approve() {
  if (currentIdx < 0) return;
  const f = frames[currentIdx];
  migrateManualBboxesOnFrame(f);
  let manualList = getManualBboxes(f).filter(m => manualBboxIsValid(m));
  const yoloBb = manualList.length === 0 ? getYoloFallbackApproveBbox(f) : null;

  // No manual box and no YOLO match — adopt predicted boxes if available
  if (manualList.length === 0 && !yoloBb && currentPredictedBoxes.length > 0) {
    for (const pb of currentPredictedBoxes) {
      if (pb.uncertain) continue;
      addManualBboxFromUser(f, normalizeManualBbox(pb), true);
    }
    manualList = getManualBboxes(f).filter(m => manualBboxIsValid(m));
  }

  if (manualList.length === 0 && !yoloBb) {
    f._explicit_empty = true;
  }
  const affectedWeedIds = new Set((f.matches || []).map(m => m.weed_id));
  pushDecisionHistory(f.timestamp_ns);
  decisions[f.timestamp_ns] = 'approved';
  buildWeedDetectionIndex(affectedWeedIds);
  autoReassignMatches(affectedWeedIds);
  reEvaluateStatuses(affectedWeedIds);
  noteLabelerAction();
  renderFrame(currentIdx);
  refreshFilmstripThumbBadge(currentIdx);
  updateCounts();
  const next = nextFrameAfterDecision();
  if (next >= 0) jumpTo(next);
}

function skip() {
  if (currentIdx < 0) return;
  const f = frames[currentIdx];
  const affectedWeedIds = new Set((f.matches || []).map(m => m.weed_id));
  pushDecisionHistory(f.timestamp_ns);
  decisions[f.timestamp_ns] = 'skipped';
  buildWeedDetectionIndex(affectedWeedIds);
  autoReassignMatches(affectedWeedIds);
  reEvaluateStatuses(affectedWeedIds);
  noteLabelerAction();
  renderFrame(currentIdx);
  refreshFilmstripThumbBadge(currentIdx);
  updateCounts();
  const next = nextFrameAfterDecision();
  if (next >= 0) jumpTo(next);
}

/** Next frame still in the review queue (if any). */
function nextReviewIdx() {
  for (let i = currentIdx + 1; i < frames.length; i++) {
    const st = effectiveStatus(frames[i]);
    if (st === 'review') return i;
  }
  return -1;
}

/** Prefer next review frame; otherwise next index so A/S advances through the mission. */
function nextFrameAfterDecision() {
  const r = nextReviewIdx();
  if (r >= 0) return r;
  if (currentIdx + 1 < frames.length) return currentIdx + 1;
  return -1;
}

approveBtn.addEventListener('click', approve);
skipBtn.addEventListener('click', skip);
if (undoBtn) undoBtn.addEventListener('click', undoLastDecision);
prevBtn.addEventListener('click', () => jumpTo(currentIdx - 1));
nextBtn.addEventListener('click', () => jumpTo(currentIdx + 1));
if (nextReviewBtn) nextReviewBtn.addEventListener('click', () => {
  const r = nextReviewIdx();
  if (r >= 0) jumpTo(r);
});

function trainingKeydownFieldContext(e) {
  const t = e.target;
  if (!t || !t.tagName) return 'free';
  if (t.isContentEditable) return 'text';
  const tag = t.tagName.toUpperCase();
  if (tag === 'SELECT' || tag === 'TEXTAREA') return 'text';
  if (tag === 'INPUT') {
    const ty = (t.type || '').toLowerCase();
    if (ty === 'number') return 'number';
    return 'text';
  }
  return 'free';
}

document.addEventListener('keydown', e => {
  const ctx = trainingKeydownFieldContext(e);
  if (ctx === 'text') return;
  const k = e.key;
  if (ctx === 'number') {
    if (k !== 'd' && k !== 'D' && k !== 'f' && k !== 'F') return;
  }
  // Firefox "Search for text when you start typing" / Quick Find steals bare letters unless prevented.
  const mod = e.ctrlKey || e.metaKey || e.altKey;
  if (k === 'a' || k === 'A') {
    if (mod) return;
    e.preventDefault();
    approve();
  } else if (k === 's' || k === 'S') {
    if (mod) return;
    e.preventDefault();
    skip();
  } else if (k === 'd' || k === 'D') {
    if (mod) return;
    e.preventDefault();
    clearManualAllCurrentFrame();
  } else if (k === 'f' || k === 'F') {
    if (mod) return;
    e.preventDefault();
    undoLastDecision();
  } else if (k === 'ArrowLeft') {
    e.preventDefault();
    jumpTo(currentIdx - 1);
  } else if (k === 'ArrowRight') {
    e.preventDefault();
    jumpTo(currentIdx + 1);
  } else if (k === 'n' || k === 'N') {
    if (mod) return;
    e.preventDefault();
    const r = nextReviewIdx();
    if (r >= 0) jumpTo(r);
  } else if (k === 'Delete') {
    e.preventDefault();
    clearAiPredictionsOnCurrentFrame();
  }
});

// ---------------------------------------------------------------------------
// Counts
// ---------------------------------------------------------------------------
function updateCounts() {
  let auto = 0, manual = 0, review = 0, skip = 0, no_det = 0;
  for (const f of frames) {
    const st = effectiveStatus(f);
    if (st === 'approved') {
      // Determine if it was auto-approved or manually approved
      const liveStatus = f._status_live || f.status;
      if (liveStatus === 'auto') auto++;
      else manual++;
    } else if (st === 'skipped') skip++;
    else if (st === 'review') review++;
    else if (st === 'no_det' || st === 'no_weed') no_det++;
  }
  document.getElementById('cntAuto').textContent = auto;
  document.getElementById('cntManual').textContent = manual;
  document.getElementById('cntReview').textContent = review;
  document.getElementById('cntSkip').textContent = skip;
  document.getElementById('cntNoDet').textContent = no_det;
  refreshTrainingAnalytics();
}

// ---------------------------------------------------------------------------
// Save labels
// ---------------------------------------------------------------------------
saveBtn.addEventListener('click', async () => {
  const approved = [];
  const skipped = [];

  for (const f of frames) {
    const d = decisions[f.timestamp_ns];
    const liveStatus = f._status_live || f.status;

    if (d === 'skipped') {
      skipped.push(f.timestamp_ns);
      continue;
    }

    if (!(d === 'approved' || (liveStatus === 'auto' && d !== 'skipped'))) continue;

    migrateManualBboxesOnFrame(f);
    const mboxes = getManualBboxes(f).filter(m => manualBboxIsValid(m));
    if (d === 'approved' && mboxes.length > 0) {
      for (const b of mboxes) {
        approved.push({
          timestamp_ns: f.timestamp_ns,
          yolo_bbox: normalizeManualBbox(b),
        });
      }
      continue;
    }
    if (d === 'approved' && f._explicit_empty && mboxes.length === 0) {
      approved.push({
        timestamp_ns: f.timestamp_ns,
        yolo_bbox: null,
      });
      continue;
    }

    if (liveStatus === 'auto' && f.matches && f.matches.length) {
      for (const m of f.matches) {
        if (!m.yolo_bbox) continue;
        const ok = m.yolo_bbox.conf >= confThresh && m.dist_px <= distThresh;
        if (!ok) continue;
        approved.push({
          timestamp_ns: f.timestamp_ns,
          yolo_bbox: m.yolo_bbox,
        });
      }
    } else {
      const match = bestMatch(f);
      if (match && match.yolo_bbox) {
        approved.push({
          timestamp_ns: f.timestamp_ns,
          yolo_bbox: match.yolo_bbox,
        });
      }
    }
  }

  if (approved.length === 0) {
    showError('No approved labels to save — approve frames with YOLO, manual boxes, or D then A for empty.');
    return;
  }

  saveBtn.disabled = true;
  saveResult.textContent = 'Saving…';

  try {
    const resp = await fetch(
      `/missions/${MISSION_ID}/training/save_labels?src=${SRC}`,
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          approved,
          skipped,
          thresholds: {conf_thresh: confThresh, dist_thresh: distThresh},
        }),
      }
    );
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      showError(data.error || 'Save failed');
    } else {
      saveResult.textContent = `✓ Saved ${data.labels_written} label files to mission dir.`;
      errorBanner.style.display = 'none';
    }
  } catch(e) {
    showError(String(e));
  } finally {
    saveBtn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Assemble dataset (copy mission frames + labels into ai_train/real_data)
// ---------------------------------------------------------------------------
if (assembleBtn) {
  assembleBtn.addEventListener('click', async () => {
    assembleBtn.disabled = true;
    const prev = saveResult.textContent;
    saveResult.textContent = 'Assembling dataset…';
    try {
      const resp = await fetch('/training/assemble_real_dataset', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mission_ids: [MISSION_ID], src: SRC}),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        showError(data.error || 'Assemble failed');
        saveResult.textContent = prev;
      } else {
        saveResult.textContent = `Copied ${data.files_copied} image/label pairs to ${data.dest}`;
        errorBanner.style.display = 'none';
      }
    } catch (e) {
      showError(String(e));
      saveResult.textContent = prev;
    } finally {
      assembleBtn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function showError(msg) {
  const m = String(msg || 'Unknown error');
  errorBanner.textContent = m;
  // #errorBanner { display: none } in page CSS — must set inline display, not ''.
  errorBanner.style.display = 'block';
  if (frameInfo) {
    frameInfo.innerHTML =
      '<div class="alert alert-danger py-2 mb-0" role="alert">' + escapeHtml(m) + '</div>';
  }
}
