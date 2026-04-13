/* Camera geometry + detection label helpers — extracted from mission_training.js.
   Loaded before mission_training.js; exposes functions via globals (same names as before). */
'use strict';

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

function _toRad(x) {
  return Number(x) * Math.PI / 180;
}

/** Great-circle ground distance in meters. */
function groundDistanceMeters(lat1, lon1, lat2, lon2) {
  const a1 = _toRad(lat1 || 0);
  const b1 = _toRad(lon1 || 0);
  const a2 = _toRad(lat2 || 0);
  const b2 = _toRad(lon2 || 0);
  const dA = a2 - a1;
  const dB = b2 - b1;
  const s1 = Math.sin(dA / 2);
  const s2 = Math.sin(dB / 2);
  const h = s1 * s1 + Math.cos(a1) * Math.cos(a2) * s2 * s2;
  return 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(Math.max(0, h))));
}

function _yawWrapAbsDeg(degA, degB) {
  let d = Math.abs(Number(degA || 0) - Number(degB || 0)) % 360;
  if (d > 180) d = 360 - d;
  return d;
}

/** Motion delta summary used by strict propagation guardrails. */
function droneStateMotionDelta(dsA, dsB) {
  if (!dsA || !dsB) return null;
  const ground_m = groundDistanceMeters(dsA.latitude, dsA.longitude, dsB.latitude, dsB.longitude);
  const alt_m = Math.abs(Number(dsA.altitude_rel_home || 0) - Number(dsB.altitude_rel_home || 0));
  const ra = dsA.rotaion || {};
  const rb = dsB.rotaion || {};
  const dRoll = Math.abs(Number(ra.x || 0) - Number(rb.x || 0)) * 180 / Math.PI;
  const dPitch = Math.abs(Number(ra.y || 0) - Number(rb.y || 0)) * 180 / Math.PI;
  const dYaw = _yawWrapAbsDeg(Number(ra.z || 0) * 180 / Math.PI, Number(rb.z || 0) * 180 / Math.PI);
  const rot_deg = Math.sqrt(dRoll * dRoll + dPitch * dPitch + dYaw * dYaw);
  return { ground_m, alt_m, rot_deg, d_roll_deg: dRoll, d_pitch_deg: dPitch, d_yaw_deg: dYaw };
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

// ---------------------------------------------------------------------------
// Manual bbox helpers
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

const DEFAULT_MANUAL_LABEL = 'sports ball';
const DEFAULT_MANUAL_CONF = 0.99;

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
