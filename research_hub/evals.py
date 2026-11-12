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
SORTS = {"error": "r.error DESC", "score": "r.score DESC", "value": "r.value_true DESC",
         "value_pred": "r.value_pred DESC", "sample": "i.sample ASC"}


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
        with self.connect(write=True) as conn:
            run = self._writable(conn, actor, run_slug, allow_closed=True)
            set_id = self._set_id(conn, run["project"], eval_set, create=True)
            for row in parsed:
                item, truth_prev = self._upsert_item(conn, set_id, row)
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
                    if sha is None:
                        conn.execute("DELETE FROM eval_layers WHERE run=? AND set_id=? AND step=? AND item=? AND layer=?",
                                     (run_slug, set_id, layer_step, item, name))
                        continue
                    conn.execute("INSERT OR REPLACE INTO eval_layers VALUES(?,?,?,?,?,?,?)",
                                 (run_slug, set_id, layer_step, item, name, sha, kind))
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (now(), run_slug))
            self._event(conn, actor["name"], "eval.log", f"run:{run_slug}",
                        f"{len(parsed)} samples of {eval_set} at step {step}", run["project"])
        return {"logged": len(parsed), "set": eval_set, "step": step, "outcomes": counts}

    def _upsert_item(self, conn, set_id, row) -> tuple[int, dict]:
        """Create or extend the shared sample facts; returns (item id, previously stored truth)."""
        existing = conn.execute("SELECT id, meta FROM eval_items WHERE set_id=? AND sample=?",
                                (set_id, row["sample"])).fetchone()
        truth_keep = {k: v for k, v in row["truth"].items() if k != "boxes" or v}
        if existing is None:
            item = conn.execute("INSERT INTO eval_items(set_id, sample, meta) VALUES(?,?,?)",
                                (set_id, row["sample"], json.dumps({"truth": truth_keep, **row["meta"]}))).lastrowid
            prev = {}
        else:
            item = existing["id"]
            meta = json.loads(existing["meta"])
            prev = meta.get("truth", {})
            meta["truth"] = {**prev, **truth_keep}
            if row["truth"].get("boxes") == []:  # an empty list says the sample has no boxes: forget the stored ones
                meta["truth"].pop("boxes", None)
            meta.update(row["meta"])
            conn.execute("UPDATE eval_items SET meta=? WHERE id=?", (json.dumps(meta), item))
        for k in row["drop_facts"]:
            conn.execute("DELETE FROM eval_facts WHERE item=? AND key=?", (item, k))
        for k, v in row["facts"].items():
            conn.execute("INSERT OR IGNORE INTO eval_facts VALUES(?,?,?)", (item, k, v[:200]))
        return item, prev

    # ---------------------------------------------------------------- reading
    def _eval_index(self, conn, run_slug) -> list[dict]:
        sets: dict[str, dict] = {}
        for r in conn.execute(
                "SELECT s.name, r.step, MAX(r.epoch) AS epoch, COUNT(*) AS n, "
                "SUM(r.outcome NOT IN ('correct','unscored')) AS wrong FROM eval_results r JOIN eval_sets s ON s.id=r.set_id "
                "WHERE r.run=? GROUP BY s.name, r.step ORDER BY s.name, r.step", (run_slug,)):
            sets.setdefault(r["name"], {"set": r["name"], "steps": []})["steps"].append(
                {"step": r["step"], "epoch": r["epoch"], "samples": r["n"], "wrong": r["wrong"], "layered": 0})
        if sets:
            layered = {(r[0], r[1]): r[2] for r in conn.execute(
                "SELECT s.name, l.step, COUNT(DISTINCT l.item) FROM eval_layers l JOIN eval_sets s ON s.id=l.set_id "
                "WHERE l.run=? AND l.step>=0 GROUP BY s.name, l.step", (run_slug,))}
            for s in sets.values():
                for st in s["steps"]:
                    st["layered"] = layered.get((s["set"], st["step"]), 0)
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

    def eval_query(self, run_slug, eval_set, step=None, filters=None, sort="error", limit=24, offset=0) -> dict:
        """One page of samples at a checkpoint, filtered by facts, classes, outcome, value range, other runs."""
        f = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
        with self.connect() as conn:
            run = self._load_run(conn, run_slug)
            set_id = self._set_id(conn, run["project"], eval_set)
            step = self._step_or_latest(conn, run_slug, set_id, step)
            joins, join_args = ["JOIN eval_items i ON i.id=r.item"], []
            where, args = ["r.run=?", "r.set_id=?", "r.step=?"], [run_slug, set_id, step]
            for key, col in (("class_true", "r.class_true"), ("class_pred", "r.class_pred"), ("outcome", "r.outcome")):
                if key in f:
                    values = str(f[key]).split(",")
                    where.append(f"{col} IN ({','.join('?' * len(values))})")
                    args += values
            for n, (key, value) in enumerate((k[5:], v) for k, v in f.items() if k.startswith("fact.")):
                if not FACT_KEY.fullmatch(key):
                    raise HubError(f"bad fact filter {key!r}")
                values = str(value).split(",")
                joins.append(f"JOIN eval_facts f{n} ON f{n}.item=r.item AND f{n}.key=? AND f{n}.value IN "
                             f"({','.join('?' * len(values))})")
                join_args += [key, *values]
            if "q" in f:
                where.append("(i.sample LIKE ? OR EXISTS(SELECT 1 FROM eval_facts q WHERE q.item=r.item AND q.value LIKE ?))")
                args += [f"%{f['q']}%"] * 2
            if "value_min" in f:
                where.append("r.value_true >= ?")
                args.append(float(f["value_min"]))
            if "value_max" in f:
                where.append("r.value_true <= ?")
                args.append(float(f["value_max"]))
            if str(f.get("layered", "")).lower() in ("1", "true", "yes"):
                where.append("EXISTS(SELECT 1 FROM eval_layers l WHERE l.run=r.run AND l.set_id=r.set_id "
                             "AND l.item=r.item AND l.step=r.step)")
            vs_cols = ""
            if "vs" in f:
                vs_step = self._step_or_latest(conn, f["vs"], set_id, f.get("vs_step"))
                joins.append("JOIN eval_results v ON v.run=? AND v.set_id=r.set_id AND v.step=? AND v.item=r.item")
                join_args += [f["vs"], vs_step]
                vs_cols = ", v.class_pred AS vs_class_pred, v.outcome AS vs_outcome, v.error AS vs_error"
                if "vs_outcome" in f:
                    values = str(f["vs_outcome"]).split(",")
                    where.append(f"v.outcome IN ({','.join('?' * len(values))})")
                    args += values
            order = SORTS.get(sort or "error", SORTS["error"])
            base = f"FROM eval_results r {' '.join(joins)} WHERE {' AND '.join(where)}"
            args = join_args + args
            total = conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
            out = rows(conn.execute(
                f"SELECT r.item, i.sample, r.epoch, r.truth, r.pred, r.class_true, r.class_pred, r.value_true, "
                f"r.value_pred, r.score, r.outcome, r.error, r.metrics{vs_cols} {base} ORDER BY {order} NULLS LAST, "
                "i.sample LIMIT ? OFFSET ?", args + [min(max(int(limit), 1), 200), max(int(offset), 0)]))
            layers = self._layers_for(conn, run_slug, set_id, [r["item"] for r in out], step)
            facts = self._facts_for(conn, [r["item"] for r in out])
            for r in out:
                self._decode(r)
                r["layers"], r["facts"] = layers[r["item"]], facts[r["item"]]
            return {"set": eval_set, "step": step, "total": total, "rows": out}

    def eval_facets(self, run_slug, eval_set, step=None) -> dict:
        """Counts behind the filter controls: outcomes, classes, every fact key, and the confusion matrix."""
        with self.connect() as conn:
            run = self._load_run(conn, run_slug)
            set_id = self._set_id(conn, run["project"], eval_set)
            step = self._step_or_latest(conn, run_slug, set_id, step)
            base = "FROM eval_results r WHERE r.run=? AND r.set_id=? AND r.step=?"
            args = (run_slug, set_id, step)
            out = {"set": eval_set, "step": step,
                   "outcome": {r[0]: r[1] for r in conn.execute(f"SELECT r.outcome, COUNT(*) {base} GROUP BY 1", args)},
                   "confusion": [list(r) for r in conn.execute(
                       f"SELECT r.class_true, r.class_pred, COUNT(*) {base} AND r.class_true!='' GROUP BY 1, 2", args)],
                   "class_true": [list(r) for r in conn.execute(
                       f"SELECT r.class_true, COUNT(*), SUM(r.outcome NOT IN ('correct','unscored')) {base} "
                       "AND r.class_true!='' GROUP BY 1 ORDER BY 2 DESC", args)],
                   "class_pred": [list(r) for r in conn.execute(
                       f"SELECT r.class_pred, COUNT(*), SUM(r.outcome NOT IN ('correct','unscored')) {base} "
                       "AND r.class_pred!='' GROUP BY 1 ORDER BY 2 DESC", args)],
                   "value_range": list(conn.execute(f"SELECT MIN(r.value_true), MAX(r.value_true) {base}", args).fetchone()),
                   "kinds": {k: bool(conn.execute(f"SELECT 1 {base} AND {expr} LIMIT 1", args).fetchone())
                             for k, expr in (("boxes", "(r.truth LIKE '%\"boxes\"%' OR r.pred LIKE '%\"boxes\"%')"),
                                             ("text", "r.pred LIKE '%\"text\"%'"), ("value", "r.value_true IS NOT NULL"),
                                             ("layers", "EXISTS(SELECT 1 FROM eval_layers l WHERE l.run=r.run AND "
                                                        "l.set_id=r.set_id AND l.item=r.item AND l.step>=0)"))},
                   "layers": self._layer_kinds(conn, run_slug, set_id), "facts": {}}
            out["box_classes"] = [r[0] for r in conn.execute(  # labels of predicted boxes: one score filter each
                "SELECT DISTINCT json_extract(b.value, '$[4]') FROM eval_results r, json_each(r.pred, '$.boxes') b "
                "WHERE r.run=? AND r.set_id=? AND r.step=? AND json_extract(b.value, '$[4]') IS NOT NULL ORDER BY 1 "
                "LIMIT 200", args)] if out["kinds"]["boxes"] else []
            for key, in conn.execute("SELECT DISTINCT f.key FROM eval_facts f JOIN eval_items i ON i.id=f.item "
                                     "WHERE i.set_id=? ORDER BY f.key", (set_id,)):
                out["facts"][key] = [list(r) for r in conn.execute(
                    "SELECT f.value, COUNT(*), SUM(r.outcome NOT IN ('correct','unscored')) FROM eval_results r "
                    "JOIN eval_facts f ON f.item=r.item AND f.key=? WHERE r.run=? AND r.set_id=? AND r.step=? "
                    "GROUP BY 1 ORDER BY 3 DESC, 2 DESC LIMIT 400", (key, *args))]
            return out

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
