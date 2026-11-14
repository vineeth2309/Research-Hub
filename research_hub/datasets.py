"""One eval set across runs: what every chosen run predicted on each sample, and where the runs agree or split.

Each run is read at its last logged checkpoint. Reading eval_results sample by sample is slow on a busy disk, so
what the pages need is packed into small files in <home>/summaries, one per run and checkpoint (outcome, predicted
class, score, error, the numbers of `pred`, which samples have overlays) and one per eval set (sample ids, truth,
facts, image). A run's own Samples tab filters and counts on the same files and reads only the page it shows from
eval_results, by primary key. The file names carry
the version kept in eval_columns / eval_set_versions, which every write raises, so a stale file is never read; a
missing one is built from the rows on the next request. Sets of samples are integer bit masks over the set's items,
so a filter is an AND and a count is a popcount.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import zlib
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from .core import HubError, NotFound, now, number, rows
from .evals import FACT_KEY, STATIC_STEP

VALUE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,39}")
MAX_RUNS = 64
MAX_EXPORT = 200_000
MEMORY = 200 << 20  # bytes of decoded summaries kept between requests
PRESETS = ("most_wrong", "all_wrong", "split", "all_right", "one_wrong", "one_right")
SORTS = {"wrong": lambda s: (s.wrong, s.disagree), "disagree": lambda s: s.disagree, "value": lambda s: s.value_mean,
         "spread": lambda s: s.value_sd, "score": lambda s: s.score_mean}
UNSCORED, CORRECT, MISSED, FALSE_ALARM, WRONG = range(5)  # what an outcome counts as


class Indexing(HubError):
    status = 503


class Stat(NamedTuple):
    """One sample across the chosen runs."""
    runs: int
    scored: int
    wrong: int
    missed: int
    false_alarm: int
    disagree: float
    value_mean: float | None
    value_sd: float | None
    score_mean: float | None
    classes: Counter


class _Cache:
    """Decoded summaries kept between requests, bounded by their estimated size; the least recently used go first."""

    def __init__(self, limit):
        self.limit, self.used, self.items, self.gates, self.lock = limit, 0, OrderedDict(), {}, threading.Lock()

    def get(self, key, cost, build):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key][0]
            gate = self.gates.setdefault(key, threading.Lock())
        with gate:  # callers asking for the same thing wait for the first one instead of each reading the disk
            try:
                with self.lock:
                    if key in self.items:
                        return self.items[key][0]
                value = build()
                size = cost(value)
                with self.lock:
                    self.items[key] = (value, size)
                    self.used += size
                    while self.used > self.limit and len(self.items) > 1:
                        self.used -= self.items.popitem(last=False)[1][1]
                return value
            finally:
                with self.lock:
                    self.gates.pop(key, None)


def _mask(positions, size) -> int:
    bits = bytearray((size + 7) // 8)
    for p in positions:
        bits[p >> 3] |= 1 << (p & 7)
    return int.from_bytes(bits, "little")


def _positions(mask: int) -> list[int]:
    out = []
    for base, byte in enumerate(mask.to_bytes((mask.bit_length() + 7) // 8, "little")):
        if byte:
            out += [base * 8 + b for b in range(8) if byte >> b & 1]
    return out


def _any(masks) -> int:
    out = 0
    for m in masks:
        out |= m
    return out


def _mean_sd(values):
    if not values:
        return None, None
    mean = sum(values) / len(values)
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _index(names: list, lookup: dict, name) -> int:
    """Position of name in names, appending it first when new."""
    if name not in lookup:
        lookup[name] = len(names)
        names.append(name)
    return lookup[name]


def _category(outcome: str) -> int:
    return {"unscored": UNSCORED, "correct": CORRECT, "missed": MISSED, "false_alarm": FALSE_ALARM}.get(outcome, WRONG)


class Datasets:
    # ---------------------------------------------------------------- summary files
    def _summary_cache(self) -> _Cache:
        return self.__dict__.setdefault("_summaries", _Cache(MEMORY))

    @staticmethod
    def _stem(run, step, kind):
        return f"{run}~{step}~{kind}~"

    def _file(self, set_id, run, step, kind, tag) -> Path:
        return self.db.summaries / str(set_id) / f"{self._stem(run, step, kind)}{tag}.z"

    @staticmethod
    def _read_file(path: Path):
        try:
            return json.loads(zlib.decompress(path.read_bytes()))
        except FileNotFoundError:
            return None

    @staticmethod
    def _write_file(path: Path, value, stem):
        """Write atomically, then remove the older versions of the same summary."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
        tmp.write_bytes(zlib.compress(json.dumps(value, separators=(",", ":")).encode(), 6))
        os.replace(tmp, path)
        for old in path.parent.iterdir():
            if old.name.startswith(stem) and old.name != path.name:
                old.unlink(missing_ok=True)

    @staticmethod
    def _set_version(conn, set_id) -> int:
        row = conn.execute("SELECT version FROM eval_set_versions WHERE set_id=?", (set_id,)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _column_version(conn, run, set_id, step):
        row = conn.execute("SELECT version FROM eval_columns WHERE run=? AND set_id=? AND step=?",
                           (run, set_id, step)).fetchone()
        return row[0] if row else None

    # ---------------------------------------------------------------- the eval set
    def _build_set(self, conn, set_id) -> dict:
        ids, names, truth, image = [], [], [], []
        for r in conn.execute("SELECT id, sample, meta FROM eval_items WHERE set_id=? ORDER BY id", (set_id,)):
            meta = json.loads(r["meta"])
            ids.append(r["id"])
            names.append(r["sample"])
            truth.append({k: v for k, v in meta.get("truth", {}).items()
                          if isinstance(v, (str, int, float)) and not isinstance(v, bool)})
            image.append(meta.get("image", ""))
        at = {item: pos for pos, item in enumerate(ids)}
        if not all(image):  # samples logged before the image was kept on the sample: take it from any run's layers
            for (run,) in conn.execute("SELECT run FROM eval_columns WHERE set_id=? ORDER BY rows DESC", (set_id,)).fetchall():
                for item, sha in conn.execute("SELECT item, blob_sha FROM eval_layers WHERE run=? AND set_id=? AND step=? "
                                              "AND layer='image'", (run, set_id, STATIC_STEP)):
                    if item in at and not image[at[item]]:
                        image[at[item]] = sha
                if all(image):
                    break
        facts: dict[str, dict] = {}
        looks: dict[str, dict] = {}
        for item, key, value in conn.execute("SELECT f.item, f.key, f.value FROM eval_facts f JOIN eval_items i "
                                             "ON i.id=f.item WHERE i.set_id=?", (set_id,)):
            col = facts.setdefault(key, {"v": [], "x": [-1] * len(ids)})
            col["x"][at[item]] = _index(col["v"], looks.setdefault(key, {}), value)
        return {"i": ids, "n": names, "t": truth, "m": image, "f": facts}

    def _set_record(self, conn, set_id) -> dict:
        """The set's samples with a mask for every true class and fact value; kept in memory while in use."""
        version = self._set_version(conn, set_id)

        def build():
            path = self._file(set_id, "_", 0, "set", f"v{version}")
            raw = self._read_file(path)
            if raw is None:
                raw = self._build_set(conn, set_id)
                if self._set_version(conn, set_id) == version:
                    self._write_file(path, raw, self._stem("_", 0, "set"))
            ids = raw["i"]
            classes: dict[str, list[int]] = {}
            for pos, t in enumerate(raw["t"]):
                if t.get("class"):
                    classes.setdefault(t["class"], []).append(pos)
            masks = {}
            for key, col in raw["f"].items():
                at_value: dict[int, list[int]] = {}
                for pos, x in enumerate(col["x"]):
                    if x >= 0:
                        at_value.setdefault(x, []).append(pos)
                masks[key] = {col["v"][x]: _mask(p, len(ids)) for x, p in at_value.items()}
            return {"ids": ids, "at": {item: pos for pos, item in enumerate(ids)}, "names": raw["n"], "truth": raw["t"],
                    "image": raw["m"], "facts": raw["f"], "all": (1 << len(ids)) - 1,
                    "class_true": {c: _mask(p, len(ids)) for c, p in classes.items()}, "fact_masks": masks}
        return self._summary_cache().get((set_id, "set", version), lambda r: len(r["ids"]) * 300, build)

    # ---------------------------------------------------------------- one run on the set
    def _build_column(self, conn, run, set_id, step) -> dict:
        ids, outcomes, classes, scores, errors = [], [], [], [], []
        oc, cl, nums = {}, {}, {}
        outcome_names, class_names = [], []
        boxes, text, box_classes = False, False, set()
        for item, outcome, class_pred, score, error, truth, pred in conn.execute(
                "SELECT item, outcome, class_pred, score, error, truth, pred FROM eval_results WHERE run=? AND set_id=? "
                "AND step=? ORDER BY item", (run, set_id, step)):
            pos = len(ids)
            ids.append(item)
            outcomes.append(_index(outcome_names, oc, outcome))
            classes.append(_index(class_names, cl, class_pred) if class_pred else -1)
            scores.append(score if score is None or math.isfinite(score) else None)
            errors.append(error if error is None or math.isfinite(error) else None)
            boxes = boxes or '"boxes"' in truth or '"boxes"' in pred
            text = text or '"text"' in pred
            parsed = json.loads(pred)
            for b in parsed.get("boxes") or ():
                if len(b) > 4 and isinstance(b[4], str):
                    box_classes.add(b[4])
            for k, v in parsed.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and VALUE_KEY.fullmatch(k):
                    nums.setdefault(k, {})[pos] = round(v, 6)
        return {"i": ids, "o": outcomes, "oc": outcome_names, "c": classes, "cl": class_names, "s": scores, "e": errors,
                "n": {k: [col.get(p) for p in range(len(ids))] for k, col in nums.items()},
                "kb": boxes, "kt": text, "bc": sorted(box_classes),
                "ly": [r[0] for r in conn.execute("SELECT DISTINCT item FROM eval_layers WHERE run=? AND set_id=? AND step=?",
                                                  (run, set_id, step))],
                "lk": dict(conn.execute("SELECT DISTINCT layer, kind FROM eval_layers WHERE run=? AND set_id=? AND "
                                        "kind IN ('mask','heatmap') ORDER BY layer", (run, set_id)).fetchall())}

    def _column_raw(self, run, set_id, step, version) -> dict:
        path = self._file(set_id, run, step, "col", f"v{version}")
        raw = self._read_file(path)
        if raw is None:
            with self.connect() as conn:  # one connection per thread
                raw = self._build_column(conn, run, set_id, step)
                if self._column_version(conn, run, set_id, step) == version:
                    self._write_file(path, raw, self._stem(run, step, "col"))
        return raw

    def _aligned(self, set_id, run, step, version, rec) -> dict:
        """One run's results at a checkpoint, lined up with the set's samples (position p is rec's sample p)."""
        size = len(rec["ids"])

        def build():
            raw = self._column_raw(run, set_id, step, version)
            o, c, s, e = [-1] * size, [-1] * size, [None] * size, [None] * size
            n = {k: [None] * size for k in raw["n"]}
            for j, item in enumerate(raw["i"]):
                pos = rec["at"].get(item)
                if pos is None:  # logged after the set record was read; the next request has it
                    continue
                o[pos], c[pos], s[pos], e[pos] = raw["o"][j], raw["c"][j], raw["s"][j], raw["e"][j]
                for k, col in n.items():
                    col[pos] = raw["n"][k][j]
            return {"o": o, "oc": raw["oc"], "cat": [_category(x) for x in raw["oc"]], "c": c, "cl": raw["cl"], "s": s,
                    "e": e, "n": n, "ly": _mask([rec["at"][i] for i in raw["ly"] if i in rec["at"]], size),
                    "kb": raw["kb"], "kt": raw["kt"], "bc": raw["bc"], "lk": raw["lk"],
                    "seen": _mask([p for p in range(size) if o[p] >= 0], size)}
        return self._summary_cache().get((set_id, run, step, version, size), lambda c: size * (80 + 30 * len(c["n"])), build)

    def _columns(self, set_id, picked, rec) -> list[dict]:
        """The chosen runs' results lined up with the set's samples. Loaded together: on a busy disk the reads overlap."""
        with ThreadPoolExecutor(min(len(picked), 16)) as pool:
            return list(pool.map(lambda p: self._aligned(set_id, p[0], p[1], p[2], rec), picked))

    # ---------------------------------------------------------------- listing
    def eval_sets(self, project) -> list[dict]:
        """Every eval set of a project with the runs that logged it, each at its last checkpoint."""
        with self.connect() as conn:
            state = conn.execute("SELECT value FROM meta WHERE key='eval_index'").fetchone()
            if state and state[0] == "pending":
                raise Indexing("the results logged before this version are being indexed; try again in a few minutes")
            out = {r["id"]: {"set": r["name"], "samples": 0, "runs": []}
                   for r in conn.execute("SELECT id, name FROM eval_sets WHERE project=?", (project,))}
            last: dict[str, dict[int, tuple]] = {}
            for run, set_id, step, rows_, logged in conn.execute(
                    "SELECT c.run, c.set_id, c.step, c.rows, c.logged FROM eval_columns c JOIN eval_sets s ON s.id=c.set_id "
                    "WHERE s.project=? ORDER BY c.run, c.set_id, c.step", (project,)):  # steps ascending: the last wins
                out[set_id]["samples"] = max(out[set_id]["samples"], rows_)
                last.setdefault(run, {})[set_id] = (step, logged)
            for run in rows(conn.execute("SELECT slug, title, owner, category, status, verdict FROM runs WHERE project=? "
                                         "ORDER BY slug", (project,))):
                for set_id, (step, logged) in last.get(run["slug"], {}).items():
                    out[set_id]["runs"].append({**run, "step": step, "logged": logged})
        return sorted((s for s in out.values() if s["runs"]), key=lambda s: (-len(s["runs"]), s["set"]))

    # ---------------------------------------------------------------- the chosen runs together
    def _dataset(self, conn, project, eval_set, slugs, value) -> dict:
        """The chosen runs on one eval set: their columns, a Stat per sample and the masks behind the presets."""
        set_id = self._set_id(conn, project, eval_set)
        slugs = list(dict.fromkeys(slugs))
        if not slugs or len(slugs) > MAX_RUNS:
            raise HubError(f"runs must name 1-{MAX_RUNS} runs that logged {eval_set}")
        known = {r[0] for r in conn.execute(
            f"SELECT slug FROM runs WHERE project=? AND slug IN ({','.join('?' * len(slugs))})", (project, *slugs))}
        last = {run: (step, version, logged) for run, step, version, logged in conn.execute(  # steps ascending: the last wins
            "SELECT run, step, version, logged FROM eval_columns WHERE set_id=? ORDER BY run, step", (set_id,))}
        picked = []
        for slug in slugs:
            if slug not in known:
                raise NotFound(f"run {slug!r} is not in this project")
            if slug not in last:
                raise NotFound(f"run {slug} has no results for this eval set")
            picked.append((slug, *last[slug]))
        rec = self._set_record(conn, set_id)
        columns = self._columns(set_id, picked, rec)
        values = sorted({k for col in columns for k in col["n"]})
        if value not in values:
            value = "value" if "value" in values else next((k for k in values if k != "score"), values[0] if values else "")
        size = len(rec["ids"])

        def build():
            nbytes = (size + 7) // 8
            has, wrong = [bytearray(nbytes) for _ in columns], [bytearray(nbytes) for _ in columns]
            groups = {name: [] for name in (*PRESETS, "scored", "seen")}
            numbers = [col["n"].get(value) for col in columns]
            stats: list[Stat | None] = []
            for pos in range(size):
                seen = scored = bad = missed = false_alarm = 0
                classes, nums, scs = Counter(), [], []
                byte, bit = pos >> 3, 1 << (pos & 7)
                for r, col in enumerate(columns):
                    o = col["o"][pos]
                    if o < 0:
                        continue
                    seen += 1
                    has[r][byte] |= bit
                    code = col["cat"][o]
                    if code != UNSCORED:
                        scored += 1
                        if code != CORRECT:
                            bad += 1
                            wrong[r][byte] |= bit
                            missed += code == MISSED
                            false_alarm += code == FALSE_ALARM
                    if col["c"][pos] >= 0:
                        classes[col["cl"][col["c"][pos]]] += 1
                    if numbers[r] is not None and numbers[r][pos] is not None:
                        nums.append(numbers[r][pos])
                    if col["s"][pos] is not None:
                        scs.append(col["s"][pos])
                if not seen:
                    stats.append(None)
                    continue
                top = max(classes.values(), default=0)
                disagree = min(bad, scored - bad) / scored if scored else (1 - top / seen if top else 0.0)
                stats.append(Stat(seen, scored, bad, missed, false_alarm, disagree, *_mean_sd(nums), _mean_sd(scs)[0], classes))
                groups["seen"].append(pos)
                if scored:
                    groups["scored"].append(pos)
                    for name, hit in (("most_wrong", bad * 2 > scored), ("all_wrong", bad == scored),
                                      ("split", 0.25 <= bad / scored <= 0.75), ("all_right", bad == 0),
                                      ("one_wrong", bad == 1 and scored > 1), ("one_right", scored - bad == 1 and scored > 1)):
                        if hit:
                            groups[name].append(pos)
            return {"stats": stats, "has": [int.from_bytes(b, "little") for b in has],
                    "wrong": [int.from_bytes(b, "little") for b in wrong],
                    "groups": {name: _mask(p, size) for name, p in groups.items()}}
        key = (set_id, "dataset", tuple(p[:3] for p in picked), value, size)
        data = self._summary_cache().get(key, lambda d: size * 400, build)
        return {**data, "rec": rec, "columns": columns, "set_id": set_id, "runs": picked, "value": value, "values": values}

    @staticmethod
    def _text_mask(rec, text) -> int:
        """The samples whose id or any fact value contains text, ignoring case."""
        needle = str(text).lower()
        return _mask([pos for pos, name in enumerate(rec["names"]) if needle in name.lower()], len(rec["ids"])) | _any(
            m for vals in rec["fact_masks"].values() for v, m in vals.items() if needle in v.lower())

    def _dataset_filter(self, d, f) -> int:
        """The samples that pass the fact, class, text and preset filters, as a mask."""
        rec, mask = d["rec"], d["groups"]["seen"]
        for key, value in f.items():
            if key.startswith("fact."):
                if not FACT_KEY.fullmatch(key[5:]):
                    raise HubError(f"bad fact filter {key[5:]!r}")
                known = rec["fact_masks"].get(key[5:], {})
                mask &= _any(known.get(v, 0) for v in str(value).split(","))
        if f.get("class_true"):
            mask &= _any(rec["class_true"].get(v, 0) for v in str(f["class_true"]).split(","))
        if f.get("q"):
            mask &= self._text_mask(rec, f["q"])
        preset = f.get("preset")
        if preset:
            if preset not in PRESETS:
                raise HubError(f"preset must be one of {list(PRESETS)}")
            mask &= d["groups"][preset]
            if f.get("run") and preset in ("one_wrong", "one_right"):  # the one run that is wrong, or right, is this one
                slugs = [p[0] for p in d["runs"]]
                if f["run"] not in slugs:
                    raise HubError(f"run {f['run']!r} is not among the chosen runs")
                r = slugs.index(f["run"])
                mask &= d["wrong"][r] if preset == "one_wrong" else d["has"][r] & ~d["wrong"][r]
        return mask

    # ---------------------------------------------------------------- reading
    def dataset_samples(self, project, eval_set, slugs, filters=None, sort="wrong", desc=True, limit=48, offset=0,
                        value=None, compact=False) -> dict:
        """One page of samples with every chosen run's call. compact leaves out images and calls, for exports."""
        f = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
        with self.connect() as conn:
            d = self._dataset(conn, project, eval_set, slugs, value or "")
        stats, rec, columns, number = d["stats"], d["rec"], d["columns"], d["value"]
        found = _positions(self._dataset_filter(d, f))
        cls = f.get("pred_class")
        if cls:  # how many runs predict this class: keep the samples where that count is within the bounds
            low, high = int(f.get("pred_min", 0)), int(f.get("pred_max", MAX_RUNS))
            found = [p for p in found if low <= stats[p].classes.get(cls, 0) <= high]
        if sort == "pred" and cls:
            rank = lambda p: stats[p].classes.get(cls, 0)  # noqa: E731
        elif sort in SORTS:
            rank = lambda p: SORTS[sort](stats[p])  # noqa: E731
        elif sort == "sample":
            rank = None
        else:
            raise HubError(f"sort must be one of {[*SORTS, 'pred', 'sample']}")
        if rank:
            ranked = [p for p in found if rank(p) is not None]
            ranked.sort(key=rank, reverse=desc)
            found = ranked + [p for p in found if rank(p) is None]
        limit = min(max(int(limit), 1), MAX_EXPORT if compact else 200)
        start = max(int(offset), 0)
        out = []
        for p in found[start:start + limit]:
            s = stats[p]
            row = {"item": rec["ids"][p], "sample": rec["names"][p], "truth": rec["truth"][p],
                   "facts": {k: c["v"][c["x"][p]] for k, c in rec["facts"].items() if c["x"][p] >= 0},
                   "runs": s.runs, "scored": s.scored, "wrong": s.wrong, "missed": s.missed, "false_alarm": s.false_alarm,
                   "disagree": round(s.disagree, 4), "value_mean": s.value_mean, "value_sd": s.value_sd,
                   "score_mean": s.score_mean, "classes": s.classes.most_common()}
            if not compact:
                row["image"] = rec["image"][p] or None
                row["calls"] = [None if c["o"][p] < 0 else
                                [c["oc"][c["o"][p]], c["cl"][c["c"][p]] if c["c"][p] >= 0 else "",
                                 c["n"][number][p] if number in c["n"] else None, c["s"][p]] for c in columns]
            out.append(row)
        return {"set": eval_set, "value": number, "values": d["values"],
                "runs": [{"slug": p[0], "step": p[1], "logged": p[3]} for p in d["runs"]], "total": len(found), "rows": out}

    def dataset_summary(self, project, eval_set, slugs, filters=None, by=None, value=None) -> dict:
        """Counts behind the page: presets, filter values, how many runs get each sample wrong, run-to-run agreement."""
        f = {k: v for k, v in (filters or {}).items() if v not in (None, "") and k != "preset"}
        with self.connect() as conn:
            d = self._dataset(conn, project, eval_set, slugs, value or "")
        rec, groups, n, size = d["rec"], d["groups"], len(d["runs"]), len(d["rec"]["ids"])
        mask = self._dataset_filter(d, f)
        scored = mask & groups["scored"]
        hist = Counter(d["stats"][p].wrong for p in _positions(scored))
        most = groups["most_wrong"]

        def counted(masks: dict, within=rec["all"], top=400):
            found = [[v, (m & within).bit_count(), (m & within & most).bit_count()] for v, m in masks.items()]
            return sorted((x for x in found if x[1]), key=lambda x: (-x[2], -x[1], x[0]))[:top]
        by = by if by in rec["fact_masks"] else next(iter(sorted(rec["fact_masks"], key=lambda k: -len(rec["fact_masks"][k]))), None)
        if scored:  # two runs agree on a sample when both are right or both are wrong
            same = [[((d["has"][a] & d["has"][b] & scored).bit_count(),
                      ((d["wrong"][a] ^ d["wrong"][b]) & d["has"][a] & d["has"][b] & scored).bit_count())
                     for b in range(n)] for a in range(n)]
            agreement = [[round(1 - differ / both, 4) if both else None for both, differ in row] for row in same]
        else:  # no truth to be right about: they agree when they predict the same class
            bits = []
            for col in d["columns"]:
                at_class: dict[int, list[int]] = {}
                for pos, c in enumerate(col["c"]):
                    if c >= 0:
                        at_class.setdefault(c, []).append(pos)
                bits.append({col["cl"][c]: _mask(p, size) for c, p in at_class.items()})
            agreement = [[round(sum((m & bits[b].get(c, 0) & mask).bit_count() for c, m in bits[a].items()) / both, 4)
                          if (both := (d["has"][a] & d["has"][b] & mask).bit_count()) else None
                          for b in range(n)] for a in range(n)]
        return {"set": eval_set, "value": d["value"], "values": d["values"], "samples": size,
                "runs": [{"slug": p[0], "step": p[1], "logged": p[3]} for p in d["runs"]],
                "total": mask.bit_count(), "scored": scored.bit_count(),
                "presets": {name: (mask & groups[name]).bit_count() for name in PRESETS},
                "wrong_hist": [hist.get(k, 0) for k in range(n + 1)],
                "class_true": counted(rec["class_true"]),
                "class_pred": sorted(set().union(*(col["cl"] for col in d["columns"])) - {""}),
                "facts": {k: counted(v) for k, v in sorted(rec["fact_masks"].items())},
                "by": by, "groups": counted(rec["fact_masks"][by], mask, 12) if by else [], "agreement": agreement}

    # ---------------------------------------------------------------- one run's Samples tab
    def _run_column(self, conn, run_slug, set_id, step):
        version = self._column_version(conn, run_slug, set_id, step)
        if version is None:
            raise NotFound(f"run {run_slug} has no results for this eval set")
        rec = self._set_record(conn, set_id)
        return rec, self._aligned(set_id, run_slug, step, version, rec)

    def eval_facets(self, run_slug, eval_set, step=None) -> dict:
        """Counts behind the filter controls: outcomes, classes, every fact key, and the confusion matrix."""
        with self.connect() as conn:
            run = self._load_run(conn, run_slug)
            set_id = self._set_id(conn, run["project"], eval_set)
            step = self._step_or_latest(conn, run_slug, set_id, step)
            rec, col = self._run_column(conn, run_slug, set_id, step)
        truth, seen = rec["truth"], _positions(col["seen"])
        outcome, confusion = Counter(), Counter()
        true_n, true_bad, pred_n, pred_bad, values, bad = Counter(), Counter(), Counter(), Counter(), [], set()
        for p in seen:
            o = col["o"][p]
            outcome[col["oc"][o]] += 1
            wrong = col["cat"][o] not in (UNSCORED, CORRECT)
            if wrong:
                bad.add(p)
            true = truth[p].get("class", "")
            pred = col["cl"][col["c"][p]] if col["c"][p] >= 0 else ""
            if true:
                confusion[true, pred] += 1
                true_n[true] += 1
                true_bad[true] += wrong
            if pred:
                pred_n[pred] += 1
                pred_bad[pred] += wrong
            if truth[p].get("value") is not None:
                values.append(truth[p]["value"])
        facts = {}
        for key, c in rec["facts"].items():
            count, wrong = Counter(), Counter()
            for p in seen:
                if c["x"][p] >= 0:
                    count[c["x"][p]] += 1
                    wrong[c["x"][p]] += p in bad
            facts[key] = sorted(([c["v"][x], n, wrong[x]] for x, n in count.items()), key=lambda r: (-r[2], -r[1], r[0]))[:400]
        ranked = lambda n, b: [[k, n[k], b[k]] for k in sorted(n, key=lambda k: (-n[k], k))]  # noqa: E731
        return {"set": eval_set, "step": step, "outcome": dict(outcome),
                "confusion": [[t, p, n] for (t, p), n in sorted(confusion.items())],
                "class_true": ranked(true_n, true_bad), "class_pred": ranked(pred_n, pred_bad),
                "value_range": [min(values), max(values)] if values else [None, None],
                "kinds": {"boxes": col["kb"], "text": col["kt"], "value": bool(values), "layers": bool(col["ly"])},
                "layers": dict(sorted(col["lk"].items())), "facts": facts,
                "box_classes": col["bc"][:200] if col["kb"] else []}

    def _page_rows(self, run_slug, set_id, step, items) -> tuple[dict, dict]:
        """The stored rows and layers of the page's samples. Each is a lookup by primary key, so a few at a time on
        their own connections: on a busy disk the waits overlap instead of adding up."""
        def fetch(chunk):
            with self.connect() as conn:
                got = {r["item"]: r for r in conn.execute(
                    "SELECT item, epoch, truth, pred, class_true, class_pred, value_true, value_pred, score, outcome, error, "
                    f"metrics FROM eval_results WHERE run=? AND set_id=? AND step=? AND item IN ({','.join('?' * len(chunk))})",
                    (run_slug, set_id, step, *chunk))}
                return got, self._layers_for(conn, run_slug, set_id, chunk, step)
        got, layers = {}, {}
        if items:
            with ThreadPoolExecutor(8) as pool:
                for rows_, layers_ in pool.map(fetch, [items[i:i + 3] for i in range(0, len(items), 3)]):
                    got.update(rows_)
                    layers.update(layers_)
        return got, layers

    def eval_query(self, run_slug, eval_set, step=None, filters=None, sort="error", limit=24, offset=0) -> dict:
        """One page of samples at a checkpoint, filtered by facts, classes, outcome, value range, other runs."""
        f = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
        with self.connect() as conn:
            run = self._load_run(conn, run_slug)
            set_id = self._set_id(conn, run["project"], eval_set)
            step = self._step_or_latest(conn, run_slug, set_id, step)
            rec, col = self._run_column(conn, run_slug, set_id, step)
            size, truth, mask = len(rec["ids"]), rec["truth"], col["seen"]

            def labelled(array, labels, wanted):  # the samples whose outcome or class is one of wanted
                ids = {i for i, name in enumerate(labels) if name in wanted}
                return _mask([p for p in range(size) if array[p] in ids], size)
            if "outcome" in f:
                mask &= labelled(col["o"], col["oc"], str(f["outcome"]).split(","))
            if "class_pred" in f:
                mask &= labelled(col["c"], col["cl"], str(f["class_pred"]).split(","))
            if "class_true" in f:
                mask &= _any(rec["class_true"].get(v, 0) for v in str(f["class_true"]).split(","))
            for key, value in f.items():
                if key.startswith("fact."):
                    if not FACT_KEY.fullmatch(key[5:]):
                        raise HubError(f"bad fact filter {key[5:]!r}")
                    mask &= _any(rec["fact_masks"].get(key[5:], {}).get(v, 0) for v in str(value).split(","))
            if "q" in f:
                mask &= self._text_mask(rec, f["q"])
            for bound, keep in (("value_min", lambda v, x: v >= x), ("value_max", lambda v, x: v <= x)):
                if bound in f:
                    x = number(f[bound], bound)
                    mask &= _mask([p for p in range(size) if truth[p].get("value") is not None and keep(truth[p]["value"], x)], size)
            if str(f.get("layered", "")).lower() in ("1", "true", "yes"):
                mask &= col["ly"]
            other = None
            if "vs" in f:
                _, other = self._run_column(conn, f["vs"], set_id, self._step_or_latest(conn, f["vs"], set_id, f.get("vs_step")))
                mask &= other["seen"]
                if "vs_outcome" in f:
                    mask &= labelled(other["o"], other["oc"], str(f["vs_outcome"]).split(","))
            found = _positions(mask)
            by = {"score": lambda p: col["s"][p], "value": lambda p: truth[p].get("value"),
                  "value_pred": lambda p: col["n"]["value"][p] if "value" in col["n"] else None}.get(sort or "error")
            found.sort(key=lambda p: rec["names"][p])
            if sort != "sample":  # biggest first, samples without the number last, ties in sample order
                by = by or (lambda p: col["e"][p])
                found.sort(key=lambda p: (by(p) is None, -(by(p) or 0)))
            page = found[max(int(offset), 0):max(int(offset), 0) + min(max(int(limit), 1), 200)]
            items = [rec["ids"][p] for p in page]
        got, layers = self._page_rows(run_slug, set_id, step, items)
        out = []
        for p, item in zip(page, items):
            if item not in got:  # deleted since the summary was read
                continue
            r = self._decode(dict(got[item]))
            r["sample"] = rec["names"][p]
            r["layers"] = layers[item]
            r["facts"] = {k: c["v"][c["x"][p]] for k, c in rec["facts"].items() if c["x"][p] >= 0}
            if other is not None:
                r["vs_class_pred"] = other["cl"][other["c"][p]] if other["c"][p] >= 0 else ""
                r["vs_outcome"] = other["oc"][other["o"][p]]
                r["vs_error"] = other["e"][p]
            out.append(r)
        return {"set": eval_set, "step": step, "total": len(found), "rows": out}

    # ---------------------------------------------------------------- results logged before eval_columns existed
    def eval_backfill(self):
        """After an upgrade: count the checkpoints already logged, then pack the last one of every run. Resumable."""
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='eval_index'").fetchone()
        state = row[0] if row else "done"
        if state == "pending":
            self._index_checkpoints()
            state = "sets"
        if state == "sets":
            self._pack_last_checkpoints()
            with self.connect(write=True) as conn:
                conn.execute("UPDATE meta SET value='done' WHERE key='eval_index'")
        self._sweep_summaries()

    def _index_checkpoints(self):
        with self.connect() as conn:
            found = conn.execute("SELECT run, set_id, step, COUNT(*), SUM(outcome NOT IN ('correct','unscored')) "
                                 "FROM eval_results GROUP BY run, set_id, step").fetchall()
            names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM eval_sets")}
            layered = {}
            for run, set_id in sorted({(r[0], r[1]) for r in found}):
                for step, n in conn.execute("SELECT step, COUNT(DISTINCT item) FROM eval_layers WHERE run=? AND set_id=? "
                                            "AND step>=0 GROUP BY step", (run, set_id)):
                    layered[run, set_id, step] = n
            records = []
            for run, set_id, step, count, wrong in found:
                epoch = conn.execute("SELECT epoch FROM eval_results WHERE run=? AND set_id=? AND step=? "
                                     "AND epoch IS NOT NULL LIMIT 1", (run, set_id, step)).fetchone()
                logged = conn.execute("SELECT MAX(ts) FROM events WHERE kind='eval.log' AND ref=? AND summary LIKE ?",
                                      (f"run:{run}", f"% of {names[set_id]} at step {step}")).fetchone()[0]
                logged = logged or conn.execute("SELECT updated FROM runs WHERE slug=?", (run,)).fetchone()[0] or now()
                records.append((run, set_id, step, epoch[0] if epoch else None, count, wrong or 0,
                                layered.get((run, set_id, step), 0), logged))
        with self.connect(write=True) as conn:  # a run that logged meanwhile already has its row
            conn.executemany("INSERT OR IGNORE INTO eval_columns(run, set_id, step, epoch, rows, wrong, layered, version, "
                             "logged) VALUES(?,?,?,?,?,?,?,1,?)", records)
            conn.execute("UPDATE meta SET value='sets' WHERE key='eval_index'")

    def _pack_last_checkpoints(self):
        with self.connect() as conn:
            for set_id in [r[0] for r in conn.execute("SELECT id FROM eval_sets ORDER BY id")]:
                self._set_record(conn, set_id)
                for run, step, version in conn.execute(
                        "SELECT run, MAX(step), version FROM eval_columns WHERE set_id=? GROUP BY run", (set_id,)).fetchall():
                    self._column_raw(run, set_id, step, version)
                    time.sleep(0.05)  # background work: leave the disk to the people using it

    def _sweep_summaries(self):
        """Remove summary files that no version refers to any more: replaced, or their run or set was deleted."""
        with self.connect() as conn:
            keep: dict[str, set[str]] = {}
            set_versions = dict(conn.execute("SELECT set_id, version FROM eval_set_versions").fetchall())
            for set_id in (r[0] for r in conn.execute("SELECT id FROM eval_sets")):
                keep[str(set_id)] = {f"{self._stem('_', 0, 'set')}v{set_versions.get(set_id, 0)}.z"}
            for run, set_id, step, version in conn.execute("SELECT run, set_id, step, version FROM eval_columns"):
                keep.get(str(set_id), set()).add(f"{self._stem(run, step, 'col')}v{version}.z")
        for folder in (f for f in self.db.summaries.iterdir() if f.is_dir()):
            for f in folder.iterdir():
                if f.name not in keep.get(folder.name, ()) and not (f.name.startswith(".") and time.time() - f.stat().st_mtime < 3600):
                    f.unlink(missing_ok=True)
            if folder.name not in keep and not any(folder.iterdir()):
                folder.rmdir()
