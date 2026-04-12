/**
 * Shared mission setup param defaults (sv.json / real_missions shape).
 * Extracted from mission_weed_marking for ES-module reuse.
 */
export function defaultParams() {
  return {
    scan_height_m: 35,
    scan_speed_ms: 1.0,
    min_dist_from_waypoint_m: 1,
    min_weed_spacing_m: 2,
    min_num_det: 3,
    goto_alt_m: 10,
    max_homing_dist_m: 10,
    min_alt_m: 5,
    max_homing_alt_m: 15,
    min_spray_error_m: 2,
    sim_ai_enable_imperfections: false,
  };
}

export function mergeParams(p) {
  return { ...defaultParams(), ...(p && typeof p === "object" ? p : {}) };
}

export function normalizeLoadedPayload(raw) {
  const d = raw && typeof raw === "object" ? raw : {};
  return {
    field_center: d.field_center != null ? d.field_center : null,
    weed_locations: Array.isArray(d.weed_locations) ? d.weed_locations : [],
    scan_path: Array.isArray(d.scan_path) ? d.scan_path : [],
    params: mergeParams(d.params),
  };
}
