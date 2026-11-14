"""One eval set across runs: what every chosen run predicted on each sample, and where the runs agree or split.

Each run is read at its last logged checkpoint. Sets of samples are kept as integer bit masks over the eval set's
items, so a filter is an AND and a count is a popcount. Loaded columns are kept in memory until the set is logged to.
"""

from __future__ import annotations

import json
import math
import re
import sys
import threading
from collections import Counter, OrderedDict
from typing import NamedTuple

from .core import HubError, NotFound, rows
from .evals import FACT_KEY, STATIC_STEP

VALUE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,39}")
MAX_RUNS = 64
MAX_EXPORT = 200_000
KEPT = 96  # cached columns and aggregates; the least recently used go first
PRESETS = ("most_wrong", "all_wrong", "split", "all_right", "one_wrong", "one_right")
SORTS = {"wrong": lambda s: (s.wrong, s.disagree), "disagree": lambda s: s.disagree, "value": lambda s: s.value_mean,
         "spread": lambda s: s.value_sd, "score": lambda s: s.score_mean}
_lock = threading.Lock()


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


def _mean_sd(values):
    if not values:
        return None, None
    mean = sum(values) / len(values)
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _chunks(seq, size=500):
    return (seq[i:i + size] for i in range(0, len(seq), size))


class Datasets:
    # ---------------------------------------------------------------- cache
    def _eval_changed(self, set_id, run, step):
        """Rows of this eval set were written: forget what was loaded from it, and note the run's checkpoint."""
        with _lock:
            versions = self.__dict__.setdefault("_dataset_versions", {})
            versions[set_id] = versions.get(set_id, 0) + 1
            if "_eval_runs" in self.__dict__:
                sets = self._eval_runs.setdefault(run, {})
                sets[set_id] = max(step, sets.get(set_id, step))

    def _eval_forget(self, run):
        with _lock:
            self.__dict__.get("_eval_runs", {}).pop(run, None)

    def eval_index(self) -> dict:
        """{run: {eval set id: last step}} for every run, read once and then kept up to date by log_eval."""
        with _lock:  # held while reading, so a log_eval that lands meanwhile is applied after, not lost
            if "_eval_runs" not in self.__dict__:
                index: dict[str, dict[int, int]] = {}
                with self.connect() as conn:
                    for (run,) in conn.execute("SELECT slug FROM runs").fetchall():
                        set_id = -1
                        while True:  # hop from one set of this run to the next: a few index seeks, not a scan
                            set_id = conn.execute("SELECT MIN(set_id) FROM eval_results WHERE run=? AND set_id>?",
                                                  (run, set_id)).fetchone()[0]
                            if set_id is None:
                                break
                            index.setdefault(run, {})[set_id] = conn.execute(
                                "SELECT MAX(step) FROM eval_results WHERE run=? AND set_id=?", (run, set_id)).fetchone()[0]
                self._eval_runs = index
            return {run: dict(sets) for run, sets in self._eval_runs.items()}

    def _dataset_memo(self, set_id, key, build):
        with _lock:
            cache = self.__dict__.setdefault("_dataset_cache", OrderedDict())
            key = (set_id, self.__dict__.setdefault("_dataset_versions", {}).get(set_id, 0), *key)
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
            gate = self.__dict__.setdefault("_dataset_building", {}).setdefault(key, threading.Lock())
        with gate:  # requests for the same thing wait for the first one instead of each reading the disk
            with _lock:
                if key in cache:
                    return cache[key]
            value = build()
            with _lock:
                cache[key] = value
                self._dataset_building.pop(key, None)
                while len(cache) > KEPT:
                    cache.popitem(last=False)
        return value

    # ---------------------------------------------------------------- loading
    def eval_sets(self, project) -> list[dict]:
        """Every eval set of a project with the runs that logged it, each at its last checkpoint."""
        index = self.eval_index()
        with self.connect() as conn:
            out = {r["id"]: {"set": r["name"], "samples": 0, "runs": []}
                   for r in conn.execute("SELECT id, name FROM eval_sets WHERE project=?", (project,))}
            for run in rows(conn.execute("SELECT slug, title, owner, category, status, verdict FROM runs WHERE project=? "
                                         "ORDER BY slug", (project,))):
                for set_id, step in index.get(run["slug"], {}).items():
                    out[set_id]["runs"].append({**run, "step": step})
            found = [(set_id, s) for set_id, s in out.items() if s["runs"]]
            for set_id, s in found:
                s["samples"] = self._dataset_memo(set_id, ("count",), lambda set_id=set_id: conn.execute(
                    "SELECT COUNT(*) FROM eval_items WHERE set_id=?", (set_id,)).fetchone()[0])
        return sorted((s for _, s in found), key=lambda s: (-len(s["runs"]), s["set"]))

    def _dataset_items(self, conn, set_id) -> dict:
        """The set's samples in a fixed order, with a mask per true class and per fact value."""
        def build():
            items, classes = [], {}
            for pos, r in enumerate(conn.execute("SELECT id, meta FROM eval_items WHERE set_id=? ORDER BY id", (set_id,))):
                items.append(r["id"])
                cls = json.loads(r["meta"]).get("truth", {}).get("class")
                if cls:
                    classes.setdefault(cls, []).append(pos)
            at = {item: pos for pos, item in enumerate(items)}
            facts: dict[str, dict[str, list]] = {}
            for r in conn.execute("SELECT f.item, f.key, f.value FROM eval_facts f JOIN eval_items i ON i.id=f.item "
                                  "WHERE i.set_id=?", (set_id,)):
                facts.setdefault(r["key"], {}).setdefault(r["value"], []).append(at[r["item"]])
            size = len(items)
            return {"items": items, "at": at, "all": (1 << size) - 1,
                    "class_true": {c: _mask(p, size) for c, p in classes.items()},
                    "facts": {k: {v: _mask(p, size) for v, p in vals.items()} for k, vals in facts.items()}}
        return self._dataset_memo(set_id, ("items",), build)

    def _dataset_column(self, conn, set_id, run, step, value) -> dict:
        """{item: (outcome, predicted class, the chosen number, score)} of one run at one checkpoint."""
        expr = {"": "NULL", "score": "score", "value": "value_pred"}.get(value) or f"json_extract(pred, '$.{value}')"

        def build():
            return {r[0]: (sys.intern(r[1]), sys.intern(r[2]), r[3] if isinstance(r[3], (int, float)) else None, r[4])
                    for r in conn.execute(f"SELECT item, outcome, class_pred, {expr}, score FROM eval_results "
                                          "WHERE run=? AND set_id=? AND step=?", (run, set_id, step))}
        return self._dataset_memo(set_id, ("column", run, step, value), build)

    def _dataset(self, conn, project, eval_set, slugs, value) -> dict:
        """The chosen runs on one eval set: their columns, a Stat per sample and the masks behind the presets."""
        set_id = self._set_id(conn, project, eval_set)
        slugs = list(dict.fromkeys(slugs))
        if not slugs or len(slugs) > MAX_RUNS:
            raise HubError(f"runs must name 1-{MAX_RUNS} runs that logged {eval_set}")
        picked = []
        for slug in slugs:
            if self._load_run(conn, slug)["project"] != project:
                raise NotFound(f"run {slug!r} is not in this project")
            picked.append((slug, self._step_or_latest(conn, slug, set_id, None)))
        first = conn.execute("SELECT pred, score FROM eval_results WHERE run=? AND set_id=? AND step=? LIMIT 1",
                             (picked[0][0], set_id, picked[0][1])).fetchone()
        values = [k for k, v in json.loads(first["pred"]).items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool) and VALUE_KEY.fullmatch(k)]
        if value not in values:
            value = "value" if "value" in values else next((k for k in values if k != "score"), values[0] if values else "")
        info = self._dataset_items(conn, set_id)

        def build():
            columns = [self._dataset_column(conn, set_id, slug, step, value) for slug, step in picked]
            size = len(info["items"])
            nbytes = (size + 7) // 8
            has, wrong = [bytearray(nbytes) for _ in columns], [bytearray(nbytes) for _ in columns]
            groups = {name: [] for name in (*PRESETS, "scored", "seen")}
            stats: list[Stat | None] = []
            for pos, item in enumerate(info["items"]):
                calls = [c.get(item) for c in columns]
                seen = [c for c in calls if c]
                if not seen:
                    stats.append(None)
                    continue
                byte, bit = pos >> 3, 1 << (pos & 7)
                scored = bad = missed = false_alarm = 0
                for r, c in enumerate(calls):
                    if not c:
                        continue
                    has[r][byte] |= bit
                    if c[0] == "unscored":
                        continue
                    scored += 1
                    if c[0] != "correct":
                        bad += 1
                        wrong[r][byte] |= bit
                        missed += c[0] == "missed"
                        false_alarm += c[0] == "false_alarm"
                classes = Counter(c[1] for c in seen if c[1])
                top = max(classes.values(), default=0)
                disagree = min(bad, scored - bad) / scored if scored else (1 - top / len(seen) if top else 0.0)
                stats.append(Stat(len(seen), scored, bad, missed, false_alarm, disagree,
                                  *_mean_sd([c[2] for c in seen if c[2] is not None]),
                                  _mean_sd([c[3] for c in seen if c[3] is not None])[0], classes))
                groups["seen"].append(pos)
                if scored:
                    groups["scored"].append(pos)
                    for name, hit in (("most_wrong", bad * 2 > scored), ("all_wrong", bad == scored),
                                      ("split", 0.25 <= bad / scored <= 0.75), ("all_right", bad == 0),
                                      ("one_wrong", bad == 1 and scored > 1), ("one_right", scored - bad == 1 and scored > 1)):
                        if hit:
                            groups[name].append(pos)
            return {"stats": stats, "columns": columns, "has": [int.from_bytes(b, "little") for b in has],
                    "wrong": [int.from_bytes(b, "little") for b in wrong],
                    "groups": {name: _mask(p, size) for name, p in groups.items()}}
        data = self._dataset_memo(set_id, ("dataset", tuple(picked), value), build)
        return {**data, **info, "set_id": set_id, "runs": picked, "value": value, "values": values}

    def _dataset_filter(self, conn, d, f) -> int:
        """The samples that pass the fact, class, text and preset filters, as a mask."""
        mask = d["groups"]["seen"]
        for key, value in f.items():
            if key.startswith("fact."):
                if not FACT_KEY.fullmatch(key[5:]):
                    raise HubError(f"bad fact filter {key[5:]!r}")
                known = d["facts"].get(key[5:], {})
                mask &= _any(known.get(v, 0) for v in str(value).split(","))
        if f.get("class_true"):
            mask &= _any(d["class_true"].get(v, 0) for v in str(f["class_true"]).split(","))
        if f.get("q"):
            like = f"%{f['q']}%"
            found = conn.execute(
                "SELECT i.id FROM eval_items i WHERE i.set_id=? AND (i.sample LIKE ? OR EXISTS(SELECT 1 FROM eval_facts q "
                "WHERE q.item=i.id AND q.value LIKE ?))", (d["set_id"], like, like))
            mask &= _mask([d["at"][r[0]] for r in found], len(d["items"]))
        preset = f.get("preset")
        if preset:
            if preset not in PRESETS:
                raise HubError(f"preset must be one of {list(PRESETS)}")
            mask &= d["groups"][preset]
            if f.get("run") and preset in ("one_wrong", "one_right"):  # the one run that is wrong, or right, is this one
                slugs = [slug for slug, _ in d["runs"]]
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
            stats = d["stats"]
            found = _positions(self._dataset_filter(conn, d, f))
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
            page = found[max(int(offset), 0):max(int(offset), 0) + limit]
            ids = [d["items"][p] for p in page]
            meta, facts, images = {}, {}, {}
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                for r in conn.execute(f"SELECT id, sample, meta FROM eval_items WHERE id IN ({marks})", chunk):
                    meta[r["id"]] = (r["sample"], json.loads(r["meta"]).get("truth", {}))
                facts.update(self._facts_for(conn, chunk))
                for slug, _ in () if compact else d["runs"]:  # the image is the same file whichever run logged it
                    missing = [i for i in chunk if i not in images]
                    if not missing:
                        break
                    images.update(conn.execute(
                        f"SELECT item, blob_sha FROM eval_layers WHERE run=? AND set_id=? AND item IN "
                        f"({','.join('?' * len(missing))}) AND step=? AND layer='image'",
                        (slug, d["set_id"], *missing, STATIC_STEP)).fetchall())
            out = []
            for p, item in zip(page, ids):
                s = stats[p]
                row = {"item": item, "sample": meta[item][0], "truth": meta[item][1], "facts": facts[item], "runs": s.runs,
                       "scored": s.scored, "wrong": s.wrong, "missed": s.missed, "false_alarm": s.false_alarm,
                       "disagree": round(s.disagree, 4), "value_mean": s.value_mean, "value_sd": s.value_sd,
                       "score_mean": s.score_mean, "classes": s.classes.most_common()}
                if not compact:
                    row["image"] = images.get(item)
                    row["calls"] = [c.get(item) for c in d["columns"]]
                out.append(row)
            return {"set": eval_set, "value": d["value"], "values": d["values"],
                    "runs": [{"slug": slug, "step": step} for slug, step in d["runs"]], "total": len(found), "rows": out}

    def dataset_summary(self, project, eval_set, slugs, filters=None, by=None, value=None) -> dict:
        """Counts behind the page: presets, filter values, how many runs get each sample wrong, run-to-run agreement."""
        f = {k: v for k, v in (filters or {}).items() if v not in (None, "") and k != "preset"}
        with self.connect() as conn:
            d = self._dataset(conn, project, eval_set, slugs, value or "")
            mask, groups, n = self._dataset_filter(conn, d, f), d["groups"], len(d["runs"])
            scored = mask & groups["scored"]
            hist = Counter(d["stats"][p].wrong for p in _positions(scored))
            most = groups["most_wrong"]

            def counted(masks: dict, within=d["all"], top=400):
                found = [[v, (m & within).bit_count(), (m & within & most).bit_count()] for v, m in masks.items()]
                return sorted((x for x in found if x[1]), key=lambda x: (-x[2], -x[1], x[0]))[:top]
            by = by if by in d["facts"] else next(iter(sorted(d["facts"], key=lambda k: -len(d["facts"][k]))), None)
            if scored:  # two runs agree on a sample when both are right or both are wrong
                same = [[((d["has"][a] & d["has"][b] & scored).bit_count(),
                          ((d["wrong"][a] ^ d["wrong"][b]) & d["has"][a] & d["has"][b] & scored).bit_count())
                         for b in range(n)] for a in range(n)]
                agreement = [[round(1 - differ / both, 4) if both else None for both, differ in row] for row in same]
            else:  # no truth to be right about: they agree when they predict the same class
                bits = self._dataset_memo(d["set_id"], ("class-bits", tuple(d["runs"])), lambda: [
                    {c: _mask(p, len(d["items"])) for c, p in by_class.items()} for by_class in (
                        _group((d["at"][item], call[1]) for item, call in column.items() if call[1])
                        for column in d["columns"])])
                agreement = [[round(sum((m & bits[b].get(c, 0) & mask).bit_count() for c, m in bits[a].items())
                                    / both, 4) if (both := (d["has"][a] & d["has"][b] & mask).bit_count()) else None
                              for b in range(n)] for a in range(n)]
            return {"set": eval_set, "value": d["value"], "values": d["values"], "samples": len(d["items"]),
                    "runs": [{"slug": slug, "step": step} for slug, step in d["runs"]],
                    "total": mask.bit_count(), "scored": scored.bit_count(),
                    "presets": {name: (mask & groups[name]).bit_count() for name in PRESETS},
                    "wrong_hist": [hist.get(k, 0) for k in range(n + 1)],
                    "class_true": counted(d["class_true"]),
                    "class_pred": sorted(set().union(*({c[1] for c in col.values()} for col in d["columns"])) - {""}),
                    "facts": {k: counted(v) for k, v in sorted(d["facts"].items())},
                    "by": by, "groups": counted(d["facts"][by], mask, 12) if by else [], "agreement": agreement}


def _any(masks) -> int:
    out = 0
    for m in masks:
        out |= m
    return out


def _group(pairs) -> dict:
    out: dict = {}
    for pos, key in pairs:
        out.setdefault(key, []).append(pos)
    return out
