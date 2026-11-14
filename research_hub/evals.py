"""Per-sample evaluation results for any task: classification, regression, masks and heatmaps as layers, boxes,
text. Sample facts (any key/value the caller sends) are stored once per eval set and shared by every run on it."""

from __future__ import annotations

import base64
import json
import re

from .core import Conflict, HubError, NotFound, choice, now, number, rows

EVAL_SET = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}@[A-Za-z0-9._-]{1,40}(?::[a-z0-9._-]{1,40})?")
LAYER = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
FACT_KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")
OUTCOMES = ("correct", "missed", "false_alarm", "wrong_class", "mismatch", "unscored")
NEGATIVES = {"negative", "background", "normal", "none", "ok", "good", "healthy"}  # compared lowercased
LAYER_KINDS = ("image", "audio", "mask", "heatmap")
STATIC_STEP = -1  # layers that never change with training: the input image/audio and ground-truth masks
MAX_ROWS = 5000


def outcome_for(truth: dict, pred: dict, negatives) -> str:
    """What happened on this sample, derived from whatever the task produced."""
    if truth.get("boxes") is not None or pred.get("boxes") is not None:
        tp, fp, fn = match_boxes(truth.get("boxes") or [], pred.get("boxes") or [])
        if fn and not tp:
            return "missed"
        if fp and not fn and not truth.get("boxes"):
            return "false_alarm"
        return "correct" if not fn and not fp else "wrong_class"
    t, p = truth.get("class"), pred.get("class")
    if t and p:
        if t == p:
            return "correct"
        if p.lower() in negatives:
            return "missed"
        if t.lower() in negatives:
            return "false_alarm"
        return "wrong_class"
    if truth.get("text") is not None and pred.get("text") is not None:
        return "correct" if _norm(truth["text"]) == _norm(pred["text"]) else "mismatch"
    return "unscored"


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def match_boxes(truth: list, pred: list, iou_min=0.5):
    """Greedy IoU matching of [x, y, w, h, label, score?] boxes with the same label."""
    used, tp = set(), 0
    for t in truth:
        best, best_j = 0.0, None
        for j, p in enumerate(pred):
            if j in used or (len(t) > 4 and len(p) > 4 and t[4] != p[4]):
                continue
            v = _iou(t, p)
            if v > best:
                best, best_j = v, j
        if best >= iou_min:
            used.add(best_j)
            tp += 1
    return tp, len(pred) - tp, len(truth) - tp


def _iou(a, b) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax2, bx2) - max(a[0], b[0])), max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _boxes(value, what):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 500:
        raise HubError(f"{what} must be a list of at most 500 boxes [x, y, w, h, label?, score?]")
    out = []
    for b in value:
        if not isinstance(b, list) or len(b) < 4:
            raise HubError(f"{what}: each box is [x, y, w, h, label?, score?], got {b!r}")
        box = [float(v) for v in b[:4]] + [str(b[4])] if len(b) > 4 else [float(v) for v in b[:4]]
        if len(b) > 5:
            box.append(float(b[5]))
        out.append(box)
    return out


def normalise_row(r: dict) -> dict:
    """Validate one {sample, facts, true, pred, …} row. Layers come back as {name: (blob sha, kind)}.

    A null removes what was logged before: a fact, or a mask or heatmap (its blob sha comes back as None)."""
    if not isinstance(r, dict):
        raise HubError("each row must be an object")
    sample = str(r.get("sample") or "").strip()[:300]
    if not sample:
        raise HubError("every row needs `sample`: a stable id such as the dataset image id")
    sent = {str(k): v for k, v in (r.get("facts") or {}).items()}
    facts = {k: str(v) for k, v in sent.items() if v not in (None, "")}
    for k in sent:
        if not FACT_KEY.fullmatch(k):
            raise HubError(f"{sample}: fact key {k!r} must be lowercase letters, digits or _")
    truth = dict(r.get("true") or {})
    pred = dict(r.get("pred") or {})
    for side, name in ((truth, "true"), (pred, "pred")):
        if side.get("class") is not None:
            side["class"] = str(side["class"])[:200]
        for k in ("value", "score"):
            if k in side:
                side[k] = number(side[k], f"{name}.{k}")
        side["boxes"] = _boxes(side.get("boxes"), f"{name}.boxes")
        if side["boxes"] is None:
            side.pop("boxes")
        if side.get("text") is not None:
            side["text"] = str(side["text"])[:20000]
    layers = {}  # blob ids uploaded beforehand, keyed by layer name
    for name, sha in (truth.pop("masks", None) or {}).items():
        layers[f"{name}_gt"] = (sha, "mask")
    for name, sha in (pred.pop("masks", None) or {}).items():
        layers[str(name)] = (sha, "mask")
    for name, sha in (pred.pop("heatmaps", None) or {}).items():
        layers[str(name)] = (sha, "heatmap")
    for key in ("image", "audio"):
        if r.get(key):
            layers[key] = (r[key], key)
    metrics, meta = r.get("metrics") or {}, r.get("meta") or {}
    if not isinstance(metrics, dict) or not isinstance(meta, dict):
        raise HubError(f"{sample}: metrics and meta must be objects")
    if r.get("size") is not None:  # the image's own size. It is stored shrunk, so pixel boxes become fractions of it
        size = r["size"]
        if not isinstance(size, list) or len(size) != 2 or not all(type(v) in (int, float) and 1 <= v <= 1e6 for v in size):
            raise HubError(f"{sample}: size is the image's [width, height] in pixels")
        meta = {**meta, "size": [round(v) for v in size]}
        for side in (truth, pred):
            if "boxes" in side:
                side["boxes"] = [b if all(v <= 1 for v in b[:4]) else
                                 [round(v / size[i % 2], 6) for i, v in enumerate(b[:4])] + b[4:] for b in side["boxes"]]
    error = number(r.get("error"), "error")
    if error is None:
        if truth.get("value") is not None and pred.get("value") is not None:
            error = abs(truth["value"] - pred["value"])
    outcome = r.get("outcome")
    if outcome:
        choice(outcome, OUTCOMES, "outcome")
    return {"sample": sample, "facts": facts, "drop_facts": [k for k, v in sent.items() if v is None], "truth": truth, "pred": pred, "layers": layers, "metrics": metrics,
            "meta": meta, "error": error, "outcome": outcome}


class Evals:
    # ------------------------------------------------------------------ blobs
    def put_blobs(self, files: list) -> list[str]:
        if not isinstance(files, list) or not files or len(files) > 500:
            raise HubError("files must be a list of 1-500 base64 strings")
        out = []
        for data_b64 in files:
            try:
                out.append(self.db.put_blob(base64.b64decode(data_b64, validate=True)))
            except (ValueError, TypeError) as e:
                raise HubError(f"bad file: {e}") from None
        return out

    def missing_blobs(self, shas: list) -> list[str]:
        if not isinstance(shas, list) or len(shas) > 20000:
            raise HubError("shas must be a list of at most 20000 sha256 ids")
        return [s for s in shas if not self.db.has_blob(str(s))]

    def _set_id(self, conn, project, name, create=False) -> int:
        if not isinstance(name, str) or not EVAL_SET.fullmatch(name):
            raise HubError("eval set must be a dataset reference name@version with an optional split, "
                           "e.g. coco@2017:val or my_dataset@1.2.0")
        if create:
            conn.execute("INSERT OR IGNORE INTO eval_sets(project, name, created) VALUES(?,?,?)", (project, name, now()))
        row = conn.execute("SELECT id FROM eval_sets WHERE project=? AND name=?", (project, name)).fetchone()
        if not row:
            raise NotFound(f"eval set {name!r} has no results in {project}")
        return row[0]

    # ---------------------------------------------------------------- logging
    def log_eval(self, actor, run_slug, eval_set, step, raw_rows, epoch=None, negatives=None) -> dict:
        try:
            step = int(step)
        except (TypeError, ValueError):
            raise HubError("step must be an integer") from None
        if step < 0:
            raise HubError("step must be >= 0")
        epoch = None if epoch in (None, "") else int(epoch)
        if not isinstance(raw_rows, list) or not raw_rows or len(raw_rows) > MAX_ROWS:
            raise HubError(f"rows must be a list of 1-{MAX_ROWS} samples; send larger sets in chunks")
        negatives = {str(n).lower() for n in negatives} if negatives else NEGATIVES
        parsed = [normalise_row(r) for r in raw_rows]
        for row in parsed:
            for name, (sha, _) in row["layers"].items():
                if not LAYER.fullmatch(name):
                    raise HubError(f"{row['sample']}: layer name {name!r} must be lowercase letters, digits, _ or -")
                if sha is not None and not self.db.has_blob(str(sha)):
                    raise HubError(f"{row['sample']}: layer {name} refers to blob {str(sha)[:12]}… which was not uploaded")
        counts: dict[str, int] = {}
        sample_changed = truth_layers = False
        with self.connect(write=True) as conn:
            run = self._writable(conn, actor, run_slug, allow_closed=True)
            set_id = self._set_id(conn, run["project"], eval_set, create=True)
            for row in parsed:
                item, truth_prev, changed = self._upsert_item(conn, set_id, row)
                sample_changed |= changed
                truth = {**truth_prev, **row["truth"]}
                if truth_prev.get("class") and row["truth"].get("class") and truth_prev["class"] != row["truth"]["class"]:
                    raise Conflict(f"{row['sample']} in {eval_set} is already labelled {truth_prev['class']!r}, not "
                                   f"{row['truth']['class']!r}; a relabelled dataset is a new version")
                prev = conn.execute("SELECT epoch, pred, score, error, metrics, outcome FROM eval_results WHERE run=? "
                                    "AND set_id=? AND step=? AND item=?", (run_slug, set_id, step, item)).fetchone()
                pred, error, metrics, outcome = row["pred"], row["error"], row["metrics"], row["outcome"]
                if prev is not None:  # fields sent overwrite; fields left out keep their logged values
                    pred = {**json.loads(prev["pred"]), **pred}
                    error = prev["error"] if error is None else error
                    metrics = {**json.loads(prev["metrics"]), **metrics}
                    epoch = prev["epoch"] if epoch is None else epoch
                if pred.get("boxes") is not None or truth.get("boxes") is not None:
                    tp, fp, fn = match_boxes(truth.get("boxes") or [], pred.get("boxes") or [])
                    metrics.update({"tp": tp, "fp": fp, "fn": fn})
                    if error is None:
                        error = float(fp + fn)
                outcome = outcome or outcome_for(truth, pred, negatives)
                counts[outcome] = counts.get(outcome, 0) + 1
                conn.execute(
                    "INSERT OR REPLACE INTO eval_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_slug, set_id, step, item, epoch, json.dumps(truth), json.dumps(pred), truth.get("class") or "",
                     pred.get("class") or "", truth.get("value"), pred.get("value"), pred.get("score"), error, outcome, json.dumps(metrics)))
                for name, (sha, kind) in row["layers"].items():
                    layer_step = STATIC_STEP if name in ("image", "audio") or name.endswith("_gt") else step
                    truth_layers |= name.endswith("_gt")
                    if sha is None:
                        conn.execute("DELETE FROM eval_layers WHERE run=? AND set_id=? AND step=? AND item=? AND layer=?",
                                     (run_slug, set_id, layer_step, item, name))
                        continue
                    conn.execute("INSERT OR REPLACE INTO eval_layers VALUES(?,?,?,?,?,?,?)",
                                 (run_slug, set_id, layer_step, item, name, sha, kind))
            self._note_eval_write(conn, run_slug, set_id, step, epoch, sample_changed, truth_layers)
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (now(), run_slug))
            self._event(conn, actor["name"], "eval.log", f"run:{run_slug}",
                        f"{len(parsed)} samples of {eval_set} at step {step}", run["project"])
        return {"logged": len(parsed), "set": eval_set, "step": step, "outcomes": counts}

    def _upsert_item(self, conn, set_id, row) -> tuple[int, dict, bool]:
        """Create or extend the shared sample facts; returns (item id, previously stored truth, whether the sample
        or one of its facts changed). Rows are written only when something changed."""
        existing = conn.execute("SELECT id, meta FROM eval_items WHERE set_id=? AND sample=?",
                                (set_id, row["sample"])).fetchone()
        truth_keep = {k: v for k, v in row["truth"].items() if k != "boxes" or v}
        image = row["layers"].get("image", (None,))[0]  # the same file for every run: kept on the sample
        if existing is None:
            meta = {"truth": truth_keep, **row["meta"], **({"image": image} if image else {})}
            item = conn.execute("INSERT INTO eval_items(set_id, sample, meta) VALUES(?,?,?)",
                                (set_id, row["sample"], json.dumps(meta))).lastrowid
            prev, changed = {}, True
        else:
            item, stored = existing["id"], json.loads(existing["meta"])
            prev = stored.get("truth", {})
            meta = {**stored, "truth": {**prev, **truth_keep}}
            if row["truth"].get("boxes") == []:  # an empty list says the sample has no boxes: forget the stored ones
                meta["truth"].pop("boxes", None)
            meta.update(row["meta"])
            if image:
                meta["image"] = image
            changed = meta != stored
            if changed:
                conn.execute("UPDATE eval_items SET meta=? WHERE id=?", (json.dumps(meta), item))
        for k in row["drop_facts"]:
            changed |= conn.execute("DELETE FROM eval_facts WHERE item=? AND key=?", (item, k)).rowcount > 0
        for k, v in row["facts"].items():
            changed |= conn.execute("INSERT OR IGNORE INTO eval_facts VALUES(?,?,?)", (item, k, v[:200])).rowcount > 0
        return item, prev, changed

    def _note_eval_write(self, conn, run_slug, set_id, step, epoch, sample_changed, truth_layers):
        """Inside the write: refresh the checkpoint's counts and raise its version, and the set's when a sample changed.
        A ground-truth layer shows at every checkpoint of the run, so writing one raises them all."""
        count, wrong = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(outcome NOT IN ('correct','unscored')), 0) FROM eval_results "
            "WHERE run=? AND set_id=? AND step=?", (run_slug, set_id, step)).fetchone()
        layered = conn.execute("SELECT COUNT(DISTINCT item) FROM eval_layers WHERE run=? AND set_id=? AND step=?",
                               (run_slug, set_id, step)).fetchone()[0]
        conn.execute(
            "INSERT INTO eval_columns(run, set_id, step, epoch, rows, wrong, layered, version, logged) "
            "VALUES(?,?,?,?,?,?,?,1,?) ON CONFLICT(run, set_id, step) DO UPDATE SET epoch=COALESCE(excluded.epoch, epoch), "
            "rows=excluded.rows, wrong=excluded.wrong, layered=excluded.layered, version=version+1, logged=excluded.logged",
            (run_slug, set_id, step, epoch, count, wrong, layered, now()))
        if truth_layers:
            conn.execute("UPDATE eval_columns SET version=version+1 WHERE run=? AND set_id=? AND step!=?",
                         (run_slug, set_id, step))
        if sample_changed:
            conn.execute("INSERT INTO eval_set_versions VALUES(?,1) ON CONFLICT(set_id) DO UPDATE SET version=version+1",
                         (set_id,))

    # ---------------------------------------------------------------- reading
    def _eval_index(self, conn, run_slug) -> list[dict]:
        sets: dict[str, dict] = {}
        for r in conn.execute("SELECT s.name, c.step, c.epoch, c.rows, c.wrong, c.layered FROM eval_columns c "
                              "JOIN eval_sets s ON s.id=c.set_id WHERE c.run=? ORDER BY s.name, c.step", (run_slug,)):
            sets.setdefault(r["name"], {"set": r["name"], "steps": []})["steps"].append(
                {"step": r["step"], "epoch": r["epoch"], "samples": r["rows"], "wrong": r["wrong"], "layered": r["layered"]})
        return list(sets.values())

    def _step_or_latest(self, conn, run_slug, set_id, step):
        if step not in (None, ""):
            return int(step)
        row = conn.execute("SELECT MAX(step) FROM eval_results WHERE run=? AND set_id=?", (run_slug, set_id)).fetchone()
        if row[0] is None:
            raise NotFound(f"run {run_slug} has no results for this eval set")
        return row[0]

    def _layers_for(self, conn, run_slug, set_id, items, step) -> dict:
        out: dict[int, dict] = {i: {} for i in items}
        if items:
            marks = ",".join("?" * len(items))
            for r in conn.execute(f"SELECT item, step, layer, blob_sha FROM eval_layers WHERE run=? AND set_id=? "
                                  f"AND item IN ({marks}) AND step IN (?, ?) ORDER BY step",
                                  (run_slug, set_id, *items, STATIC_STEP, step)):
                out[r["item"]][r["layer"]] = r["blob_sha"]
        return out

    @staticmethod
    def _layer_kinds(conn, run_slug, set_id) -> dict:
        """{layer name: mask|heatmap} for the overlays this run logged on this eval set."""
        return {r[0]: r[1] for r in conn.execute(
            "SELECT DISTINCT layer, kind FROM eval_layers WHERE run=? AND set_id=? AND kind IN ('mask','heatmap') "
            "ORDER BY layer", (run_slug, set_id))}

    def _facts_for(self, conn, items) -> dict:
        out: dict[int, dict] = {i: {} for i in items}
        if items:
            marks = ",".join("?" * len(items))
            for r in conn.execute(f"SELECT item, key, value FROM eval_facts WHERE item IN ({marks})", items):
                out[r["item"]][r["key"]] = r["value"]
        return out

    @staticmethod
    def _decode(r: dict) -> dict:
        for k in ("truth", "pred", "metrics"):
            r[k] = json.loads(r[k]) if r.get(k) else {}
        return r

    def eval_sample(self, run_slug, eval_set, sample) -> dict:
        """One sample across every checkpoint of a run: facts, truth, predictions and layers per step."""
        with self.connect() as conn:
            run = self._load_run(conn, run_slug)
            set_id = self._set_id(conn, run["project"], eval_set)
            item = conn.execute("SELECT * FROM eval_items WHERE set_id=? AND sample=?", (set_id, sample)).fetchone()
            if not item:
                raise NotFound(f"{sample} is not in {eval_set}")
            meta = json.loads(item["meta"])
            out = {"sample": item["sample"], "facts": self._facts_for(conn, [item["id"]])[item["id"]],
                   "truth": meta.pop("truth", {}), "meta": meta,
                   "layer_kinds": self._layer_kinds(conn, run_slug, set_id)}
            out["steps"] = [self._decode(r) for r in rows(conn.execute(
                "SELECT step, epoch, truth, pred, class_pred, value_pred, score, outcome, error, metrics FROM eval_results "
                "WHERE run=? AND item=? AND set_id=? ORDER BY step", (run_slug, item["id"], set_id)))]
            layers: dict[int, dict] = {}
            for r in conn.execute("SELECT step, layer, blob_sha FROM eval_layers WHERE run=? AND set_id=? AND item=?",
                                  (run_slug, set_id, item["id"])):
                layers.setdefault(r["step"], {})[r["layer"]] = r["blob_sha"]
            out["static_layers"] = layers.pop(STATIC_STEP, {})
            for s in out["steps"]:
                s["layers"] = layers.get(s["step"], {})
            return out
