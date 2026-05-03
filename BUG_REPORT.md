# Bug Report — skydock2 + ai_skydock

Workspace: `/home/fred/skydock2` and sibling `/home/fred/ai_skydock`
Date: 2026-04-27

Fifteen issues, ordered by suggested fix sequence at the bottom.

---

## 1. `pull` doesn't reuse already-downloaded data in `skydock2/rpi_missions`

**Where**

- `ai_skydock/pull_frames_rpi.sh` (single mission)
- `ai_skydock/pull_all_flights.sh` (driver)
- `skydock2/pull_logs_rpi.sh` (older path; `tools/sync_rpi_logs.sh` is the newer hashed one)

**Symptom**

When you "pull" into `ai_skydock/flights/`, the script always rsyncs frames from
the Pi over SSH, even if you've already downloaded the same mission into
`skydock2/rpi_missions/<MISSION_ID>/frames/` (e.g. via `pull_logs_rpi.sh` or
`tools/sync_rpi_logs.sh`). On a slow Wi-Fi link this is many minutes of
redundant transfer.

**Root cause**

`pull_frames_rpi.sh` only sees one source of truth — the remote Pi:

```58:65:/home/fred/ai_skydock/pull_frames_rpi.sh
echo "==> Pulling raw frames ..."
rsync -avz --progress \
    --include="*.jpg" --include="*.jpeg" \
    --exclude="*" \
    "${RPI_USER}@${RPI_HOST}:${RPI_MISSION_DIR}/frames/" \
    "${LOCAL_DIR}/raw_frames/"
```

`pull_all_flights.sh` only checks `flight_meta.json` for "already pulled":

```39:42:/home/fred/ai_skydock/pull_all_flights.sh
ALREADY_PULLED=$(grep -r '"mission_id"' "${FLIGHTS_DIR}"/*/flight_meta.json 2>/dev/null \
    | sed 's/.*"mission_id": "\([^"]*\)".*/\1/' | sort | uniq || true)
```

It has no awareness of `~/skydock2/rpi_missions/`. Meanwhile
`skydock2/tools/sync_rpi_logs.sh` already has the right hash logic and even
writes a `manifest.txt` with `source_hash=` (lines 84-89, 162-164).

The "various cache files" you mentioned (e.g. `auto_labels/`, `meta/`, label
`.txt` files, post-pull derived artefacts) mean a naive whole-dir hash will
mismatch even when the source frames are identical — so the comparison must be
over the **frame set only**, not the whole mission dir.

**Fix**

In `pull_frames_rpi.sh`, before the SSH rsync, add a "local-first" path:

1. Resolve `LOCAL_CACHE="$HOME/skydock2/rpi_missions/$MISSION_ID"` (env override
   `SKYDOCK_RPI_MISSIONS_DIR`).
2. Compute remote frames hash on the Pi with the same Python snippet as
   `tools/sync_rpi_logs.sh` (`remote_hash_of_mission`), but scoped to
   `<mid>/frames/` only — sorted SHA-256 over `(rel_path, file_bytes)`.
3. Compute local hash the same way over `$LOCAL_CACHE/frames/`.
4. If local exists and hashes match → `cp -al` (hard-link) or
   `rsync -a --link-dest` from `$LOCAL_CACHE/frames/` into
   `$LOCAL_DIR/raw_frames/` (no SSH).
5. Else if local exists but hashes differ → log it, then choose:
   - if remote frame_count >= local frame_count → pull from Pi (Pi has fresher data).
   - if local has the extra files → log and still mirror Pi (Pi is canonical).
6. Else → fall back to existing SSH rsync.

Then update the local cache as well (push/copy back to
`skydock2/rpi_missions/...` so the next consumer can reuse it). Cache the
remote hash in `manifest.txt` next to the frames so future runs can skip even
the SSH hash call when nothing has changed.

In `pull_all_flights.sh`, extend `ALREADY_PULLED` to also union directories
from `$HOME/skydock2/rpi_missions/`:

```bash
LOCAL_CACHE_DIR="${SKYDOCK_RPI_MISSIONS_DIR:-$HOME/skydock2/rpi_missions}"
LOCAL_CACHE_IDS=$(ls -1 "$LOCAL_CACHE_DIR" 2>/dev/null | grep -E '^[0-9]+$' || true)
ALREADY_PULLED="$ALREADY_PULLED"$'\n'"$LOCAL_CACHE_IDS"
```

…but only treat it as "skip the SSH hash" — still verify hash before copying.
Reuse `tools/sync_rpi_logs.sh`'s `remote_hash_of_mission` helper (factor it
out into `tools/lib_rpi_hash.sh`) so all three scripts share one
implementation.

---

## 2. Training UI dies with `No label dirs in this flight. Run auto_label.py or add labels_truth/.`

**Where**

```114:117:/home/fred/ai_skydock/dashboard_pages/data.py
if not label_sets:
    st.warning(
        "No label dirs in this flight. Run auto_label.py or add labels_truth/.")
    return
```

The Streamlit "Convert flight → staging" tab early-returns because it scans
`flight_dir` for `labels_*` / `labels_truth` subdirs (lines 105-109) and finds
none. The user must manually `cd ai_skydock && python labeling/auto_label.py
--flight <FLIGHT>` from the terminal first.

**Root cause**

Two friction points:

1. **The dashboard tells you to run a CLI tool but won't run it for you**, even
   though `labeling/auto_label.py` is a regular Python script. Most users will
   not switch back to a terminal mid-flow.
2. The "Convert flight → staging" tab and the Train tab don't share state
   about which flights have labels yet, so a freshly-pulled flight always
   lands in this dead-end.

**Fix**

In `_convert_flight()` (`dashboard_pages/data.py`), replace the bare warning
with an inline action:

```python
if not label_sets:
    st.warning("No label dirs in this flight. Auto-label now using the ground model?")
    model_path = os.environ.get("SKYDOCK_YOLO_MODEL") or str(MODEL_REG / "ground_latest" / "best.pt")
    cols = st.columns([3, 1])
    cols[0].caption(f"Model: `{model_path}`")
    if cols[1].button("Run auto-label", type="primary", disabled=not Path(model_path).is_file()):
        with st.spinner(f"Auto-labelling {sel_name} ..."):
            res = subprocess.run(
                [sys.executable, "labeling/auto_label.py", "--flight", sel_name,
                 "--model", model_path],
                capture_output=True, text=True, cwd=str(REPO))
        st.code((res.stdout + res.stderr)[-3000:], language="text")
        if res.returncode == 0:
            st.success("Auto-label complete. Reload to see labels."); st.rerun()
        else:
            st.error("auto_label.py failed.")
    return
```

Also: when a flight has zero label dirs, `pull_frames_rpi.sh` should print a
clearer "Next" hint that points at `auto_label.py` with the resolved model
path, not just a fragmentary "set SKYDOCK_YOLO_MODEL".

---

## 3. Hailo compile of `yolov8l.onnx` fails with `The layer yolov8l/conv41 doesn't have one output layer`

**Where**

```101:116:/home/fred/ai_skydock/4_compile_inside_docker.py
nms_config = {
    "nms_scores_th": 0.3,
    "nms_iou_th": 0.45,
    "image_dims": [IMGSZ, IMGSZ],
    "max_proposals_per_class": 100,
    "classes": 1,
    "regression_length": 16,
    "background_removal": False,
    "background_removal_index": 0,
    "bbox_decoders": [
        {"name": f"{MODEL_NAME}/bbox_decoder41", "stride": 8,  "reg_layer": f"{MODEL_NAME}/conv41", "cls_layer": f"{MODEL_NAME}/conv42"},
        {"name": f"{MODEL_NAME}/bbox_decoder52", "stride": 16, "reg_layer": f"{MODEL_NAME}/conv52", "cls_layer": f"{MODEL_NAME}/conv53"},
        {"name": f"{MODEL_NAME}/bbox_decoder62", "stride": 32, "reg_layer": f"{MODEL_NAME}/conv62", "cls_layer": f"{MODEL_NAME}/conv63"},
    ]
}
```

**Root cause**

Those `convNN` names are **not from the ONNX**. They're names the Hailo parser
invents while flattening — sequential `convN` indices counted across the whole
network. They depend on the architecture:

- `yolov8s` has fewer backbone/neck conv layers, so the head's six `cv2/cv3`
  outputs land at `conv41/42/52/53/62/63` → compiles fine (you have a working
  `yolov8s.hef` in `shared_with_docker/`).
- `yolov8l` has a deeper neck, so those head layers land at different indices
  (probably `conv6X`/`7X`). What `conv41` actually points to in `yolov8l` is
  some intermediate branch in the C2f neck that fans out to multiple
  consumers — hence "doesn't have one output layer".

The log confirms only the **cls** layers (`conv42`, `conv53`, `conv63`) got
their activation swapped to Sigmoid before the failure; the parser then tried
to wire NMS reg→cls pairs and discovered `conv41` is structurally not a
pre-NMS regression head in `yolov8l`.

**Fix**

Stop hardcoding these. Build the bbox_decoder list from the actual parsed
graph. Three options, easiest first:

1. **Use Hailo's `hailomz` model zoo config** for `yolov8l` — it ships an
   alf/`alls` model script with the right per-arch indices for every variant.
   Replace the hand-rolled `nms_postprocess(...)` line with one of the zoo's
   pre-baked YAML model scripts.

2. **Discover the indices after parsing**. Right after
   `runner.translate_onnx_model(...)` returns, inspect `runner.get_hn_dict()`
   (or `runner._hn`) to find the six layers whose `original_names` match the
   six end nodes. Sort them by stride (input H/W ratio) and emit the
   `bbox_decoders` list:

   ```python
   end_to_role = {
       "/model.22/cv2.0/cv2.0.2/Conv": ("reg", 8),
       "/model.22/cv3.0/cv3.0.2/Conv": ("cls", 8),
       "/model.22/cv2.1/cv2.1.2/Conv": ("reg", 16),
       "/model.22/cv3.1/cv3.1.2/Conv": ("cls", 16),
       "/model.22/cv2.2/cv2.2.2/Conv": ("reg", 32),
       "/model.22/cv3.2/cv3.2.2/Conv": ("cls", 32),
   }
   hn = runner.get_hn_dict()
   by_stride: dict[int, dict[str, str]] = {}
   for layer_name, info in hn["layers"].items():
       for orig in info.get("original_names", []):
           if orig in end_to_role:
               role, stride = end_to_role[orig]
               by_stride.setdefault(stride, {})[role] = layer_name
   bbox_decoders = [
       {"name": f"{MODEL_NAME}/bbox_decoder_s{stride}", "stride": stride,
        "reg_layer": by_stride[stride]["reg"], "cls_layer": by_stride[stride]["cls"]}
       for stride in (8, 16, 32)
   ]
   ```

3. **Don't add NMS post-process at compile time** — parse without
   `nms_postprocess(...)` (the comment in `4_compile_inside_docker.py` already
   says "NMS is handled by `libhailo_yolov8_postprocess.so` on the Pi"). The
   pipeline on the Pi already runs CPU-side NMS, so for the heavier variants
   (`yolov8l/x`) drop the model-script line entirely and accept that NMS lives
   on the RPi. This is also the comment-block claim in the file header but
   the code below doesn't match it.

While you're in there, also fix the misleading
`WARNING: '...yolov8l.pt' not yolov8 — end node /model.22/Concat_3 may not match.`
in `3_compile_hailo8.sh`:

```36:41:/home/fred/ai_skydock/3_compile_hailo8.sh
case "$sel" in
  yolov8*|yolo8*) ;;
  *)
    echo "WARNING: '$sel' not yolov8 — end node /model.22/Concat_3 may not match." >&2
    ;;
esac
```

The basename of `/home/fred/ai_skydock/yolov8l.pt` matches `yolov8*` so this
should not have fired — it did because `$sel` is the **full path** not the
basename. Use `case "$(basename "$sel")"` instead. Cosmetic but the log line
will keep confusing future-you.

### 3.1 Follow-up failure after the first fix attempt

After patching the layer indices, the `yolov8l.pt` compile run fails again
in a *different* place — same disease, second symptom:

```
File ".../hailo_postprocess.py", line 375, in yolov8_decoding_call
    decoded_bboxes = tf.expand_dims(decoded_bboxes, axis=2)
ValueError: Tried to convert 'input' to a tensor and failed.
            Error: None values not supported.

Arguments received by HailoPostprocess.call():
  • inputs=['tf.Tensor(shape=(1, 160, 160, 64), dtype=float32)',
            'tf.Tensor(shape=(1, 160, 160, 80), dtype=float32)',
            'tf.Tensor(shape=(1, 80,  80,  64), dtype=float32)',
            'tf.Tensor(shape=(1, 80,  80,  80), dtype=float32)',
            'tf.Tensor(shape=(1, 40,  40,  64), dtype=float32)',
            'tf.Tensor(shape=(1, 40,  40,  80), dtype=float32)']
```

Two things are wrong about those input shapes — both confirm the NMS
config and the actual model graph are out of sync:

1. **Feature map sizes are off-by-one stride.** YOLOv8 at `imgsz=640`
   produces P3/P4/P5 at strides 8/16/32, i.e. 80×80, 40×40, 20×20. The
   tensors Hailo is feeding into NMS are 160/80/40 — strides 4/8/16. So
   the patch picked end nodes one stage *too early* in the C2f neck;
   `bbox_decoder` is wired to intermediate features, not to
   `model.22/cv2.{0,1,2}.2/Conv`. Hailo then tries to broadcast against
   the wrong anchor grid and `decoded_bboxes` ends up `None` — that's the
   `None values not supported` death.

2. **Class count mismatch.** Cls heads have **80 channels** (full COCO),
   but `nms_config["classes"] = 1` (line 162). The NMS layer was
   configured for a Ball-only fine-tune, but `yolov8l.pt` is the stock
   80-class hub weight. Even with the right layer names, these two
   numbers must match: pass the user's checkpoint through a 1-class
   fine-tune *or* set `classes` from the actual cls-head channel count.

**Tightened fix**

The fix from option 2 above needs three more guards. Replace the patch
with this slightly-bigger version:

```python
# After runner.translate_onnx_model(...)
hn = runner.get_hn_dict()

end_to_role = {
    "/model.22/cv2.0/cv2.0.2/Conv": ("reg", 8),
    "/model.22/cv3.0/cv3.0.2/Conv": ("cls", 8),
    "/model.22/cv2.1/cv2.1.2/Conv": ("reg", 16),
    "/model.22/cv3.1/cv3.1.2/Conv": ("cls", 16),
    "/model.22/cv2.2/cv2.2.2/Conv": ("reg", 32),
    "/model.22/cv3.2/cv3.2.2/Conv": ("cls", 32),
}

by_stride: dict[int, dict[str, tuple[str, int]]] = {}  # stride -> role -> (hailo_name, channels)
for layer_name, info in hn["layers"].items():
    for orig in info.get("original_names", []):
        if orig in end_to_role:
            role, stride = end_to_role[orig]
            ch = info.get("output_shapes", [[None]*4])[0][-1]
            by_stride.setdefault(stride, {})[role] = (layer_name, ch)

# 1. Sanity: every stride/role must be filled
for stride in (8, 16, 32):
    for role in ("reg", "cls"):
        if role not in by_stride.get(stride, {}):
            raise RuntimeError(
                f"Could not resolve {role} head at stride {stride} — "
                f"end_node mapping is wrong for this model."
            )

# 2. Sanity: cls channel count must agree across strides
cls_channels = {by_stride[s]["cls"][1] for s in (8, 16, 32)}
if len(cls_channels) != 1:
    raise RuntimeError(f"Cls heads disagree on class count: {cls_channels}")
n_classes = cls_channels.pop()

# 3. Sanity: reg channel count must be 4 × regression_length
reg_channels = {by_stride[s]["reg"][1] for s in (8, 16, 32)}
if reg_channels != {4 * REGRESSION_LENGTH}:
    raise RuntimeError(
        f"Reg heads have {reg_channels} channels, expected "
        f"{4 * REGRESSION_LENGTH} for regression_length={REGRESSION_LENGTH}"
    )

bbox_decoders = [
    {"name":      f"{MODEL_NAME}/bbox_decoder_s{stride}",
     "stride":    stride,
     "reg_layer": by_stride[stride]["reg"][0],
     "cls_layer": by_stride[stride]["cls"][0]}
    for stride in (8, 16, 32)
]

nms_config = {
    "nms_scores_th": 0.3,
    "nms_iou_th": 0.45,
    "image_dims": [IMGSZ, IMGSZ],
    "max_proposals_per_class": 100,
    "classes": n_classes,                # <-- was hardcoded 1
    "regression_length": REGRESSION_LENGTH,
    "background_removal": False,
    "background_removal_index": 0,
    "bbox_decoders": bbox_decoders,
}
```

Three explicit `RuntimeError`s above turn silent "None values not
supported" deaths into legible "the cls heads disagree on class count"
errors, which is exactly what was needed when the same compile script
was reused on a 1-class fine-tune *and* on a stock 80-class hub model.

The 160×160 feature maps are also a useful test signal: if you ever see
those shapes in `HailoPostprocess.call()` again, the end_node resolver
just walked into the C2f neck — re-check what the parser actually mapped
your end nodes to with `runner.get_end_nodes()` before optimization.

**Workaround until the fix lands.** Skip Hailo NMS for now — drop the
`nms_postprocess(...)` line from the model script entirely (option 3
above) and let the RPi do CPU NMS via `libhailo_yolov8_postprocess.so`.
That gets `yolov8l.hef` produced in ~10 minutes; you can revisit the
bake-in-NMS path once the resolver above is in place.

---

## 4. Train UI doesn't let you pick which dataset(s) to train on (white hat → ball false positives)

**Where**

- `ai_skydock/2_train.py` — only takes a single `--data` flag, defaults to
  `merged_dataset/data.yaml`.
- `ai_skydock/dashboard_pages/train.py` — has no controls for arch / data /
  epochs / fine-tune. Just a static `st.code(...)` snippet.
- `ai_skydock/datasets/` already has versioned datasets (`v1`, `v2`, `v3`)
  that the UI ignores.

```202:225:/home/fred/ai_skydock/2_train.py
parser.add_argument("--data",           default="merged_dataset/data.yaml")
parser.add_argument("--model",          default="yolov8n.pt", ...)
parser.add_argument("--epochs",         type=int, default=100)
parser.add_argument("--batch",          type=int, default=None)
parser.add_argument("--imgsz",          type=int, default=1280, ...)
```

**Symptom you're hitting**

You flew at a new site where spectators wore white caps. The current ball
detector treats them as balls because:

- The training set is `merged_dataset/`, sourced from `1_download_datasets.py` —
  Roboflow ball sets only. Zero negative samples of "white round things that
  are not balls" (caps, helmets, paper plates, golf balls in lawn).
- Without a UI, you can't easily mix in COCO `person`/`hat` images as
  negatives or add a new in-field flight as a hard-negative split, so every
  training run rebuilds the same overfit ball-only world.

**Fix — UI**

In `dashboard_pages/train.py`, add a "Train new model" form:

```python
data_yamls = sorted(p for p in (REPO / "datasets").glob("*/data.yaml")) \
           + [REPO / "merged_dataset" / "data.yaml"]
with st.form("train_form"):
    arch = st.selectbox("Arch", ["yolov8n", "yolov8s", "yolov8m", "yolov8l", "yolov8x"])
    data_choices = st.multiselect(
        "Datasets to train on (combined at YAML level)",
        [str(p.relative_to(REPO)) for p in data_yamls],
        default=[str((REPO / "merged_dataset" / "data.yaml").relative_to(REPO))],
    )
    epochs = st.number_input("Epochs", 10, 500, 100)
    imgsz  = st.selectbox("imgsz", [640, 960, 1280], index=2)
    finetune = st.selectbox("Finetune from", ["(none)"] + [m["version"] for m in db_models()])
    extra_neg = st.text_input("Extra negative-sample dir (no labels = pure neg)", value="")
    submit = st.form_submit_button("Queue training", type="primary")
if submit:
    write_train_queue_entry(...)
```

When more than one dataset is selected, write a synthetic
`data_combined.yaml` that lists every chosen `train:` and `val:` dir as a
YOLO multi-source data config (Ultralytics supports lists), or symlink-merge
them under `datasets/combined_<hash>/`.

**Fix — model**

The deeper cause is class-imbalance, not UI. Mitigations to also wire in:

1. **Add a hard-negatives split.** Drop the white-hat flight (or a small COCO
   people subset) into a `train/images_neg/` folder with empty `*.txt`
   labels. YOLO treats label-less frames as pure negatives. The "Convert
   flight → staging" tab in `data.py` already has an "include as negatives"
   option (line ~134-135) — surface this as the default for hat-confusion
   flights.
2. **Multi-class instead of single-class.** Currently `data.yaml` has
   `nc: 1, names: ['Ball']`. Re-train as
   `nc: 2, names: ['Ball','HardNeg']` (or use COCO classes). The model learns
   to actively classify the confuser instead of just "is it round and bright"
   → hat detections will go to class 1 and you can drop them at inference.
3. **Lower confidence ceiling at the FSM layer.** In the meantime in
   `homing.py` / wherever you accept detections for spraying, raise the conf
   threshold for ball-class only from `0.3` to `~0.6` until the new model is
   trained — kicks the can but stops the white-hat false-spray today.
4. **Augmentation realism.** `2_train.py` currently uses heavy mosaic +
   erasing. Mosaic on a ball-only dataset can create chimera images that
   "teach" the model that any 4 round bright pixels = ball. Drop `mosaic`
   from `1.0` → `0.3` for the next finetune.

---

## 4b. The Train tab has no way to actually start a training run

**Where**

```16:21:/home/fred/ai_skydock/dashboard_pages/train.py
def render() -> None:
    st.header("Train")
    tabs = st.tabs(["Runs", "Queue", "Compile worker"])
    with tabs[0]: _runs()
    with tabs[1]: _queue()
    with tabs[2]: _compile_worker()
```

```47:54:/home/fred/ai_skydock/dashboard_pages/train.py
def _queue() -> None:
    qfile = REPO / "train_queue.json"
    if not qfile.exists():
        st.info("No train_queue.json. Use train_queue.py to add jobs."); return
    try:
        st.json(json.loads(qfile.read_text()))
    except Exception as e:
        st.error(f"Could not parse train_queue.json: {e}")
```

**Symptom**

Open the dashboard → Train tab → you see:

- **Runs** — read-only table of past registry rows.
- **Queue** — `st.json(...)` dump of `train_queue.json`. No add. No edit. No
  remove. No "run now".
- **Compile worker** — only handles compile after a run finishes; doesn't
  start training.

To actually train you have to leave the dashboard, hand-edit
`train_queue.json` in a real editor, then in a terminal run
`python train_queue.py`. The "Quick start" snippet in `_runs()` is just
static text in `st.code(...)` — it doesn't execute.

Even the misleading hint `"Use train_queue.py to add jobs."` is wrong —
`train_queue.py` does not add jobs to the queue. It is the **runner** that
consumes the queue. There is no `add` command anywhere in the file (only
`--queue`, `--dry-run`).

**Root cause**

`_queue()` was scaffolded as a viewer ("Step 1 stub" per the module
docstring) and Step 2 never landed:

```1:5:/home/fred/ai_skydock/dashboard_pages/train.py
"""Train stage — queue + runs + compile worker status.

Step 1 stub: surfaces train_queue.json and lists registry runs. Compile worker
status comes in Step 2 (auto-compile worker).
"""
```

Compile worker shipped, queue editor + launcher didn't.

**Fix**

Replace `_queue()` with an editor + launcher, and add a `_train_now()` form
for ad-hoc one-off runs (this is the "dataset picker" UI from issue #4, but
folded into a runnable form). Concretely:

```python
def _train_now() -> None:
    st.subheader("Train now (one-off)")
    data_yamls = sorted(str(p.relative_to(REPO))
                        for p in REPO.glob("datasets/*/data.yaml"))
    merged = REPO / "merged_dataset" / "data.yaml"
    if merged.is_file():
        data_yamls.append(str(merged.relative_to(REPO)))

    with st.form("train_now"):
        model    = st.selectbox("Model",
            ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt"])
        data     = st.selectbox("Dataset", data_yamls,
            index=max(0, data_yamls.index(str(merged.relative_to(REPO)))
                            if str(merged.relative_to(REPO)) in data_yamls else 0))
        epochs   = st.number_input("Epochs", 10, 500, 100)
        imgsz    = st.selectbox("imgsz", [640, 960, 1280], index=2)
        patience = st.number_input("Patience", 5, 100, 30)
        finetune = st.selectbox("Finetune from",
            ["(none)"] + [m["version"] for m in db_models()])
        background = st.checkbox("Run in background (nohup)", value=True)
        go = st.form_submit_button("Start training", type="primary")

    if not go:
        return
    args = [sys.executable, "-u", "2_train.py",
            "--model", model, "--data", data,
            "--epochs", str(epochs), "--imgsz", str(imgsz),
            "--patience", str(patience)]
    if finetune != "(none)":
        args += ["--finetune-from", finetune]

    log_path = REPO / "logs" / f"train_{datetime.now():%Y%m%d_%H%M%S}.log"
    log_path.parent.mkdir(exist_ok=True)
    if background:
        with open(log_path, "wb") as lf:
            subprocess.Popen(args, cwd=str(REPO), stdout=lf, stderr=subprocess.STDOUT,
                             start_new_session=True)
        st.success(f"Started in background → tail `{log_path}`")
    else:
        with st.spinner(f"Training {model} on {data} ..."):
            res = subprocess.run(args, cwd=str(REPO),
                                 capture_output=True, text=True)
        st.code((res.stdout + res.stderr)[-4000:], language="text")
        if res.returncode == 0: st.success("Training complete.")
        else: st.error(f"Training failed (exit {res.returncode}).")


def _queue() -> None:
    qfile = REPO / "train_queue.json"
    jobs = json.loads(qfile.read_text()) if qfile.exists() else []

    st.subheader("Queued jobs")
    if not jobs:
        st.info("Queue is empty.")
    else:
        for i, job in enumerate(jobs):
            cols = st.columns([5, 1])
            cols[0].write(f"**{i+1}.** `{job.get('model','yolov8n.pt')}` "
                          f"epochs={job.get('epochs',100)} "
                          f"data=`{job.get('data','merged_dataset/data.yaml')}`")
            if cols[1].button("Remove", key=f"rmq_{i}"):
                jobs.pop(i)
                qfile.write_text(json.dumps(jobs, indent=2))
                st.rerun()

    st.subheader("Add to queue")
    with st.form("queue_add"):
        model  = st.text_input("Model", "yolov8s.pt")
        data   = st.text_input("Data yaml", "merged_dataset/data.yaml")
        epochs = st.number_input("Epochs", 10, 500, 100)
        imgsz  = st.selectbox("imgsz", [640, 960, 1280], index=2)
        if st.form_submit_button("Append"):
            jobs.append({"model": model, "data": data,
                         "epochs": int(epochs), "imgsz": int(imgsz),
                         "split_val": 0.2, "patience": 30})
            qfile.write_text(json.dumps(jobs, indent=2))
            st.rerun()

    st.subheader("Run queue")
    lock = REPO / ".train_queue.lock"
    if lock.exists():
        st.warning(f"🔒 Queue runner already active (pid {lock.read_text().strip()})")
    elif jobs and st.button("Run queue (background)", type="primary"):
        log_path = REPO / "logs" / f"train_queue_{datetime.now():%Y%m%d_%H%M%S}.log"
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "wb") as lf:
            p = subprocess.Popen(
                [sys.executable, "-u", "train_queue.py"],
                cwd=str(REPO), stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True)
        lock.write_text(str(p.pid))
        st.success(f"Started queue runner pid {p.pid} → `{log_path}`")
        st.rerun()
```

And add the new sub-tab in `render()`:

```python
tabs = st.tabs(["Train now", "Queue", "Runs", "Compile worker"])
with tabs[0]: _train_now()
with tabs[1]: _queue()
with tabs[2]: _runs()
with tabs[3]: _compile_worker()
```

Other cleanups while in there:

- `train_queue.py` should drop / write the `.train_queue.lock` file itself
  (`atexit`-style) so the UI's "is the runner still up?" check is reliable
  across restarts.
- `train_queue.py --add '{"model":"yolov8s.pt",...}'` would let the
  dashboard's add-job path use the same code path as CLI, instead of two
  places editing the JSON.
- Update the docstring + the false hint in `_queue()`
  (`"Use train_queue.py to add jobs."`) to reflect reality once these land.

This slots in just before issue #4's "dataset picker" — fix the launch button
first (so you have *any* way to start a run from the UI), then richen the
form with multi-dataset / negatives selection.

---

## 5. "FPS (Hailo-8)" displayed in the dashboard is wrong / unreliable

**Where**

- `ai_skydock/dashboard_lib.py` lines 123-138 — `parse_fps_from_text()`
- `ai_skydock/dashboard_pages/evaluate.py` lines 340-403 — `_run_remote_video_benchmark()`
- `ai_skydock/init_registry.py` line 48 — `models.fps_rpi_hailo8 REAL` column
- `ai_skydock/5_deploy_to_rpi.sh` — does NOT benchmark after deploy

**Symptom**

The "FPS (Hailo-8)" / "FPS (RPi Hailo-8)" metric you see in:

- `evaluate.py:111-112` (history cards)
- `evaluate.py:151` (picker tab)
- `evaluate.py:191,194` (compare table)
- `deploy.py:59` (deploy header)
- `evaluate.py:289-297` (Accuracy vs FPS scatter)

…is read straight from `models.fps_rpi_hailo8` in `registry.db`. That column
gets populated by **one** code path: the manual "Run Video Stream Benchmark
over SSH" button. Until you click it, the column is `NULL` (display: "—").
After you click it, the value sticks forever — there's no re-validation when
you redeploy a different HEF or change the Pi pipeline.

Three concrete things that make the value wrong even after you click:

1. **`parse_fps_from_text()` returns the first match**, not the inference FPS.

   ```123:138:/home/fred/ai_skydock/dashboard_lib.py
   def parse_fps_from_text(text: str) -> float | None:
       if not text:
           return None
       patterns = [
           r"([0-9]+(?:\.[0-9]+)?)\s*(?:FPS|fps)",
           r"(?:FPS|fps)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
           r"throughput\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
       ]
       for pat in patterns:
           m = re.search(pat, text)
           if m:
               try:
                   return float(m.group(1))
               except ValueError:
                   return None
       return None
   ```

   GStreamer logs from the `hailo-rpi5-examples/basic_pipelines/detection.py`
   pipeline emit several FPS-like lines: source/camera FPS, sink/display FPS,
   queue FPS, and an inference FPS. `re.search` returns the first regex hit
   anywhere in the buffer, which on this pipeline is usually the **source
   FPS** (camera or video file rate, e.g. `30`), not the Hailo inference
   rate. Whatever number lands first wins. If the input video is 30 FPS,
   you'll always store ~30 regardless of what the chip actually does.

2. **The wall-clock fallback overcounts overhead.**

   ```393:398:/home/fred/ai_skydock/dashboard_pages/evaluate.py
   fps = parse_fps_from_text(out_text)
   frame_count = parse_max_frame_count(out_text)
   if fps is None and frame_count > 0:
       fps = frame_count / elapsed
   if fps is None or fps <= 0:
       st.error("Could not derive FPS from benchmark output."); return
   ```

   `elapsed` is wall time from `subprocess.run(SSH + [remote_cmd])`. That
   includes: SSH connect, `bash -lc 'source setup_env.sh'`, GStreamer
   pipeline build, Hailo device open, model load, first-frame warmup, and
   pipeline teardown. For a short benchmark (a few seconds of video), warmup
   dominates and the reported FPS is much lower than steady-state. For a
   long video it's closer to truth, but still not the chip's throughput —
   it's mostly the input file's rate.

3. **No ground-truth tool is used.** Hailo ships `hailortcli benchmark <hef>`
   and `hailortcli run <hef>` exactly for this. They report:

   ```
   Network: yolov8s
       Frames per second: 235.41
       FPS (HW only): 312.18
       Latency (avg, hw_only): 3.20 ms
   ```

   The dashboard never calls them. It runs the full GStreamer detection
   pipeline, which is bottlenecked by source video rate, NMS post-process on
   CPU, and DRM display — none of which are "Hailo-8 FPS" in any useful
   sense.

4. **There's no benchmark-on-deploy.** `5_deploy_to_rpi.sh` copies the HEF,
   restarts the service, marks the model deployed — but never runs
   `hailortcli benchmark`, so `fps_rpi_hailo8` stays whatever it was (or
   stays NULL).

**Fix**

Two parts: (a) change what we measure and how, (b) trigger it automatically.

### a) Measure with `hailortcli`, not by parsing GStreamer logs

Add a helper in `dashboard_lib.py`:

```python
def parse_hailortcli_fps(text: str) -> dict[str, float]:
    """Returns {"streaming": x, "hw_only": y} from `hailortcli benchmark` output.
    Falls back to {} if the well-known headings are absent."""
    out: dict[str, float] = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*Frames per second\s*:\s*([0-9.]+)", line)
        if m: out["streaming"] = float(m.group(1)); continue
        m = re.match(r"\s*FPS \(HW only\)\s*:\s*([0-9.]+)", line)
        if m: out["hw_only"] = float(m.group(1)); continue
        m = re.match(r"\s*FPS \(streaming\)\s*:\s*([0-9.]+)", line)
        if m: out["streaming"] = float(m.group(1)); continue
    return out
```

Replace `_run_remote_video_benchmark` with a `hailortcli`-first path:

```python
def _run_remote_hailo_benchmark(
    bench_version, bench_host, bench_user,
    duration_s: int = 15, batch_size: int = 8,
):
    bench_hef = MODEL_REG / bench_version / "best.hef"
    if not bench_hef.exists():
        st.error(f"Missing HEF: {bench_hef}"); return

    target = f"{bench_user}@{bench_host}"
    SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", target]
    SCP = ["scp", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no"]

    remote_hef = f"/home/{bench_user}/ai_benchmarking_over_ssh/{bench_version}.hef"
    subprocess.run(SSH + [f"mkdir -p $(dirname {remote_hef})"], check=True)
    subprocess.run(SCP + [str(bench_hef), f"{target}:{remote_hef}"], check=True)

    cmd = (f"hailortcli benchmark --time-to-run {duration_s} "
           f"--batch-size {batch_size} {shlex.quote(remote_hef)}")
    res = subprocess.run(SSH + [cmd], capture_output=True, text=True,
                         timeout=duration_s + 60)
    out = (res.stdout or "") + "\n" + (res.stderr or "")
    st.code(out[-6000:], language="text")

    fps_map = parse_hailortcli_fps(out)
    fps = fps_map.get("streaming") or fps_map.get("hw_only")
    if fps is None or fps <= 0:
        st.error("hailortcli did not report FPS — see output above."); return

    conn = get_conn()
    conn.execute(
        "UPDATE models SET fps_rpi_hailo8=?, fps_hw_only=?, fps_measured_at=?, "
        "fps_measured_host=? WHERE version=?",
        (fps_map.get("streaming"), fps_map.get("hw_only"),
         datetime.utcnow().isoformat() + "Z", bench_host, bench_version),
    )
    conn.commit(); conn.close()
    st.success(f"{bench_version}: streaming={fps_map.get('streaming')} "
               f"hw_only={fps_map.get('hw_only')} (saved)")
```

This needs three new columns:

```sql
ALTER TABLE models ADD COLUMN fps_hw_only REAL;
ALTER TABLE models ADD COLUMN fps_measured_at TEXT;
ALTER TABLE models ADD COLUMN fps_measured_host TEXT;
```

Update `init_registry.py` and `migrations.py` to add them. The two flavours
matter:

- `fps_hw_only` — pure Hailo throughput; what to optimise the compile for.
  Stable across runs.
- `fps_rpi_hailo8` — streaming (HW + DMA + RPi CPU/PCIe overhead); what the
  FSM actually sees. This is the one that should drive `MIN_HOMING_DIST`
  etc.

Display both in the metric cards (e.g.
`FPS Hailo (HW): 312 / Stream: 235 @ rpi.local 2026-04-27`). Grey out as
"stale" if `fps_measured_at` is older than the current `best.hef` mtime.

### b) Auto-run after compile and after deploy

In `5_deploy_to_rpi.sh`, after the deploy succeeds, run the benchmark:

```bash
echo "==> Benchmarking ${VERSION} on Hailo-8 ..."
ssh "${RPI_USER}@${RPI_HOST}" \
    "hailortcli benchmark --time-to-run 15 --batch-size 8 ${RPI_DEST}/models/ball_detection.hef" \
    | tee /tmp/${VERSION}_bench.log

# parse + write fps_* into registry.db (same Python heredoc as deploy block)
```

In the dashboard, fire it from `compile_worker.py` or a "Compile + benchmark"
combo button so a freshly compiled HEF gets a real number before it ever
shows in the table.

Belt-and-braces: have the compare/scatter charts in `evaluate.py` filter out
rows where `fps_measured_at IS NULL OR fps_measured_at < hef_mtime`. Today
they show stale numbers as if they were current.

### c) Fix the parser even if you keep the streaming benchmark

If you still want to keep the GStreamer-pipeline benchmark as a secondary
"real-world" measure, narrow the regex to lines the Hailo example explicitly
emits (e.g. `Pipeline output FPS:` or the line with `inference_pipeline`),
and reject any number that's within 10% of the input video's nominal FPS
(it's almost certainly source rate, not inference rate). Better: read
frame-count / wall-time **only** for the steady-state region (drop first 2
seconds for warmup).

---

## 6. Evaluate tab shows raw metric names with no explanation of what they mean

**Where**

- `ai_skydock/dashboard_pages/evaluate.py:87-119` — history cards (mAP50,
  mAP50-95, Precision, Recall, FPS).
- `ai_skydock/dashboard_pages/evaluate.py:147-156` — Picker tab metric row.
- `ai_skydock/dashboard_pages/evaluate.py:184-205` — Compare tab.
- `ai_skydock/dashboard_pages/deploy.py:49-62` — Selected Model Metrics row.

**Symptom**

A model card on the Evaluate tab currently looks like this for an
un-evaluated model:

```
v018  yolov8s · 1280px · deployed: —
mAP50      —
mAP50-95   —
Precision  —
Recall     —
FPS (Hailo-8)  —
Trained on: — / —   ·  2026-04-14
```

If you don't already know the field, there's no way to learn what these mean
without leaving the tool. There is no tooltip, no expander, no link, and the
"Trained on: — / —" field is so terse it reads as broken (it's actually
`<dataset_version> / <dataset_source>` with both nulls). The Compare tab
makes it worse: it labels the row literally `mAP50` and shows the delta in
raw units, so a `Δ +0.012` is meaningless to a non-ML reader.

**Root cause**

The cards are hand-rolled HTML in `_history()` (`evaluate.py:87-120`) — no
`help=` parameter, no `st.tooltip`, no glossary. The `_picker()` and
`_benchmarks()` views use `st.metric(...)` which **does** support a `help`
kwarg, but it's never set:

```147:151:/home/fred/ai_skydock/dashboard_pages/evaluate.py
c1, c2, c3, c4 = st.columns(4)
c1.metric("Version", sel)
c2.metric("Architecture", m.get("model_arch") or "—")
c3.metric("mAP50", fmt_metric(m.get("mAP50")))
c4.metric("FPS (Hailo-8)", fmt_metric(m.get("fps_rpi_hailo8"), 1))
```

Compare is the same — bare row labels, no help, no units:

```186:195:/home/fred/ai_skydock/dashboard_pages/evaluate.py
comp_data = {
    "Metric": ["mAP50", "mAP50_95", "Precision", "Recall", "FPS (RPi)"],
    v_a: [m_a.get("mAP50"), m_a.get("mAP50_95"),
          m_a.get("precision_val"), m_a.get("recall_val"),
          m_a.get("fps_rpi_hailo8")],
    ...
}
```

The "Trained on: — / —" line in the card mixes two nullable fields with no
fallback text, so an empty registry row renders as visual noise instead of
"unknown dataset":

```114:118:/home/fred/ai_skydock/dashboard_pages/evaluate.py
<div style="margin-top:8px;color:#aaa;font-size:0.78em">
  Trained on: <span style="color:#ddd">{ds_str}</span>
  &nbsp;·&nbsp; {(m.get('train_date','') or '')[:10] or '—'}
</div>
```

with `ds_str` built earlier as `f"{ds_ver} / {ds_src}"` even when both are
nulls.

**Fix**

Centralise the glossary in `dashboard_lib.py` so every page (Evaluate,
Deploy, Compare) renders the same explanations:

```python
METRIC_HELP: dict[str, str] = {
    "mAP50": (
        "Mean Average Precision at IoU≥0.5. 1.0 = perfect, 0 = useless. "
        "Computed on the validation split: how often the model both "
        "(a) draws a box that overlaps a ground-truth box by ≥50% AND "
        "(b) labels it correctly. Standard YOLO benchmark number."
    ),
    "mAP50-95": (
        "mAP averaged over IoU thresholds 0.50, 0.55, … 0.95. Stricter than "
        "mAP50 — penalises sloppy box edges. Always ≤ mAP50. Better proxy "
        "for tight-localisation quality (e.g. spraying close to the weed)."
    ),
    "Precision": (
        "Of every detection the model emits, what fraction is a real weed? "
        "1.0 = no false positives. Low precision means the spray will fire "
        "on hats / paper / shadows."
    ),
    "Recall": (
        "Of every real weed in the validation set, what fraction did the "
        "model find? 1.0 = no missed weeds. Low recall means the drone "
        "flies over weeds without seeing them."
    ),
    "FPS (Hailo-8)": (
        "Frames per second on the Raspberry Pi 5 + Hailo-8 26 TOPS "
        "accelerator. Measured by `hailortcli benchmark` over SSH "
        "(see issue #5). At 30 FPS the FSM has fresh detections every "
        "33 ms; below ~15 FPS HOMING gets jittery."
    ),
    "Trained on": (
        "Dataset version + source used to train this checkpoint, e.g. "
        "`v3 / merged_dataset (4218 imgs)`. `— / —` means the registry "
        "row has no dataset_id (older runs)."
    ),
}

def metric_help(name: str) -> str | None:
    return METRIC_HELP.get(name)
```

Then in every `st.metric(...)` call wire it through:

```python
c3.metric("mAP50", fmt_metric(m.get("mAP50")), help=metric_help("mAP50"))
c4.metric("FPS (Hailo-8)", fmt_metric(m.get("fps_rpi_hailo8"), 1),
          help=metric_help("FPS (Hailo-8)"))
```

Streamlit renders `help=...` as a `?` icon next to the label that pops the
text on hover — zero layout cost, full glossary.

For the hand-rolled HTML cards in `_history()`, swap the bare label `<div>`
for a `<span>` with a `title="..."` attribute (native browser tooltip):

```python
def _label_with_help(label: str) -> str:
    h = metric_help(label) or ""
    safe = h.replace('"', "&quot;")
    return (f'<div style="color:#aaa;font-size:0.75em" '
            f'title="{safe}">{label}</div>')
```

…and use `_label_with_help("mAP50")` etc. inside the f-string.

For the `Trained on: — / —` line, fall back to a single dash + caption when
both fields are null:

```python
ds_ver = m.get("dataset_version")
ds_src = m.get("dataset_source")
ds_img = m.get("dataset_images")
if not (ds_ver or ds_src):
    ds_str = '<span style="color:#888">(no dataset linked — older training run)</span>'
else:
    ds_str = f"{ds_ver or '?'} / {ds_src or '?'}"
    if ds_img:
        ds_str += f" ({ds_img} imgs)"
```

For the Compare table, append a help row or attach `column_config` with
descriptions:

```python
import streamlit as st
st.dataframe(
    pd.DataFrame(comp_data),
    column_config={
        "Metric": st.column_config.TextColumn(
            "Metric",
            help="Hover each row name in the cells for definition."),
        v_a: st.column_config.NumberColumn(v_a, format="%.4f"),
        v_b: st.column_config.NumberColumn(v_b, format="%.4f"),
        "Δ (B−A)": st.column_config.NumberColumn(
            "Δ (B−A)", format="%+.4f",
            help="Positive = B is better. For FPS rows, integer comparison."),
    },
    use_container_width=True,
)
```

…and prepend a single `st.expander("What do these metrics mean?")` at the
top of the tab that dumps the full `METRIC_HELP` dict as a definition list,
so a first-time user sees it before having to hover anything.

While in there, also reword the units explicitly so the cards read:

- `mAP50` → `mAP@0.5` (industry-standard form, less ambiguous than the
  collapsed Ultralytics name)
- `mAP50-95` → `mAP@[0.5:0.95]`
- `FPS (Hailo-8)` → `FPS (Hailo-8 streaming)` once the dual-FPS column from
  issue #5 lands; add a second card `FPS (Hailo-8 HW only)`.

---

## 7. Flight Viewer model dropdown is unfiltered noise — needs pinned "best ground" to win

**Where**

- `ai_skydock/flight_viewer.py:525-534` — `/api/models` returns every `.pt`
  in the repo + every `runs/detect/*/weights/best.pt`.
- `ai_skydock/viewer/viewer.js:970-983` — `loadModels()` dumps them all into
  one flat `<select>`.
- `ai_skydock/model_registry/pinned.json` — already has `best_edge` /
  `best_ground` keys; the rest of the codebase honours them (deploy,
  evaluate, training-page select), but the flight-viewer model picker does
  not.

**Symptom**

Open Flight Viewer → "Run YOLO" model dropdown shows a long unsorted list:

```
yolov5n.pt
yolov5s.pt
yolov5m.pt
yolov5l.pt
yolov5x.pt
yolov8n.pt
yolov8s.pt
yolov8m.pt
yolov8l.pt
yolov8x.pt
yolo11n.pt
yolo11s.pt
…
runs/detect/ball_yolov8s/weights/best.pt
runs/detect/ball_yolov8s2/weights/best.pt
runs/detect/ball_yolov8s3/weights/best.pt
runs/detect/ball_yolov8x/weights/best.pt
runs/detect/ball_yolov8x4/weights/best.pt
…
```

After ~5 training runs this becomes unusable. There's no indication which is
the current best ground model, no grouping, no "default this", no filter.
The default-pick logic only looks for the literal first hit of three
hardcoded names (`yolov8s.pt`, `yolov8x.pt`, `yolo11n.pt`) which is almost
certainly not what you want to label new flights with:

```979:982:/home/fred/ai_skydock/viewer/viewer.js
for (const p of ['yolov8s.pt', 'yolov8x.pt', 'yolo11n.pt']) {
    if (list.includes(p)) { modelSelect.value = p; break; }
}
```

**Root cause**

`/api/models` is a flat directory scan and `loadModels()` doesn't talk to
`/api/training/pinned` or `/api/training/registry_models`. The pinning
machinery already exists — `flight_viewer.py:830-852` reads/writes
`model_registry/pinned.json` and the **training** page UI uses it
(`viewer.js:1554-1578`). The auto-label workflow that runs when you click
"Run YOLO" on a flight just doesn't subscribe to the same data.

**Fix**

Three small changes:

### a) `/api/models` returns structured groups, not a flat list

In `flight_viewer.py`:

```python
@app.route("/api/models")
def api_models():
    """Grouped model list with pinning info."""
    pinned = json.loads((BASE / "model_registry" / "pinned.json").read_text()) \
             if (BASE / "model_registry" / "pinned.json").exists() else {}

    base_pts = sorted(p.name for p in BASE.iterdir() if p.suffix == ".pt")

    registry: list[dict] = []
    reg_root = BASE / "model_registry"
    if reg_root.is_dir():
        for vdir in sorted(reg_root.iterdir(), reverse=True):
            pt = vdir / "best.pt"
            if pt.is_file():
                registry.append({
                    "version": vdir.name,
                    "path": str(pt.relative_to(BASE)),
                    "is_pinned_ground": pinned.get("best_ground") == vdir.name,
                    "is_pinned_edge":   pinned.get("best_edge")   == vdir.name,
                })

    runs: list[str] = []
    runs_dir = BASE / "runs" / "detect"
    if runs_dir.is_dir():
        for w in runs_dir.glob("*/weights/best.pt"):
            runs.append(str(w.relative_to(BASE)))

    return jsonify({
        "pinned": pinned,
        "registry": registry,   # newest first
        "base":     base_pts,   # yolov8n.pt etc.
        "runs":     runs,       # raw runs/detect/*/weights/best.pt
    })
```

### b) `loadModels()` honours pinning + uses `<optgroup>`

In `viewer.js`:

```js
async function loadModels() {
    const r = await fetch('/api/models');
    const data = await r.json();   // {pinned, registry, base, runs}
    modelSelect.innerHTML = '';

    const pinnedGround = data.pinned.best_ground;
    const pinnedEdge   = data.pinned.best_edge;

    // 1. Pinned options on top, pre-selected
    if (pinnedGround) {
        const reg = data.registry.find(m => m.version === pinnedGround);
        if (reg) {
            const og = document.createElement('optgroup');
            og.label = 'Pinned';
            const opt = document.createElement('option');
            opt.value = reg.path;
            opt.textContent = `⭐ Best Ground (${reg.version})`;
            og.appendChild(opt);
            if (pinnedEdge && pinnedEdge !== pinnedGround) {
                const er = data.registry.find(m => m.version === pinnedEdge);
                if (er) {
                    const eopt = document.createElement('option');
                    eopt.value = er.path;
                    eopt.textContent = `⭐ Best Edge (${er.version})`;
                    og.appendChild(eopt);
                }
            }
            modelSelect.appendChild(og);
        }
    }

    // 2. Registry (newest first)
    if (data.registry.length) {
        const og = document.createElement('optgroup');
        og.label = 'Registry';
        for (const m of data.registry) {
            const opt = document.createElement('option');
            opt.value = m.path;
            const tag = m.is_pinned_ground ? ' ⭐ground'
                      : m.is_pinned_edge   ? ' ⭐edge' : '';
            opt.textContent = `${m.version}${tag}`;
            og.appendChild(opt);
        }
        modelSelect.appendChild(og);
    }

    // 3. Base hub weights (collapsed by default — least useful)
    if (data.base.length) {
        const og = document.createElement('optgroup');
        og.label = 'Base (untrained hub weights)';
        for (const m of data.base) {
            const opt = document.createElement('option');
            opt.value = opt.textContent = m;
            og.appendChild(opt);
        }
        modelSelect.appendChild(og);
    }

    // 4. Run weights (only if "show all" toggled — see (c))
    if (data.runs.length && document.getElementById('showAllModelsChk')?.checked) {
        const og = document.createElement('optgroup');
        og.label = 'Run weights (raw)';
        for (const m of data.runs) {
            const opt = document.createElement('option');
            opt.value = opt.textContent = m;
            og.appendChild(opt);
        }
        modelSelect.appendChild(og);
    }

    // 5. Default selection: pinned ground > pinned edge > newest registry > first base
    const reg0 = data.registry[0]?.path;
    const def =
        (pinnedGround && data.registry.find(m => m.version === pinnedGround)?.path) ||
        (pinnedEdge   && data.registry.find(m => m.version === pinnedEdge)?.path) ||
        reg0 ||
        ['yolov8s.pt', 'yolov8x.pt', 'yolo11n.pt'].find(p => data.base.includes(p)) ||
        '';
    modelSelect.value = def;
    runYoloBtn.disabled = !modelSelect.value;
}
```

### c) Add a "Show all models" toggle

A small checkbox next to the model dropdown so users who actively want the
full mess can still get it; default off:

```html
<label class="muted" style="margin-left:8px">
  <input type="checkbox" id="showAllModelsChk"> show all
</label>
```

with `showAllModelsChk.addEventListener('change', loadModels)` in
`viewer.js`. When unchecked: pinned + registry + base. When checked: also
the `runs/detect/*/weights/best.pt` flood.

### d) Surface "pin from here" in the flight viewer

Right now you can only pin from the Training page. Add a `📌` button next to
the dropdown that POSTs to `/api/training/pinned/<version>` with
`pin_type=ground` for the currently selected option (only enabled when the
selection is a registry version). Then a quick "this run looks better" can
be locked in without leaving the flight viewer.

Net effect: open Flight Viewer → dropdown opens to `⭐ Best Ground (v004)`
already selected, the next 5 entries are recent registry versions ranked
newest-first, and the 30+ raw `runs/detect/*` entries are hidden behind a
toggle.

---

## 8. Flight Viewer draws 5–10 overlapping boxes per object — NMS is too lax + class-aware

**Where**

- `ai_skydock/flight_viewer.py:608` — Ultralytics `model.predict()` is
  called with only `conf=conf`. No `iou=`, no `agnostic_nms=`, no `classes=`.
- `ai_skydock/viewer/viewer.js:524-533` — render loop blindly draws every
  surviving box (cyan) on top of RPi detections (green) and manual boxes
  (orange).

**Symptom**

A single physical ball gets ~8–10 stacked cyan rectangles from one model
prediction. Visible in the user-attached screenshot of
`runs/detect/ball_yolo26x/weights/best.pt` at `conf=0.25`. They sit on top
of each other within a few pixels — clearly the same object, not different
ones.

**Root cause**

Two compounding effects:

1. **Default IoU threshold is too lax.** Ultralytics' `model.predict()`
   defaults to `iou=0.7`, meaning two boxes can overlap by up to 70% before
   either is suppressed by NMS. For tightly-packed near-identical detections
   on a small object this lets duplicates through.

2. **Class-aware NMS leaks duplicates across classes.** The ball model is
   fine-tuned over the COCO head and still emits multiple weed-proxy
   classes — `sports ball` (32), `frisbee` (29), occasionally `person` (0)
   — for the *same pixel region*. NMS in PyTorch/Ultralytics is by default
   **per-class**: a `sports ball@0.92` and a `frisbee@0.41` at the same
   location are treated as independent objects and both survive. Add a
   class-0 leak and you can see four+ co-located boxes from a single object.

   This matches the model's training history: the upstream
   `ai_callback.py` filter intentionally accepts
   `["sports ball", "frisbee", "person"]` as ball proxies, so the network
   was never trained to suppress those alternative class predictions. The
   viewer also doesn't filter by class — it draws every detection as
   `Ball XX%` regardless of which COCO class fired (`viewer.js:532`).

3. **No client-side de-dup.** Even when NMS lets 2–3 duplicates through,
   the rendering code happily stacks them. There is no second-pass merge.

**Fix**

### a) Tighten NMS at inference (`flight_viewer.py:608`)

```python
results = model.predict(
    str(img_path),
    conf=conf,
    iou=0.45,            # was implicit 0.7 — drops more duplicates
    agnostic_nms=True,   # NMS across classes, not within
    max_det=20,          # safety cap; one ball never needs 20+ boxes
    verbose=False,
)
```

`agnostic_nms=True` is the single most impactful change here — it merges
the `sports ball` / `frisbee` / `person` predictions on the same region
into one box (the highest-confidence one wins).

### b) Restrict to ball-class detections

The deployment runtime keeps only weed-proxy classes; the labelling viewer
should match. Pass `classes=[0, 29, 32]` (or the equivalent for your custom
model) so unrelated COCO classes never reach the canvas:

```python
BALL_LIKE_CLASSES = [0, 29, 32]   # person, frisbee, sports ball
results = model.predict(
    str(img_path),
    conf=conf,
    iou=0.45,
    agnostic_nms=True,
    classes=BALL_LIKE_CLASSES,
    max_det=20,
    verbose=False,
)
```

For a custom single-class ball model just use `classes=[0]`.

### c) Belt-and-braces client-side merge

Even with stricter NMS, when you slide the conf slider down to 0.05 you
will still get a ring of low-confidence false positives around a real
detection. Add a small dedup pass before rendering in `viewer.js` (e.g.
just before the loop at line 525):

```js
function dedupBoxes(dets, iouThresh = 0.5) {
    const sorted = [...dets].sort((a, b) => b[5] - a[5]);   // by conf desc
    const kept = [];
    for (const d of sorted) {
        const [, cx, cy, w, h] = d;
        const a = { x1: cx - w/2, y1: cy - h/2, x2: cx + w/2, y2: cy + h/2 };
        let suppressed = false;
        for (const k of kept) {
            const [, kcx, kcy, kw, kh] = k;
            const b = { x1: kcx - kw/2, y1: kcy - kh/2, x2: kcx + kw/2, y2: kcy + kh/2 };
            const ix = Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1));
            const iy = Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1));
            const inter = ix * iy;
            const union = w*h + kw*kh - inter;
            if (union > 0 && inter / union > iouThresh) { suppressed = true; break; }
        }
        if (!suppressed) kept.push(d);
    }
    return kept;
}
```

Then in the render loop:

```js
for (const d of dedupBoxes(detections[stem] || [])) {
    // … existing draw code …
}
```

Apply the same dedup to the `dets_map[stem]` payload in `/api/approve`
(`flight_viewer.py:672-681`) so approved labels written to staging never
contain stacked duplicates.

### d) Optional: surface a "max boxes per frame" slider

A small input next to Conf:

```html
<label>Max boxes <input type="number" id="maxBoxes" value="3" min="1" max="20"></label>
```

then `dedupBoxes(...).slice(0, maxBoxes)` before rendering. Useful for
flight scenarios where you know there's only one ball anyway — keeps a
single highest-confidence box even when NMS let 2–3 close ones survive.

After this change the screenshot situation collapses from 8+ stacked cyan
boxes down to a single `Ball 92%` box, and approving the frame writes one
clean YOLO label line instead of a polluted multi-row label that would
re-train the next generation to be even more duplicate-prone.

---

## 9. Flight Viewer "Copy approved → staging" silently fails to ingest, no per-flight / multi-batch dataset workflow

**Where**

- `ai_skydock/flight_viewer.py:634-708` — `/api/approve` writes
  `staging/{images,labels,meta}/` and `staging/batch_info.json`.
- `ai_skydock/dashboard_pages/data.py:48-63` — Data tab structure (Convert
  flight → staging | Validate + Ingest | Dataset versions | Hard cases).
- `ai_skydock/dashboard_pages/data.py:115-249` — `_convert_flight()` copies
  flight → staging, **overwrites** `batch_info.json` (line 243) without
  checking what's already there.
- `ai_skydock/add_data.py:192-200` — strict "class id is 0 (Ball only)"
  validator.
- `ai_skydock/add_data.py:253-338` — `ingest()` always copies the entire
  previous version into `vN+1` (line 271-276); there is no alternative
  ingest mode.

**Symptom**

User clicks "Copy approved → staging" in the Flight Viewer. Frames + labels
+ meta land in `staging/` correctly. They then open the Data tab.

- The "Convert flight → staging" tab (the *first* tab, the one that lands
  by default) shows nothing about the staging contents — no counters, no
  "1 batch waiting", nothing. It's a *write-only* view.
- The "Validate + Ingest" tab does see staging, but if the Flight Viewer
  used a COCO/hub model (anything not the custom Ball-only fine-tune) the
  dry-run dies with `class id 32 (expected 0 = Ball)` — the labels were
  written with raw COCO class IDs.
- If the user re-uses the *first* tab to convert another flight while a
  Flight Viewer batch is already staged, `_convert_flight()` overwrites
  `staging/batch_info.json` (data.py:243) and merges images into the same
  flat dirs, silently mixing two batches under one (last-write-wins)
  metadata blob.
- There is no "ingest only flight X", no "ingest each flight as its own
  dataset", and no "ingest multiple flights as one fresh dataset" path.
  Every successful ingest just adds to a single monotonically growing
  `vN+1` chain (`add_data.py:271-276` clones `vN` then adds staging).

**Root cause**

Three independent issues collide:

1. **Class-ID mismatch.** `flight_viewer.py:680` writes `int(cls)` straight
   from the model output:
   ```python
   lines.append(f"{int(cls)} {cx:.6f} ...")
   ```
   With a COCO base model, `cls=32` (sports ball) or `cls=29` (frisbee)
   passes through unchanged. `add_data.py:192-195` then rejects every
   single line. The user sees "validation failed" and assumes the Data
   page "doesn't read it" — it reads it, but rejects it.

2. **Single-tenant staging.** `staging/` is a single flat tree. Both the
   Flight Viewer (`flight_viewer.py:646-651`) and `_convert_flight`
   (`data.py:196-199`) write into the *same* `staging/{images,labels,meta}/`
   and overwrite the *same* `batch_info.json`. Two batches in the staging
   area at the same time = data corruption.

3. **No staging visibility.** The Data tab's first sub-tab is the only one
   visible by default. It has no `st.metric`/`st.info` block telling you
   "staging has 54 images from 2026-04-27_flight02 (Flight Viewer)". The
   user has no signal that their work was even received.

4. **No alternative ingest modes.** `add_data.py` has exactly one mode:
   `vN+1 = vN ∪ staging`. There is no:
   - "fresh dataset" mode (don't inherit vN)
   - "named dataset" mode (`flight02_only`, not `v7`)
   - "split-by-flight" mode (one dataset per `flight_id`)
   - "queue staging" mode (accumulate multiple Flight Viewer batches before
     ingesting them as a coherent v-bump)

**Fix**

### a) Remap class IDs at staging write-time (`flight_viewer.py`)

The Flight Viewer is the *labeling* surface — its output is supposed to be
clean Ball labels, not raw COCO predictions. Add a class-id remap before
writing the label file:

```python
# Top of file:
COCO_BALL_LIKE = {0, 29, 32}   # person, frisbee, sports ball
DATASET_BALL_CLASS = 0          # what add_data.py expects

# Replace lines 674-681 with:
lines = []
for det in dets_map[stem]:
    cls, cx, cy, w, h = det[0], det[1], det[2], det[3], det[4]
    cf = det[5] if len(det) > 5 else 1.0
    if cf < min_conf:
        continue
    if cls in COCO_BALL_LIKE or _is_custom_ball_model(model_name):
        cls = DATASET_BALL_CLASS
    else:
        continue   # drop labels that aren't ball-proxy classes
    lines.append(f"{int(cls)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
lbl_dst.write_text("\n".join(lines) + "\n")
```

(`_is_custom_ball_model` = simple heuristic: model lives under
`runs/detect/` or `model_registry/`, not in `BASE`.)

### b) Show staging contents at the top of the Data tab

In `data.py:render()`, before the tabs:

```python
def _staging_summary() -> dict:
    img_dir = STAGING / "images"
    bi_path = STAGING / "batch_info.json"
    meta_dir = STAGING / "meta"
    if not bi_path.exists() or not img_dir.is_dir():
        return {"empty": True}
    n_imgs = sum(1 for p in img_dir.iterdir()
                 if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    bi = json.loads(bi_path.read_text())
    flights = set()
    if meta_dir.is_dir():
        for m in meta_dir.glob("*.json"):
            try:
                flights.add(json.loads(m.read_text()).get("flight_id"))
            except Exception:
                pass
    flights.discard(None)
    return {
        "empty": n_imgs == 0,
        "n_imgs": n_imgs,
        "flights": sorted(flights),
        "source": bi.get("source", "?"),
        "date": bi.get("date", "?"),
    }

def render() -> None:
    st.header("Data")
    s = _staging_summary()
    if not s.get("empty"):
        cols = st.columns(4)
        cols[0].metric("Staged images", s["n_imgs"])
        cols[1].metric("Flights", len(s.get("flights", [])))
        cols[2].caption(f"Source: {s.get('source','?')}")
        cols[3].caption(f"Date: {s.get('date','?')}")
        if s.get("flights"):
            st.caption("From: " + ", ".join(s["flights"]))
        if st.button("Clear staging", key="clear_staging"):
            for sub in ("images", "labels", "meta"):
                for f in (STAGING / sub).glob("*"):
                    f.unlink(missing_ok=True)
            (STAGING / "batch_info.json").unlink(missing_ok=True)
            st.rerun()
    tabs = st.tabs([...])
```

That single banner means "the Flight Viewer worked" or "staging is empty"
becomes a 1-second visual answer instead of a 5-minute filesystem hunt.

### c) Multi-batch staging with explicit ingest modes

Replace the single flat `staging/` with a versioned subdir scheme:

```
staging/
  pending/
    2026-04-27_flight02__1730034011/
      images/  labels/  meta/  batch_info.json
    2026-04-27_flight03__1730034400/
      images/  labels/  meta/  batch_info.json
```

`flight_viewer.py:/api/approve` writes to a *new timestamped subdir* every
time, never the legacy flat tree. `_convert_flight` does the same. Then on
the Data tab show all pending batches as a checklist:

```
☑ 2026-04-27_flight02 — 54 images (Flight Viewer · 2026-04-27)
☑ 2026-04-27_flight03 — 78 images (Flight Viewer · 2026-04-27)
☐ 2026-04-26_flight01 — 22 images (auto_label · 2026-04-26)

Ingest mode:
  ( ) Add to current dataset (vN → vN+1)        ← today's behaviour
  ( ) New fresh dataset (no inheritance)        ← e.g. "ball-only-2026-04"
  ( ) Per-flight datasets (one vN+1 per flight) ← isolate by flight
  ( ) Per-batch datasets (one vN+1 per batch)
Dataset name (optional, fresh mode only): [______________]
```

`add_data.py` grows three new flags:

```python
parser.add_argument("--mode", choices=["append", "fresh", "per-flight",
                                       "per-batch"], default="append")
parser.add_argument("--name", default=None,
                    help="Dataset name (fresh mode only)")
parser.add_argument("--batch", action="append", default=None,
                    help="staging/pending/<batch> dirs to include "
                         "(repeatable; default: all)")
```

`mode=append` keeps current behaviour. `mode=fresh` skips the
`shutil.copytree(prev_dir, dest_dir)` at line 271-276 so the new dataset
contains *only* the staged batches. `mode=per-flight` groups batches by
their `flight_id` field and produces one `vN+M` per group.
`mode=per-batch` produces one `vN+M` per batch dir.

### d) Side-step the conflict at the protocol level

Even before (c) lands, fix the immediate clobber bug: in
`flight_viewer.py:/api/approve`, refuse to write if `batch_info.json`
already exists with a different `source` or `flight_id`, and tell the
client:

```python
bi_path = STAGING / "batch_info.json"
if bi_path.exists():
    try:
        existing = json.loads(bi_path.read_text())
    except Exception:
        existing = {}
    if existing.get("source") != "flight_viewer" or \
       existing.get("flight_id") not in (None, "", fid):
        return jsonify({
            "error": "staging not empty (different batch in progress); "
                     "go to Data → Validate + Ingest, or click Clear staging.",
            "existing_batch": existing,
        }), 409
```

UI in `viewer.js` shows the error verbatim instead of "ok".

After (a)+(b)+(d) the user's *immediate* problem ("I clicked it and
nothing happened") goes away in a single afternoon. (c) is the bigger
refactor that gives them the per-flight / per-batch / fresh-dataset
workflow they want.

---

## 10. Flight Viewer doesn't feel integrated — it's a separate Flask app iframing the dashboard

**Where**

- `ai_skydock/flight_viewer.py:42, 1430-1431` — Flask app on `:8502`,
  hand-rolled HTML/CSS/JS under `viewer/`.
- `ai_skydock/dashboard_pages/*.py` — Streamlit app on `:8501`, separate
  process, separate visual language, separate state.
- `ai_skydock/viewer/index.html:30-40` — top nav has 9 buttons, only 2
  ("Flight Viewer", "Training") are native Flask pages; the other 7 load
  Streamlit in an iframe.
- `ai_skydock/viewer/viewer.js:1057` — hardcodes
  `http://localhost:8501/?page=${dashTarget}` as the iframe `src`.
- `ai_skydock/dashboard_lib.py:296-341` — `ensure_flight_viewer_running()`
  spawns Flask as a subprocess of Streamlit (PID file +
  `.flight_viewer.log`), so launch order matters and silent restarts
  leak processes.

**Symptom**

Looks like one app, behaves like two. The visible seams:

1. **Different visual languages on either side of the navbar.** Click
   "Flight Viewer" — dark hand-rolled CSS, Inter font, cyan accents,
   compact widgets. Click "Model History" — Streamlit chrome, default
   sans-serif, big white sidebar, pastel buttons, totally different
   typography and spacing. Inside the *same browser tab*, by clicking a
   single nav item.

2. **Hard-coded `localhost:8501` iframe.** `viewer.js:1057` does
   `dashFrame.src = "http://localhost:8501/?page=..."` — breaks the
   moment you SSH-tunnel one port but not the other, run on a different
   host, or change Streamlit's port. The "Model History" button just
   shows a blank frame.

3. **No shared state.** Selecting `2026-04-27_flight02` in the Flight
   Viewer sidebar doesn't hint that flight to the Streamlit "Hard Cases"
   page. Streamlit's pinned-model selection doesn't carry over to the
   Flight Viewer's "Run YOLO" dropdown (Issue #7). Flight Viewer's
   `/api/training/registry_models` and Streamlit's `db_models()` are two
   independent reads of the *same* `registry.db` from two separate
   processes.

4. **Two parallel implementations of the same thing.**
   - **Models list:** `flight_viewer.py:525-534` (`/api/models`) vs
     `dashboard_lib.py:db_models()`.
   - **Pinned models:** `flight_viewer.py:830-852`
     (`/api/training/pinned`) vs
     `dashboard_lib.py:103 load_pinned_models()`.
   - **Staging status:** `flight_viewer.py:720-738`
     (`/api/training/staging_status`) vs `dashboard_pages/data.py`'s
     direct filesystem inspection.
   - **Training trigger:** Flight Viewer has its own `loadTrainingPage()`
     and job runner (`flight_viewer.py:44-130, train_job_state.json`,
     `train_job.log`); Streamlit has its own `train_queue.py` flow.
     **These two training entry points are mutually invisible** — start
     a job from one, the other UI doesn't know.

5. **Subprocess fragility.** `dashboard_lib.py:ensure_flight_viewer_running`
   spawns Flask from Streamlit, with a PID file + log + port probe. If
   Streamlit crashes, the Flight Viewer keeps running with a stale PID
   file. If Flight Viewer crashes, Streamlit silently iframes a dead
   port. If you start Flight Viewer first (`python flight_viewer.py`),
   the Streamlit "Flights" tab works via iframe but the Flight Viewer's
   own iframe-back-into-Streamlit only works if you *also* spin up
   Streamlit on `:8501` — but nothing told you to.

6. **CORS / auth boundaries.** Two origins (`:8501`, `:8502`), no shared
   session, no auth — fine for `localhost` but means there's no way to
   put auth in front of one of them without bespoke proxy work.

7. **Confusing navigation chrome.** The Streamlit app, viewed *outside*
   the Flight Viewer iframe, has its own page-switcher/sidebar — a
   *different* navigation than the Flight Viewer's top bar. Power users
   end up using both, hitting the same logical page two ways with two
   different URLs.

**Root cause**

The Flight Viewer was built as an independent Flask labelling tool for a
specific flow (frame-by-frame YOLO approve/skip with manual annotation
on `<canvas>`), then "wrapped around" the existing Streamlit dashboard
by adding a top nav that iframes it. The integration is a UI shell, not
a real merge of state, styling, or process model.

There's also no architectural doc that says "Flask owns flights +
training UX, Streamlit owns analytics + registry views". Each side has
quietly grown features the other already has (the duplicate model lists,
duplicate pinning machinery, duplicate training job runners).

**Fix**

Three options, increasing in scope. Pick based on how much rework you
want to do *before* the upcoming retrain.

### Option A — Make the iframe shell honest (1 day)

Treat the current architecture as fine, just stop the rough edges.

1. **Pass the dashboard origin in.** Add `DASH_PORT` /
   `DASH_ORIGIN` env vars consumed by both `flight_viewer.py` (renders
   `index.html`) and `viewer.js`. Remove the hardcoded `:8501`:

   ```js
   const DASH_BASE = window.__DASH_BASE__;        // injected by template
   document.getElementById('dashFrame').src = `${DASH_BASE}/?page=${dashTarget}`;
   ```

   Render the value from a tiny `/config.js` Flask route that reads
   `os.environ.get("DASH_BASE", "http://localhost:8501")`.

2. **Single launcher script.** `bin/dashboard.sh` that starts both
   processes with health checks, prints both URLs, traps SIGINT to kill
   both. Kill `ensure_flight_viewer_running()` — Streamlit-spawning-Flask
   is the wrong direction (Streamlit reruns on every interaction).

3. **Embed mode for Streamlit.** Streamlit has `?embed=true` which hides
   its own header/sidebar. Use that on the iframe URL so the Flight
   Viewer's top nav is the *only* navigation visible on dashboard pages:

   ```js
   `${DASH_BASE}/?embed=true&page=${dashTarget}`
   ```

4. **Unify the visual language.** Streamlit's chrome can't fully match
   the Flight Viewer's hand-rolled CSS, but you can `st.markdown(...,
   unsafe_allow_html=True)` a `<style>` block at the top of every page
   that matches the Flight Viewer's CSS variables (`--bg`, `--accent`,
   `--border`, font stack). Land it once in `dashboard_lib.py` and call
   it from each page's `render()`.

5. **Cross-frame state.** Use `postMessage` so the Flight Viewer's
   flight selection propagates into the iframe and vice versa:

   ```js
   // outer
   dashFrame.contentWindow.postMessage(
       {type: 'flight', value: flightId}, DASH_BASE);
   ```

   Streamlit-side: a small `streamlit-component` or
   `st.components.v1.html` listener that calls `st.session_state` then
   `st.rerun()`.

That removes seams 1-3 and (with the launcher) seam 5 of the symptom
list. Seams 4, 6, 7 stay.

### Option B — Move the Flight Viewer *into* Streamlit (3-4 days)

Streamlit can host a frame-by-frame canvas labeller via
`streamlit-drawable-canvas` + a custom component for the keyboard
shortcuts. Replace the Flask app with a Streamlit page:

```
dashboard_pages/
  flights.py       # the new Flight Viewer, native Streamlit
  data.py
  train.py
  ...
```

Pros:
- One process, one origin, one visual language.
- Direct access to `db_*` helpers and `load_pinned_models()` —
  duplicates from list (4) collapse into single sources of truth.
- `st.session_state` shares flight/model/dataset selection across all
  pages for free.
- Auth/proxy story becomes "put a reverse proxy in front of Streamlit",
  done.

Cons:
- Streamlit's interaction model (full-page rerun on every event) is a
  bad fit for a canvas labeller that needs sub-100ms response on
  click/drag/keystroke. Will need a custom component
  (`streamlit-drawable-canvas` is close but slow at scale).
- ~1 week of UI rework. The current canvas + filmstrip + keyboard
  shortcuts in `viewer.js` is ~1500 lines of polish you'd have to redo.

### Option C — Move Streamlit pages *into* the Flask app (5-7 days)

Flip the direction: keep the fast hand-rolled UI, port Streamlit pages
to Flask + a small JS framework (or vanilla, like `viewer.js` already
does). Each `dashboard_pages/<page>.py` becomes a Flask route + JSON API
+ HTML template.

Pros:
- One process, native fast UI, full control of state and styling.
- The training trigger (Issue #4b/#5) becomes trivial — Flight Viewer
  already has a job runner (`flight_viewer.py:44-130`); it just needs
  the right frontend.
- `registry.db` is read directly, no Streamlit `st.cache` weirdness.

Cons:
- Largest rework. Lose `st.dataframe`, `st.bar_chart`, `pd.DataFrame`
  → Streamlit one-liners; you'd reimplement those with a small chart
  lib.
- Loses the "drop a `.py` file in `dashboard_pages/` and it appears as a
  tab" workflow which is convenient when prototyping.

### Recommendation

**Do Option A now** (1 day, unblocks the immediate "doesn't feel
integrated" complaint), and treat Option B/C as the medium-term decision
once the retrain pipeline (#1-#9) is no longer the bottleneck. Without
A, every other UI fix in this report (#7 model dropdown, #9 staging
banner, #6 metric tooltips) lands on the *Streamlit* side of the
seam — meaning the Flight Viewer keeps feeling separate even after
those land.

The single lowest-cost win is step 4 of Option A: ~30 lines of CSS in a
shared `_inject_dashboard_css()` helper that every Streamlit `render()`
calls. That alone removes the visual whiplash that triggered the "doesn't
feel integrated" reaction.

---

## 11. Train → "Finetune from" lets you pick any version, even of the wrong architecture

**Where**

- `ai_skydock/dashboard_pages/train.py:160` — finetune dropdown is built
  from every model in the registry:
  ```python
  finetune_versions = ["(none)"] + [m["version"] for m in db_models()]
  ```
- `ai_skydock/dashboard_pages/train.py:181, 192, 293, 305-307` — the
  "Model arch" and "Finetune from" selectors are independent inputs in
  both the **Train now** and **Queue** forms; nothing checks they're
  compatible.
- `ai_skydock/2_train.py:246-250` — when `--finetune-from` is set,
  `--model` is **silently dropped**:
  ```python
  if args.finetune_from:
      weights = str(get_model_pt_path(args.finetune_from))
      print(f"Finetune from : {args.finetune_from} → {weights}")
  else:
      weights = args.model
  ```
- `ai_skydock/viewer/viewer.js:42-100` — the *Flight Viewer's* training
  page already has a `_refreshFinetuneDropdown()` that filters by arch
  family. The Streamlit page does not. (Yet another duplicate from
  Issue #10.)

**Symptom**

In the Train tab → "Train now" form the user picks:

```
Model arch:    yolo11n.pt
Finetune from: v003           ← was trained on yolov8s.pt
```

Clicks "Start training". The run launches with `--model yolo11n.pt
--finetune-from v003`. Inside `2_train.py:246-250` the `--model` arg is
discarded and the run continues from `v003/best.pt` — a yolov8s
checkpoint. The user thinks they're training a yolo11n; they're
actually adding more epochs to a yolov8s. The registry entry for the
new run is then re-tagged as `yolov8s` (line 252-266 looks up
`model_arch` from the source row), so even the post-mortem view in
`Train → Runs` shows the "wrong" arch silently.

Edge case is even worse: a 1-class Ball fine-tune chained from a stock
80-class hub model gives confused class counts (cf. Issue #3.1) — and
the UI provides no signal at all that a chained finetune is happening
across a class-count boundary.

**Root cause**

Two design issues collide:

1. **The dropdown is unfiltered.** `db_models()` returns every
   `(version, model_arch)` row in `training_runs`; the form just puts
   versions into the selectbox. There's nothing keyed off the currently
   selected `Model arch`.

2. **`Model arch` is dead weight when `Finetune from` is set.**
   `2_train.py` treats the two flags as alternatives, not as a
   compatibility pair. So even if the user picked "right" the UI is
   misleading — the `Model arch` value has no effect on the resulting
   run when finetune is non-`(none)`. There's nothing in the UI that
   says "you've now overridden the arch above".

3. **The compatibility rule is undocumented.** Ultralytics will *attempt*
   to load a yolov8s checkpoint into a yolo11n model and crash with a
   shape-mismatch deep in `torch.load` once the user is 5 minutes into
   a run. That's a tarpit failure mode — long enough to feel real, late
   enough that you've already wasted GPU time.

**Fix**

Three layers, smallest first.

### a) Filter the finetune dropdown to compatible versions

In `dashboard_pages/train.py`, mirror the logic that
`viewer/viewer.js:42-100` already uses for the Flight Viewer's training
page. Add a small helper at the top of the file:

```python
def _arch_family(arch: str | None) -> str:
    """Group archs that can finetune across each other.

    yolov8{n,s,m,l,x} all share the same head topology so weights
    transfer across sizes (ultralytics handles the channel-count jump);
    yolo11{n,...} share a different topology. Cross-family finetune is
    not supported by ultralytics out of the box.
    """
    a = (arch or "").lower()
    for fam in ("yolov8", "yolo11", "yolo26"):
        if a.startswith(fam):
            return fam
    return a or "unknown"


def _compatible_finetunes(selected_arch: str) -> list[dict]:
    fam = _arch_family(selected_arch)
    return [m for m in db_models()
            if _arch_family(m.get("model_arch")) == fam]
```

Then in `_train_now()` replace lines 160 + 192 with:

```python
# 192-ish, *after* model_arch is chosen:
compat = _compatible_finetunes(model)
if compat:
    finetune_versions = ["(none)"] + [
        f"{m['version']}  ({m.get('model_arch','?')}, "
        f"mAP50={m.get('mAP50','—')})"
        for m in compat
    ]
else:
    finetune_versions = ["(none)"]
finetune_label = st.selectbox(
    "Finetune from", finetune_versions, index=0,
    help=f"Filtered to arch family `{_arch_family(model)}`. "
         f"Cross-family finetune is not supported.",
)
finetune = finetune_label.split()[0] if finetune_label != "(none)" else "(none)"
```

The label includes `model_arch` and `mAP50` so the user has a concrete
reason to pick `v003 (yolov8s, mAP50=0.84)` over `v007 (yolov8s,
mAP50=0.71)`. Same edit applies to the Queue form (line 305-307).

### b) Disable / mark "Model arch" when finetune is set

When a finetune source is chosen, the `Model arch` value is ignored by
`2_train.py`. Surface that in the UI:

```python
if finetune != "(none)":
    sel = next(m for m in compat if m["version"] == finetune)
    st.info(f"Using `{sel['model_arch']}` weights from {finetune}. "
            f"`Model arch` selection is ignored when finetuning.")
    # Force the model field to match — defends against an arch-mismatch
    # crash if the user manually chose a different family.
    model = sel["model_arch"]
```

So the form output is internally consistent and the user sees explicitly
what arch the run will actually use.

### c) Hard-fail in `2_train.py` on cross-family finetune

Even with the UI fixed, the CLI is still callable with mismatched flags
(queue editing, scripts, the `train_queue.py` worker). Add a guard
right after weight resolution at line 250:

```python
if args.finetune_from:
    weights = str(get_model_pt_path(args.finetune_from))
    src_arch = _lookup_arch_from_registry(args.finetune_from)
    if args.model and _arch_family(args.model) != _arch_family(src_arch):
        raise SystemExit(
            f"Cross-family finetune not supported: --model "
            f"{args.model} (family {_arch_family(args.model)}) vs "
            f"--finetune-from {args.finetune_from} "
            f"({src_arch}, family {_arch_family(src_arch)}). "
            f"Drop --model or pick a same-family source."
        )
```

Same `_arch_family` helper as (a) — extract it to `dashboard_lib.py` so
both the CLI and the UI share it. That kills the duplicate logic in
`viewer/viewer.js` too: have the Flight Viewer's
`_refreshFinetuneDropdown()` consume `/api/training/registry_models`'s
`model_arch` field via the same family rule.

### d) (Stretch) Class-count compatibility check

Even within a family, a 1-class Ball fine-tune chaining from a 80-class
hub checkpoint silently re-uses the 80-class head (Ultralytics expands
the cls head to match `data.yaml`'s `nc`). Worth a `st.warning(...)`
when the source's `nc` and the selected dataset's `nc` differ — and a
hard error in `2_train.py` if the user is *not* doing a deliberate
class-count change (rare but valid for distillation).

After (a)+(b)+(c), the dropdown shows only sensible choices, the form
output is internally consistent, and a misuse via CLI gives a clean
message instead of a 5-minute-in `torch.load` crash.

---

## 12. Compile (ONNX → HEF) button shows no live output, dies on Streamlit restart

**Where**

- `ai_skydock/dashboard_pages/deploy.py:144-157` — Compile HEF button:
  ```python
  with st.spinner(f"Compiling {len(selected_targets)} model(s) ..."):
      res = subprocess.run(
          ["bash", str(REPO / "3_compile_hailo8.sh"), *selected_targets],
          capture_output=True, text=True, cwd=str(REPO),
      )
  if res.returncode == 0:
      st.success(...)
      st.code((res.stdout or "No stdout")[-6000:], language="text")
  ```
- `ai_skydock/dashboard_pages/deploy.py:163-174` — same pattern for the
  "Push HEF to Raspberry Pi" button.
- `ai_skydock/compile_worker.py:100-127` — there's already a worker that
  does this *correctly* (streams to `model_registry/<v>/compile.log`,
  writes `compiling`/`compiled`/`failed` rows to DB, holds
  `.compile.lock`). The button just doesn't use it.

**Symptom (verbatim from the user)**

> Compile (ONNX → HEF)
>
> Models to compile
> v004 (registry)
>
> Compiling 1 model(s) ...

That spinner stays on screen for 5–15 minutes per model with **zero
output**. No stdout, no stderr, no progress, no log path, no PID.
Worse, if anything triggers a Streamlit script rerun mid-compile —
clicking another widget, switching tabs, even Streamlit's own auto-rerun
on file change — the subprocess is killed with the script and the
compile is gone, with no row in the DB to show it ever happened.

**Root cause**

`subprocess.run(..., capture_output=True)` is the wrong pattern for any
job that runs longer than a Streamlit form roundtrip. It does three
fatal things:

1. **Buffers stdout/stderr in memory until exit.** No streaming, no
   tail, no progress bar. The `st.spinner` is a glorified hourglass.
2. **Lives inside the Streamlit script thread.** Streamlit reruns the
   whole script on every interaction — so the moment anything else on
   the page is clicked (or the page is refreshed, or the server is
   stopped/restarted by the dashboard launcher, or Streamlit's
   file-watcher trips on a saved log file) the subprocess gets
   `SIGTERM` along with the script.
3. **Writes nothing durable.** No PID file, no log file, no DB row →
   no way to tell from outside the dead Streamlit thread that a
   compile ever started, let alone how far it got.

The repo has the *correct* primitive sitting right there:
`compile_worker.py` already implements the full
spawn-detached + stream-to-log + DB-status-update pattern. The
`Train → Compile worker` tab even has UI for it
(`train.py:379-451`). Deploy's compile button just bypasses all of it
and reaches straight for the blocking `subprocess.run`. Same mistake on
the rsync push button below it.

**Fix**

Reuse the worker. Two paths, pick whichever you prefer:

### a) Cheapest — call `compile_worker.py` instead of the script

`compile_worker.py` already mints the right log files and DB rows. Just
mark the targets `pending` and spawn the worker detached:

```python
if st.button(btn_label, type="primary",
             disabled=len(selected_targets) == 0, key="compile_hef_btn"):
    # 1. Mark each selected target pending in the DB
    conn = get_conn()
    for tgt in selected_targets:
        v = Path(tgt).parent.name
        if v.startswith("v") and v[1:].isdigit():
            conn.execute(
                "UPDATE models SET compile_status='pending' WHERE version=?",
                (v,))
    conn.commit(); conn.close()

    # 2. Spawn the worker detached (mirrors train.py:_train_now)
    LOG_DIR = REPO / "logs"; LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"compile_{datetime.now():%Y%m%d_%H%M%S}.log"
    with open(log_path, "wb") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-u", "compile_worker.py"],
            cwd=str(REPO), stdout=lf, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (REPO / ".compile_session.log").write_text(str(log_path))
    st.success(f"Compile started (pid {proc.pid}). Tailing log below.")
    st.rerun()
```

Then on every render, *before* the form, show a live tail if a
compile is in progress:

```python
lock = MODEL_REG / ".compile.lock"
log_pointer = REPO / ".compile_session.log"
if lock.exists() or (log_pointer.exists() and log_pointer.is_file()):
    pid = lock.read_text().strip() if lock.exists() else "?"
    st.warning(f"🔒 Compile in progress (pid {pid})")
    log_path = Path(log_pointer.read_text().strip()) if log_pointer.exists() else None
    if log_path and log_path.is_file():
        st.code(_tail(log_path, 80), language="text")
    cols = st.columns(2)
    if cols[0].button("Refresh"):
        st.rerun()
    if cols[1].button("Stop", key="compile_stop_btn"):
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        except Exception as e:
            st.error(f"Could not stop: {e}")
        st.rerun()
```

The same `_tail()` helper that already exists in `train.py:139-146`
applies here — extract it to `dashboard_lib.py` so all three
long-running-job UIs (train, queue, compile) share it.

### b) Slightly more invasive — compile_worker as a daemon

Run `compile_worker.py --watch` as a system service (or as a one-shot
spawned by `dashboard_lib.ensure_compile_worker_running()` mirroring the
flight-viewer subprocess pattern at `dashboard_lib.py:296-341`). Then
the Compile button just sets DB rows to `pending` and the daemon picks
them up at the next poll (default 30s). The Deploy tab tails
`model_registry/<version>/compile.log` per-version, which is
**already** what the worker writes (line 113-118 of compile_worker.py).

### c) Same fix for "Push HEF to Raspberry Pi"

`deploy.py:163-174` has the same blocking-`subprocess.run` shape on the
rsync push, with the same restart-fragility:

```python
if st.button("Push to Pi", ...):
    with st.spinner(...):
        res = subprocess.run(
            ["bash", str(REPO / "5_deploy_to_rpi.sh"), sel, rpi_host, rpi_user],
            capture_output=True, text=True, cwd=str(REPO),
        )
```

A 200 MB rsync over SSH is short enough that the user pain is smaller,
but the principle is identical. Spawn detached, write
`.deploy.{pid,log}`, tail in-page on rerun. Or — simplest — just drop
`capture_output=True` and tee `5_deploy_to_rpi.sh` output to a log file,
then tail it inside an `st.empty()` placeholder updated every second
via `st.experimental_rerun`. Either way, the user sees rsync progress
instead of a 30-second silent spinner.

### d) Make state persistent across Streamlit restarts

`.compile.lock` already persists (line 47-67 of `compile_worker.py`).
The missing piece is the *log pointer* — without it, on Streamlit
restart the page can't find the live log even though the worker is
still running. Two artefacts written at spawn time fix this:

- `MODEL_REG / ".compile.session"` — JSON `{pid, log_path, started_at,
  targets: [v004, v005, ...]}` — survives Streamlit restart.
- A `_recover_compile_session()` helper called from `render()` that
  reads the session file, validates the PID is alive (mirroring
  `_running()` in `train.py:127-136`), and shows the tail. Match the
  same pattern as `flight_viewer.py:_recover_job` (lines 69+) so all
  three long-running-job UIs use one shared shape.

After (a)+(c)+(d) the user gets:

- Live tail of the Hailo Docker compile (`Loaded 150 calibration
  images`, `[1/3] Parsing ONNX model`, etc.) instead of a silent
  spinner.
- A "Compile in progress (pid 12345)" banner when they reload the page
  or the server restarts.
- A way to actually `Stop` the compile (today there's no kill button
  — they have to find the PID via `ps`).
- The same UX for the rsync push.

---

## 13. "Pin as ground" silently rejects every `runs/detect/*` weight — only registry paths work

**Where**

- `ai_skydock/viewer/viewer.js:1093-1116` — pin button regex-matches
  *only* `model_registry/vNNN/best.pt`:
  ```js
  const m = v.match(/^model_registry\/(v\d+)\/best\.pt$/i);
  if (!m) {
      setStatus('Pin only works for registry paths model_registry/vNNN/best.pt', 'err');
      return;
  }
  ```
- `ai_skydock/viewer/index.html:88-93` — the **Pin as ground** button
  is always enabled regardless of what's selected in the dropdown.
- `ai_skydock/flight_viewer.py:525-534` — `/api/models` returns *both*
  `model_registry/vNNN/best.pt` and every `runs/detect/*/weights/best.pt`
  unfiltered, so it's trivial to land on a `runs/detect/...` selection
  (especially when the user enables the visible "Show
  `runs/detect` weights" checkbox at `index.html:84-87`).
- `ai_skydock/2_train.py:397-443` — does auto-promote
  `runs/detect/<name>/weights/best.pt` → `model_registry/vNNN/best.pt`
  at the end of a successful run. Killed/crashed runs and any weights
  produced outside of `2_train.py` (e.g. an old run, a manual ultralytics
  invocation, a copy from the Flight Viewer's training page) sit in
  `runs/detect/` forever and never get a registry entry.

**Symptom (verbatim from the user, screenshot attached)**

The Flight Viewer's right sidebar shows:

```
Model
[ runs/detect/ball_yolo26x/weights/best.pt ]
[ ] Show runs/detect weights
[ Pin as ground ]
…
[ Copy approved → staging ]
[ Save session ]

Pin only works for registry paths
model_registry/vNNN/best.pt
```

User clicks **Pin as ground**. Nothing visible happens, except the same
red status flashing the same string they can already see two lines
below the button. There is no way from this UI to:

1. Pin a weight that isn't already in the registry.
2. Promote a `runs/detect/*` weight to the registry without dropping
   to a shell.
3. Tell whether the `runs/detect/*` weight they're holding is *already*
   in the registry under some `vNNN` (it usually is — `2_train.py`
   copies it).

So the Pin button is a dead button for ~50% of the entries in its own
sibling dropdown.

**Root cause**

Three independent pieces of friction:

1. **Hard rejection instead of resolution.** The regex at `viewer.js:1095`
   refuses anything that isn't a `model_registry/...` literal. But the
   `runs/detect/<run>/weights/best.pt` file is *byte-identical* to the
   `model_registry/<v>/best.pt` it was promoted into (`2_train.py:403` is
   `shutil.copy2`). A SHA-256 dedupe back to the registry would resolve
   the selection automatically.

2. **Always-enabled button.** The button is enabled even when the
   selected option doesn't match the regex. Standard "show the cliff
   before the user walks off it" miss — disable + tooltip would prevent
   the click in the first place.

3. **No promotion path.** Even if the regex resolution misses (run was
   killed pre-archive, weights were dropped in by hand), there is no
   "Register this run" button anywhere in the UI. The user has to know
   to call a CLI step (and there isn't a clean one — `2_train.py`
   handles archive at end-of-train but has no "register an existing
   run" subcommand). So the fallback when (1) and (2) miss is "drop to
   shell, hand-roll a directory and a SQL insert".

The "Pin only works for registry paths" hint at the bottom is honest
but tells a story about the *implementation*, not the *user goal*. It
should be telling the user how to make it work.

**Fix**

### a) Resolve runs/detect → registry by hash

In `flight_viewer.py`, after the existing `/api/training/pin` route,
add a small helper and have the pin route accept either a `version` or
a `path`:

```python
import hashlib

def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _registry_version_for_path(rel_path: str) -> str | None:
    """Return vNNN if the given .pt's contents match a registry entry."""
    src = (BASE / rel_path).resolve()
    if not src.is_file():
        return None
    src_hash = _sha256(src)
    reg_root = BASE / "model_registry"
    if not reg_root.is_dir():
        return None
    for vdir in sorted(reg_root.iterdir(), reverse=True):
        cand = vdir / "best.pt"
        if cand.is_file() and _sha256(cand) == src_hash:
            return vdir.name
    return None
```

Then `/api/training/pin` accepts `{path: "...", type: "ground"}` as
well as the existing `{version: "vNNN", ...}` shape:

```python
@app.route("/api/training/pin", methods=["POST"])
def api_training_pin():
    data     = request.get_json(force=True) or {}
    version  = data.get("version", "")
    path     = data.get("path", "")
    pin_type = data.get("type", "")
    if not version and path:
        version = _registry_version_for_path(path) or ""
        if not version:
            return jsonify({
                "error": "weights not in registry",
                "hint":  "click 'Register this run' to promote, then pin",
                "path":  path,
            }), 404
    # ... rest unchanged ...
```

Frontend (`viewer.js:1093-1116`) drops the regex and just posts the
selection straight:

```js
document.getElementById('pinGroundBtn')?.addEventListener('click', async () => {
    const v = modelSelect.value || '';
    const r = await fetch('/api/training/pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: v, type: 'ground' }),
    });
    const data = await r.json().catch(() => ({}));
    if (r.status === 404 && data.hint) {
        setStatus(data.hint, 'err');
        document.getElementById('registerRunBtn').style.display = '';
        return;
    }
    if (!r.ok || data.error) {
        setStatus(`Pin failed: ${data.error || r.statusText}`, 'err');
        return;
    }
    setStatus(`Pinned best ground → ${data.pinned.best_ground}`, 'ok');
    await loadModels();
});
```

This single change makes the button work for **every** weight that's
already represented in the registry (i.e. anything `2_train.py`
processed end-to-end), without touching the registry contract.

### b) Disable the button when it can't work

Pre-flight gate: when `modelSelect` changes, ask the server whether
the current selection has a registry equivalent and disable the button
if not:

```js
async function _refreshPinButton() {
    const btn = document.getElementById('pinGroundBtn');
    const sel = modelSelect.value || '';
    btn.disabled = true;
    btn.title = 'Resolving…';
    try {
        const r = await fetch(`/api/training/resolve?path=${encodeURIComponent(sel)}`);
        const d = await r.json();
        if (d.version) {
            btn.disabled = false;
            btn.title    = `Pin ${d.version} as best ground`;
        } else {
            btn.disabled = true;
            btn.title    = `Not in registry — promote first`;
        }
    } catch { btn.disabled = true; }
}
modelSelect.addEventListener('change', _refreshPinButton);
```

(`/api/training/resolve` is a 5-line wrapper around
`_registry_version_for_path`.) Combined with (a), the user now sees
greyed-out "Pin as ground" only when promotion is genuinely needed —
not when the dropdown happens to be holding a `runs/detect/*` path
that's already a registry duplicate.

### c) "Register this run" button for the genuine misses

For weights that aren't in the registry yet, add a sibling button next
to "Pin as ground". Hidden by default; shown when (a) returns 404 or
(b) detects no resolution:

```html
<button type="button" id="registerRunBtn" style="display:none; ...">
    Register this run
</button>
```

```js
document.getElementById('registerRunBtn').addEventListener('click', async () => {
    const v = modelSelect.value || '';
    const r = await fetch('/api/training/register_run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: v }),
    });
    const d = await r.json();
    if (!r.ok) { setStatus(`Register failed: ${d.error}`, 'err'); return; }
    setStatus(`Registered as ${d.version} — now pinning…`, 'ok');
    await loadModels();
    modelSelect.value = `model_registry/${d.version}/best.pt`;
    document.getElementById('pinGroundBtn').click();
});
```

`/api/training/register_run` does what `2_train.py:397-443` does, but
in retrofit form (no training run; just promote weights + add a row):

```python
@app.route("/api/training/register_run", methods=["POST"])
def api_training_register_run():
    data = request.get_json(force=True) or {}
    src = (BASE / data.get("path", "")).resolve()
    if not src.is_file() or src.suffix != ".pt":
        return jsonify({"error": "path must be a .pt file"}), 400

    # Check duplicate by hash first
    existing = _registry_version_for_path(str(src.relative_to(BASE)))
    if existing:
        return jsonify({"version": existing, "duplicate": True})

    # Mint next version
    reg_root = BASE / "model_registry"
    nums = [int(d.name[1:]) for d in reg_root.iterdir()
            if d.name.startswith("v") and d.name[1:].isdigit()]
    version = f"v{(max(nums) if nums else 0) + 1:03d}"
    vdir = reg_root / version
    vdir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(src, vdir / "best.pt")

    # Pull arch from filename, mAP from sibling results.csv if present
    arch = "unknown"
    name_low = src.parent.parent.name.lower()  # e.g. ball_yolo26x
    for fam in ("yolov8n","yolov8s","yolov8m","yolov8l","yolov8x",
                "yolo11n","yolo11s","yolo11m","yolo11l","yolo11x"):
        if fam in name_low:
            arch = fam; break

    # Insert minimal DB rows so the rest of the UI sees this version
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO training_runs (model_arch, source) VALUES (?, ?)",
            (arch, "register_run"))
        tr_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO models (version, training_run_id) VALUES (?, ?)",
            (version, tr_id))
        conn.commit(); conn.close()

    return jsonify({"version": version, "duplicate": False})
```

(Schema is best-effort — match whatever the user's `migrations.py`
declares for the `models` / `training_runs` tables; the column list
above is illustrative.)

### d) Cosmetic: stop the static "hint paragraph"

The italic red caption at the bottom of the panel
(`viewer/index.html` near the Save session button) is now redundant
once (a)+(b)+(c) land. Replace it with a `<span>` that's only shown
when (b) fails to resolve, alongside the "Register this run" button.
That removes the permanent "this UI is broken on purpose" sticker the
user is currently looking at.

After (a)+(b)+(c)+(d):

- 95% of clicks "just work" because the user's `runs/detect/...`
  selection is a hash-equivalent of an existing registry version.
- 5% of clicks (genuine new runs / hand-dropped weights) get a single
  follow-up button "Register this run" instead of a dead-end error.
- The button is greyed out *before* the user clicks when neither path
  is available.
- The static hint paragraph disappears.

This issue is a sub-symptom of the same root cause as Issue #7
(`/api/models` returns an unfiltered firehose with no resolution back
to the registry). When #7 lands and the dropdown defaults to a pinned
or registry version, this collision becomes much rarer — but
**not zero**, because the "Show `runs/detect` weights" checkbox keeps
the option live for power-users. So #13 still needs its own fix.

---

## 14. "Run hailortcli benchmark over SSH" hangs silently with no console view

**Where**

- `ai_skydock/dashboard_pages/evaluate.py:491-547` —
  `_run_remote_hailo_benchmark()` runs three blocking `subprocess.run`
  calls (`ssh mkdir`, `scp HEF`, `ssh hailortcli benchmark`) all
  inside a single `with st.spinner(...)` context.
- `ai_skydock/dashboard_pages/evaluate.py:419-488` —
  `_run_remote_video_benchmark()` has the same shape for the legacy
  GStreamer pipeline benchmark (3 blocking `subprocess.run` calls,
  ~5-minute timeout, no live output).

**Symptom (verbatim from the user)**

> Hailo-8 Benchmark (`hailortcli`)
>
> Pure-HW throughput. Use this number to optimise the compile step.
> Runs `hailortcli benchmark` over SSH against the .hef on the Pi.
>
> Time-to-run (seconds): 15
> Batch size: 8
>
> Running hailortcli benchmark on fred@rpi.local (15s @ batch 8) ...
>
> this just hangs also there is no console view

The spinner stays on for 60+ seconds (15s benchmark + scp + mkdir +
SSH handshake) with **zero output**. If `hailortcli` actually hangs on
the Pi (busy `/dev/hailo0`, firmware mismatch, lock contention) the
spinner stays for the whole `duration_s + 90` timeout (105 seconds for
default settings). The user has no way to tell which of these is
happening:

- SSH still authenticating
- `mkdir -p` running
- `scp` transferring the 100-150 MB `.hef`
- `hailortcli` waiting for device lock
- `hailortcli` running its 15-second loop
- The whole thing is dead and Streamlit will time out

And of course if anything else on the page is clicked mid-benchmark,
the Streamlit script reruns and the whole pipeline is killed (same
fragility as Issue #12).

**Root cause**

Same pattern as Issue #12, applied to a remote pipeline:

```python
with st.spinner(f"Running hailortcli benchmark on {target} "
                f"({duration_s}s @ batch {batch_size}) ..."):
    r = subprocess.run(SSH + [f"mkdir -p {shlex.quote(remote_base)}"],
                       capture_output=True, text=True, cwd=str(REPO))
    # ... if r.returncode != 0: ...
    r = subprocess.run(SCP + [str(bench_hef), f"{target}:{remote_hef}"],
                       capture_output=True, text=True, cwd=str(REPO))
    # ... if r.returncode != 0: ...
    cmd = (f"hailortcli benchmark --time-to-run {duration_s} ...")
    res = subprocess.run(SSH + [cmd], capture_output=True, text=True,
                         cwd=str(REPO),
                         timeout=duration_s + 90)
```

Three things compound:

1. **`capture_output=True`** — stdout/stderr buffered until exit. Even
   though `hailortcli` prints progress (`Starting measurement...`,
   `Iteration 1/15...`), none of it reaches the UI until the run is
   over (or the timeout fires).

2. **Sequential, opaque phases.** The spinner string says "Running
   hailortcli benchmark" but ~60 seconds of that is actually scp of
   the HEF and SSH startup. The user reads "15s @ batch 8" and expects
   a ~20s wait; gets ~75-90s and assumes it's hung.

3. **No persistence.** Streamlit rerun = pipeline killed. The
   `.compile.session` machinery proposed in Issue #12 doesn't exist
   yet for this button either.

Plus benchmark-specific failure modes nothing surfaces:

4. **`hailortcli` device-lock timeout.** If `/dev/hailo0` is held by
   the FSM runtime, `hailortcli` waits 30+ seconds before failing.
   That looks identical to a "hung" SSH connection from the dashboard.

5. **HEFs re-uploaded every click.** Even if the same HEF was scp'd 30
   seconds ago, the next click re-scps the whole 100+ MB file. There
   is no remote-hash check.

6. **No pre-flight.** A 1-second `hailortcli fw-control identify`
   would catch "device unreachable" / "wrong firmware" before
   committing to a multi-minute pipeline. It's not done.

**Fix**

### a) Ship the same persistence machinery as Issue #12

`_run_remote_hailo_benchmark()` should not call `subprocess.run`
in-thread. Spawn detached, write a log file, tail it. The exact
pattern from Issue #12's `(a)` step applies; the only differences are:

```python
# Phase markers in the log so the tail is informative
LOG_DIR.mkdir(exist_ok=True)
log_path = LOG_DIR / f"hailo_bench_{datetime.now():%Y%m%d_%H%M%S}.log"

script = REPO / "tools" / "run_hailo_benchmark.sh"   # new
proc = subprocess.Popen(
    ["bash", str(script),
     bench_user, bench_host, str(bench_hef), bench_version,
     str(duration_s), str(batch_size)],
    cwd=str(REPO),
    stdout=open(log_path, "wb"), stderr=subprocess.STDOUT,
    start_new_session=True,
)
session = {
    "pid": proc.pid, "log_path": str(log_path),
    "started_at": datetime.now(timezone.utc).isoformat(),
    "version": bench_version, "host": bench_host,
}
(REPO / ".hailo_bench.session").write_text(json.dumps(session))
st.success(f"Benchmark started (pid {proc.pid}). Tailing log below.")
st.rerun()
```

The new `tools/run_hailo_benchmark.sh` does the three SSH steps with
`set -x` + clearly-bracketed phase output:

```bash
#!/usr/bin/env bash
set -e
USER=$1; HOST=$2; HEF=$3; VERSION=$4; DURATION=$5; BATCH=$6
TARGET="${USER}@${HOST}"
REMOTE_HEF="/home/${USER}/ai_benchmarking_over_ssh/${VERSION}.hef"

echo "=== [$(date -Iseconds)] phase=preflight target=${TARGET}"
ssh -o ConnectTimeout=8 -o BatchMode=yes "${TARGET}" \
    "hailortcli fw-control identify" \
  || { echo "preflight failed: hailortcli not responsive"; exit 2; }

echo "=== [$(date -Iseconds)] phase=mkdir"
ssh "${TARGET}" "mkdir -p /home/${USER}/ai_benchmarking_over_ssh"

echo "=== [$(date -Iseconds)] phase=hash_local"
LOCAL_HASH=$(sha256sum "${HEF}" | awk '{print $1}')
echo "local sha256 ${LOCAL_HASH}"

echo "=== [$(date -Iseconds)] phase=hash_remote"
REMOTE_HASH=$(ssh "${TARGET}" \
    "[ -f ${REMOTE_HEF} ] && sha256sum ${REMOTE_HEF} | awk '{print \$1}'" || true)
echo "remote sha256 ${REMOTE_HASH:-<absent>}"

if [ "${LOCAL_HASH}" != "${REMOTE_HASH}" ]; then
    echo "=== [$(date -Iseconds)] phase=scp size=$(stat -c%s "${HEF}" | numfmt --to=iec)"
    rsync -avh --info=progress2 -e "ssh -o ConnectTimeout=8" \
          "${HEF}" "${TARGET}:${REMOTE_HEF}"
else
    echo "=== [$(date -Iseconds)] phase=scp_skipped (hash match)"
fi

echo "=== [$(date -Iseconds)] phase=benchmark duration=${DURATION}s batch=${BATCH}"
ssh "${TARGET}" \
    "hailortcli benchmark --time-to-run ${DURATION} \
                          --batch-size ${BATCH} ${REMOTE_HEF}"

echo "=== [$(date -Iseconds)] phase=done"
```

Tailing this log gives the user a stream like:

```
=== [...] phase=preflight target=fred@rpi.local
Identifying board
Control Protocol Version: 2
Firmware Version: 4.20.0 (release)
=== [...] phase=mkdir
=== [...] phase=hash_local
local sha256 7f3c…
=== [...] phase=hash_remote
remote sha256 7f3c…
=== [...] phase=scp_skipped (hash match)
=== [...] phase=benchmark duration=15s batch=8
Starting Measurement...
[==========================================>] 100%
…
```

— each phase clearly demarcated, with progress, and `phase=scp_skipped`
the second time the same HEF is benchmarked.

### b) Recovery on every render

Same shape as Issue #12's `(d)`. Before the form, check
`.hailo_bench.session`:

```python
session_path = REPO / ".hailo_bench.session"
if session_path.exists():
    s = json.loads(session_path.read_text())
    if _pid_alive(s.get("pid")):
        st.warning(f"🔒 Benchmark in progress on {s['host']} "
                   f"(pid {s['pid']}, version {s['version']})")
        st.code(_tail(Path(s["log_path"]), 100), language="text")
        cols = st.columns(3)
        if cols[0].button("Refresh"):
            st.rerun()
        if cols[1].button("Stop"):
            try: os.killpg(os.getpgid(s["pid"]), signal.SIGTERM)
            except Exception as e: st.error(f"Could not stop: {e}")
            st.rerun()
        return   # don't render the form while a benchmark is live
    else:
        # Process gone — show final tail + parse + clear session
        out_text = Path(s["log_path"]).read_text(errors="replace")
        st.code(out_text[-6000:], language="text")
        fps_map = parse_hailortcli_fps(out_text)
        if fps_map:
            _persist_hailo_fps(s["version"], s["host"], fps_map)
            st.success(f"Benchmark complete: {fps_map}")
        session_path.unlink(missing_ok=True)
```

Kills the "spinner forever" symptom: a dead/finished benchmark always
resolves on the next render.

### c) Phase-aware status messages

The current spinner string "Running hailortcli benchmark on
fred@rpi.local (15s @ batch 8) ..." lies for the first 30-60 seconds
(it's actually scp / mkdir / SSH handshake). Replace with the live tail
from (a). The `phase=` markers in the log are grep-friendly so the UI
can also do:

```python
phase = "preflight"
for line in tail_text.splitlines():
    if "phase=" in line:
        phase = line.split("phase=", 1)[1].split()[0]
st.caption(f"Phase: **{phase}**")
```

### d) Same fix for the legacy video benchmark — **and make it actually succeed**

`_run_remote_video_benchmark()` (lines 419-488) has the same shape, the
same fragility, and a 5-minute (`bench_video_timeout=300`) default
timeout. Same `tools/run_video_benchmark.sh` + detach + tail. Even
better here than for `hailortcli` because the video benchmark prints
GStreamer progress at 30 Hz — the live tail is genuinely useful for
debugging "is the pipeline stuck on a corrupt frame".

But (a)+(b)+(c) only makes the **UI** for the video benchmark work.
The benchmark itself is currently **measuring the wrong thing** for
several independent reasons. The default command template is:

```text
bash -lc 'cd ~/skydock2/hailo-rpi5-examples
        && source setup_env.sh
        && cd basic_pipelines
        && python3 detection.py --input "{video_path}"
                                --hef-path "{hef_path}"
        2>&1 | tee "{log_path}"'
```

with `bench_video_path = /home/fred/skydock2/benchmark/input.mp4`. The
upstream pipeline is `hailo_apps...GStreamerDetectionApp` driving the
example callback in `hailo-rpi5-examples/basic_pipelines/detection.py`.

Each of the following is sufficient on its own to make the resulting
"FPS" number meaningless:

1. **Wall-clock pacing on the videosink (THE biggest one).** Default
   GStreamer videosinks have `sync=true`. A 30 FPS source video plays
   at 30 FPS no matter how fast the Hailo can run. The "video stream
   benchmark" therefore reports ~29-30 FPS for *every* model, big or
   small, because the bottleneck is the file's frame rate, not the
   accelerator. Need either:
   - source caps `framerate=0/1` + `sync=false` on the sink, OR
   - `--frame-rate 0` (the upstream basic_pipelines support this), OR
   - swap `videosink` for `fakesink sync=false`.

2. **`--show-fps` is not passed.** Without it the upstream
   `GStreamerDetectionApp` doesn't print FPS at all. Then
   `parse_fps_from_text()` falls through to a loose regex that
   matches *any* "fps"-shaped string in GStreamer's verbose log:
   negotiated source caps `framerate=30/1`, fallback rates from
   element introspection, etc. The number it returns is whatever
   matched first, not the pipeline throughput.

3. **`DISPLAY` may be inherited.** When SSHing into `fred@rpi.local`
   with X-forwarding (`-X`) or with `DISPLAY` set in the user's login
   shell, GStreamer tries to render to that display. If the display is
   slow / unreachable, the pipeline hangs or back-pressures and the
   FPS collapses. Fix: explicit `env -u DISPLAY` (and
   `export GST_VIDEO_SINK=fakesink`) at the top of the remote command.

4. **No video-file existence check.** If `/home/fred/skydock2/
   benchmark/input.mp4` does not exist on the Pi, GStreamer's
   `filesrc` either errors out late or stalls during pad linking. The
   user just sees the existing "this hangs" symptom. Pre-flight:
   `ssh ... 'test -s {video_path}'` and abort with a clear message if
   the file is missing or zero-bytes.

5. **`labels_path` is scp'd but never consumed.** The default command
   template doesn't pass `--labels-path` (the upstream `detection.py`
   doesn't accept one anyway — labels come from the HEF post-process
   metadata). Wasted ~100 KB transfer per run, plus the
   `if not labels_local.exists()` guard in lines 426-427 blocks the
   benchmark for every model that doesn't ship `ball_labels.json`.
   Either drop the labels scp+guard entirely, or only do it when the
   command template literally contains `{labels_path}`.

6. **Result clobbers the canonical hailortcli number.** Lines 481-485:
   ```python
   conn.execute(
       "UPDATE models SET fps_rpi_hailo8=?, fps_measured_at=?, "
       "fps_measured_host=? WHERE version=?", ...)
   ```
   Both benchmarks write to **the same column** `fps_rpi_hailo8`. Per
   `migrations.py:23-25`, that column is documented as "streaming FPS
   (HW + DMA + RPi overhead)" — i.e. exactly what
   `parse_hailortcli_fps()['streaming']` produces. The hailortcli
   value is the trustworthy one (real Hailo runtime, no GStreamer
   pipeline overhead, no parsing ambiguity); the video benchmark
   should not be allowed to overwrite it. Two clean options:
   - Add a separate `fps_pipeline REAL` column in `migrations.py` and
     have the video benchmark write *only* there. Display both side
     by side on the History card.
   - Drop the legacy video benchmark entirely. The "Video Stream
     Benchmark (legacy)" subheading and the *prefer the hailortcli
     path above* caption already signal it's deprecated; if it can't
     produce an honest pipeline-FPS number after fixing 1-5, the
     simplest answer is to remove the button and the function.

7. **`bash -lc` over non-interactive SSH is fragile.** `setup_env.sh`
   may rely on dotfile-installed env (e.g. ROCm/Hailo paths exported
   by `~/.bashrc`); under a non-interactive SSH session those are not
   sourced. Replace `bash -lc` with `bash -c` and source the env file
   explicitly: `source /opt/hailo/hailort.env || true; source
   ~/skydock2/hailo-rpi5-examples/setup_env.sh`. Or just hardcode the
   exact env exports inside `tools/run_video_benchmark.sh` so the
   benchmark is reproducible irrespective of dotfiles.

Concrete remote-side script that addresses 1-7 (paired with the
detached/persistence machinery from (a)+(b)+(c)):

```bash
#!/usr/bin/env bash
# tools/run_video_benchmark.sh
set -e
USER=$1; HOST=$2; HEF=$3; VERSION=$4; VIDEO=$5; DURATION=$6
TARGET="${USER}@${HOST}"
REMOTE_HEF="/home/${USER}/ai_benchmarking_over_ssh/${VERSION}.hef"

echo "=== [$(date -Iseconds)] phase=preflight"
ssh -o BatchMode=yes "${TARGET}" "test -s ${VIDEO}" \
  || { echo "preflight failed: video missing or empty: ${VIDEO}"; exit 2; }
ssh "${TARGET}" "test -d ~/skydock2/hailo-rpi5-examples/basic_pipelines" \
  || { echo "preflight failed: hailo-rpi5-examples not on Pi"; exit 2; }

echo "=== [$(date -Iseconds)] phase=hash_local"
LOCAL_HASH=$(sha256sum "${HEF}" | awk '{print $1}')
REMOTE_HASH=$(ssh "${TARGET}" \
    "[ -f ${REMOTE_HEF} ] && sha256sum ${REMOTE_HEF} | awk '{print \$1}'" || true)
if [ "${LOCAL_HASH}" != "${REMOTE_HASH}" ]; then
    echo "=== [$(date -Iseconds)] phase=scp"
    rsync -avh --info=progress2 "${HEF}" "${TARGET}:${REMOTE_HEF}"
fi

echo "=== [$(date -Iseconds)] phase=run duration=${DURATION}s"
ssh "${TARGET}" bash -s <<EOF
set -e
unset DISPLAY
export GST_VIDEO_SINK=fakesink
cd ~/skydock2/hailo-rpi5-examples
source setup_env.sh
cd basic_pipelines
timeout ${DURATION} python3 -u detection.py \
    --input "${VIDEO}" \
    --hef-path "${REMOTE_HEF}" \
    --frame-rate 0 \
    --show-fps
EOF
echo "=== [$(date -Iseconds)] phase=done"
```

Plus, in `_persist_video_fps()` (or wherever the result lands), write
to a new `fps_pipeline REAL` column instead of clobbering
`fps_rpi_hailo8`. Add the column in `migrations.py` and surface it on
the History card next to the existing "FPS / hw_only" pair (so each
model has three numbers: pipeline / streaming / hw_only).

After 1-7: the legacy video benchmark stops being a coin-flip number
in a column owned by hailortcli, starts producing an honest
"full-pipeline FPS" measurement (which IS useful — it captures the
GStreamer overhead the FSM actually pays at runtime), and surfaces
its progress live so the user can see it's measuring 200 Hz instead
of 30 Hz on a yolo11n HEF. That makes it complementary to
`hailortcli`, not redundant.

### e) Pre-flight cuts most of the "hangs"

The `hailortcli fw-control identify` step in (a) takes <1 second when
healthy, fails in <8 seconds when the firmware is unreachable, and
covers the most common cause of a "hung" benchmark: `hailortcli` is
waiting for the FSM runtime to release `/dev/hailo0`. Even just
surfacing that as a fast-fail with a clear message saves the user from
the 30-second device-lock timeout downstream.

After (a)+(b)+(c)+(d): the user sees live SSH/scp/hailortcli output
in-page within 1 second of clicking, can stop a misbehaving run with a
button, and Streamlit reruns no longer kill an in-flight benchmark.
The "this just hangs" symptom becomes "ah, it's stuck on
`phase=benchmark` because of `device busy`" — the diagnosis is the
output, not the absence of it.

This is the same machinery as Issues #12 (compile) and is itself a
specific instance of a broader pattern flagged in Issue #10: every
long-running operation in the dashboard re-implements
`subprocess.run + spinner` instead of using a shared
`run_in_background(name, argv)` helper. The right end-state is one
helper in `dashboard_lib.py`:

```python
def run_in_background(name: str, argv: list[str]) -> int:
    """Spawn detached. Returns pid. Logs to logs/<name>_<ts>.log,
    session sidecar at REPO / f'.{name}.session'."""
```

— and every "go" button in the codebase calls it. That refactor is
implied by #10, #12, and #14 collectively; doing it once instead of
three times is the win.

---

## Suggested order of attack

1. **Pull fix** (#1) — small, unblocks faster iteration on everything else.
   You need cheap re-pulls to debug the others.
2. **Auto-label button** (#2) in `data.py` — 30 minutes; removes the manual
   CLI step.
3. **Train launcher** (#4b) — give the Train tab any way to start a run.
4. **Train dataset picker** (#4) — once you can launch, you can mix in
   hat-negatives.
5. **Hailo NMS layer-name discovery** (#3) — unblocks `yolov8l.hef` /
   `yolov8x.hef`.
6. **Real Hailo FPS via `hailortcli`** (#5) — wire into deploy, kill the
   stale number.
7. **Metric glossary on Evaluate** (#6) — 30 minutes; cosmetic but the only
   item a non-ML team-mate would notice immediately.
8. **Pin best ground in Flight Viewer dropdown** (#7) — group + default to
   pinned, hide the runs/detect flood. Cheap and stops you mis-selecting a
   stale checkpoint when auto-labelling new flights.
9. **NMS dedup in Flight Viewer** (#8) — one-line change to `model.predict`
   + 15-line client dedup. Has to land **before** the next big auto-label
   pass, otherwise the duplicate boxes get baked into staging labels and
   poison the next training run.
10. **Staging visibility + class-id remap + clobber guard** (#9 a/b/d) —
    same-day fix. Without this every "Copy approved → staging" from the
    Flight Viewer is silently broken when the model is anything other
    than a single-class Ball model. Land this *before* you tell anyone
    else to use the flow.
11. **Shared `run_in_background()` helper + persistence** (#12 + #14) —
    1 day. One helper in `dashboard_lib.py`, then port: compile button
    + rsync push (#12), hailortcli benchmark (#14), legacy video
    benchmark (#14d). Each "go" button gains live tail, Stop button,
    and recovery on Streamlit restart. Cheaper to do once for all
    three than three times. Pulls in the existing `_tail()` /
    `_running()` helpers from `train.py`.
12. **Pin-button hash-resolution + Register run** (#13) — half a day.
    Stops the dead-button experience for `runs/detect/*` selections
    and gives users a single-click promotion path. Plays nicely with
    #7 once it lands but is needed independently because
    "Show `runs/detect` weights" stays available for power-users.
13. **Finetune-from arch filter + arch override guard** (#11) — half a
    day. Cuts the worst silent-misuse failure (you think you trained
    yolo11n, you actually didn't). Lands cleanly into the existing
    `train.py` form — no architectural changes needed. Should land
    before the next retrain attempt.
14. **Flight-Viewer/Streamlit integration polish** (#10 Option A) — 1 day.
    Inject shared CSS, drop the hardcoded `:8501`, embed-mode the iframe,
    propagate flight selection via `postMessage`. Won't fix everything
    but kills the "feels like two apps" reflex and makes every later UI
    fix land in one consistent shell.
15. **Multi-batch staging + per-flight/fresh ingest modes** (#9c) —
    bigger refactor. Unlocks running A/B datasets (control vs. with-hats)
    and per-flight regression sets, which are the things you actually
    need to debug the white-hat misclassification.
16. **Multi-class retrain with hat negatives** — once 1-15 are in, retrain
    v0XX and deploy.
17. **Decide on long-term shell architecture** (#10 Option B vs C) —
    medium-term. Punt until retrain pipeline is healthy; revisit when
    the next major UI feature is being designed.
