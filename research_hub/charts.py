"""Charts logged to a run: a kind, columns of data, and which column plays which role.

The hub stores the data, not a picture, so the dashboard can draw it in its own theme, show values on hover and
put the same chart from several runs side by side. A chart logged at several steps keeps every step.
"""

from __future__ import annotations

import json
import math
import zlib

from .core import HubError, NotFound, choice, now, rows
from .runs import METRIC_KEY

# kind -> the roles ("channels") it cannot be drawn without
KINDS = {
    "line": ("x", "y"), "area": ("x", "y"), "scatter": ("x", "y"), "bar": ("x", "y"), "pie": ("label", "value"),
    "histogram": ("low", "high", "value"), "box": ("low", "q1", "median", "q3", "high"),
    "violin": ("group", "y", "density"), "heatmap": ("x", "y", "value"), "table": (),
}
CHANNELS = ("x", "y", "color", "size", "text", "label", "value", "group", "low", "high", "q1", "median", "q3",
            "outlier", "density")
MAX_ROWS = 50_000
MAX_COLUMNS = 64
MAX_BYTES = 8 * 1024 * 1024
MAX_HISTORY = 120


def _cell(v, where):
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            raise HubError(f"{where} holds a non-finite number; send null instead")
        return v
    if isinstance(v, str):
        if len(v) > 2000:
            raise HubError(f"{where} holds a string longer than 2000 characters")
        return v
    raise HubError(f"{where} must hold numbers, strings, booleans or null, got {type(v).__name__}")


def normalise_chart(chart) -> dict:
    """Check a chart sent by a client and return the form that is stored."""
    if not isinstance(chart, dict):
        raise HubError("chart must be an object with kind, data.columns and encoding")
    kind = choice(chart.get("kind"), tuple(KINDS), "chart kind")
    columns = (chart.get("data") or {}).get("columns")
    if not isinstance(columns, dict) or not columns or len(columns) > MAX_COLUMNS:
        raise HubError(f"chart data.columns must be an object of 1 to {MAX_COLUMNS} named columns")
    lengths = set()
    for name, values in columns.items():
        if not isinstance(name, str) or not name or len(name) > 120:
            raise HubError("column names must be strings of 1 to 120 characters")
        if not isinstance(values, list):
            raise HubError(f"column {name!r} must be a list")
        lengths.add(len(values))
        for v in values:
            _cell(v, f"column {name!r}")
    if len(lengths) != 1:
        raise HubError("every column of a chart must have the same number of rows")
    n = lengths.pop()
    if n > MAX_ROWS:
        raise HubError(f"a chart holds at most {MAX_ROWS} rows, got {n}; sample or aggregate it first")
    encoding = chart.get("encoding") or {}
    if not isinstance(encoding, dict):
        raise HubError("chart encoding must be an object of channel -> column name")
    for channel, column in encoding.items():
        choice(channel, CHANNELS, "encoding channel")
        if column not in columns:
            raise HubError(f"encoding {channel!r} names column {column!r}, which is not in the data")
    missing = [c for c in KINDS[kind] if c not in encoding]
    if missing:
        raise HubError(f"a {kind} chart needs encoding for {missing}")
    options = chart.get("options") or {}
    if not isinstance(options, dict) or len(json.dumps(options)) > 65536:
        raise HubError("chart options must be an object of at most 64 KB")
    title = chart.get("title") or ""
    if not isinstance(title, str) or len(title) > 200:
        raise HubError("chart title must be a string of at most 200 characters")
    return {"kind": kind, "title": title.strip(), "data": {"columns": columns}, "encoding": encoding, "options": options,
            "rows": n}


class Charts:
    def log_chart(self, actor, run_slug, name, chart, step=None) -> dict:
        """Store a chart on a run. The same name at a new step adds a version; at the same step it replaces."""
        if not isinstance(name, str) or not METRIC_KEY.fullmatch(name):
            raise HubError("chart name must be 1 to 80 letters, digits, _ . / -")
        spec = normalise_chart(chart)
        try:
            step = -1 if step is None else int(step)
        except (TypeError, ValueError):
            raise HubError("chart step must be an integer") from None
        raw = json.dumps(spec, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_BYTES:
            raise HubError(f"chart {name!r} is {len(raw) // 1024} KB; the limit is {MAX_BYTES // 1024} KB")
        sha = self.db.put_blob(zlib.compress(raw, 6))
        ts = now()
        with self.connect(write=True) as conn:
            self._writable(conn, actor, run_slug)
            conn.execute("INSERT OR REPLACE INTO charts VALUES(?,?,?,?,?,?,?,?)",
                         (run_slug, name, step, spec["kind"], spec["title"], sha, spec["rows"], ts))
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (ts, run_slug))
        return {"name": name, "step": None if step < 0 else step, "kind": spec["kind"], "rows": spec["rows"]}

    @staticmethod
    def _chart_index(conn, run_slug) -> list[dict]:
        out: dict[str, dict] = {}
        for r in conn.execute("SELECT name,step,kind,title,n_rows FROM charts WHERE run=? ORDER BY name, step", (run_slug,)):
            entry = out.setdefault(r["name"], {"name": r["name"], "steps": []})
            entry.update(kind=r["kind"], title=r["title"], rows=r["n_rows"])  # the latest step describes the chart
            if r["step"] >= 0:
                entry["steps"].append(r["step"])
        return list(out.values())

    def charts(self, run_slug) -> list[dict]:
        """Every chart on a run: name, kind, title and the steps it was logged at."""
        with self.connect() as conn:
            self._load_run(conn, run_slug)
            return self._chart_index(conn, run_slug)

    def _read_chart(self, sha) -> dict:
        path = self.db.blob_path(sha)
        if not path:
            raise NotFound("the chart's data is missing from the blob store")
        return json.loads(zlib.decompress(path.read_bytes()))

    def chart(self, run_slug, name, step=None, history=False) -> dict:
        """One chart at a step (the latest when omitted). ``history`` adds every step, thinned to at most 120."""
        with self.connect() as conn:
            self._load_run(conn, run_slug)
            versions = rows(conn.execute("SELECT step, blob_sha FROM charts WHERE run=? AND name=? ORDER BY step",
                                         (run_slug, name)))
        if not versions:
            raise NotFound(f"run {run_slug} has no chart named {name!r}")
        try:
            wanted = versions[-1]["step"] if step in (None, "") else int(step)
        except ValueError:
            raise HubError("step must be an integer") from None
        chosen = next((v for v in versions if v["step"] == wanted), None)
        if not chosen:
            raise NotFound(f"chart {name!r} was not logged at step {wanted}")
        out = {"name": name, "step": None if wanted < 0 else wanted, "steps": [v["step"] for v in versions if v["step"] >= 0],
               **self._read_chart(chosen["blob_sha"])}
        if history:
            kept = versions[::max(1, math.ceil(len(versions) / MAX_HISTORY))]
            if kept[-1] is not versions[-1]:
                kept.append(versions[-1])
            out["history"] = [{"step": v["step"], **self._read_chart(v["blob_sha"])} for v in kept]
        return out

    def compare_charts(self, slugs: list[str]) -> list[dict]:
        """Charts that two or more of the given runs logged under the same name."""
        slugs = [s for s in slugs if s][:8]
        by_name: dict[str, dict] = {}
        with self.connect() as conn:
            for s in slugs:
                self._load_run(conn, s)
                for c in self._chart_index(conn, s):
                    by_name.setdefault(c["name"], {"name": c["name"], "kind": c["kind"], "title": c["title"], "runs": []})
                    by_name[c["name"]]["runs"].append(s)
        return [c for c in by_name.values() if len(c["runs"]) > 1]
