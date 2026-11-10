"""Model graphs logged to a run: the layers, connections and losses captured from one training step."""

from __future__ import annotations

import json
import math
import zlib

from .core import HubError, NotFound, choice, now
from .runs import METRIC_KEY

KINDS = ("input", "module", "op", "loss")
TEXT = ("name", "type", "group", "detail", "loss", "dtype")
NUMBERS = ("act_mean", "act_std", "grad_norm", "value")
MAX_NODES, MAX_EDGES = 5000, 20000


def _shape(value, what):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 12 or any(not isinstance(d, int) or isinstance(d, bool) for d in value):
        raise HubError(f"{what} must be a list of at most 12 integers")
    return value


def normalise_graph(graph) -> dict:
    """Check a graph sent by a client and return the form that is stored: known fields only."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise HubError("model graph must be an object with nodes and edges")
    if not 0 < len(graph["nodes"]) <= MAX_NODES or len(graph["edges"]) > MAX_EDGES:
        raise HubError(f"a model graph holds 1 to {MAX_NODES} nodes and at most {MAX_EDGES} edges")
    nodes, ids = [], set()
    for n in graph["nodes"]:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not 0 < len(n["id"]) <= 300 or n["id"] in ids:
            raise HubError("every node needs a unique string id of at most 300 characters")
        ids.add(n["id"])
        node = {"id": n["id"], "kind": choice(n.get("kind"), KINDS, "node kind")}
        for key in TEXT:
            if n.get(key) not in (None, ""):
                if not isinstance(n[key], str) or len(n[key]) > 300:
                    raise HubError(f"node {key} must be a string of at most 300 characters")
                node[key] = n[key]
        for key in NUMBERS:
            if n.get(key) is not None:
                if isinstance(n[key], bool) or not isinstance(n[key], (int, float)) or not math.isfinite(n[key]):
                    raise HubError(f"node {key} must be a finite number")
                node[key] = n[key]
        if n.get("params"):
            if not isinstance(n["params"], int) or n["params"] < 0:
                raise HubError("node params must be a non-negative integer")
            node["params"] = n["params"]
        if n.get("out_shape") is not None:
            node["out_shape"] = _shape(n["out_shape"], "out_shape")
        if n.get("in_shapes"):
            if not isinstance(n["in_shapes"], list) or len(n["in_shapes"]) > 32:
                raise HubError("in_shapes must be a list of at most 32 shapes")
            node["in_shapes"] = [_shape(s, "in_shapes") for s in n["in_shapes"]]
        nodes.append(node)
    edges = []
    for e in graph["edges"]:
        if not isinstance(e, dict) or e.get("from") not in ids or e.get("to") not in ids:
            raise HubError("every edge must run between two nodes of the graph")
        edges.append({"from": e["from"], "to": e["to"], "shape": _shape(e.get("shape"), "edge shape")})
    blocks = graph.get("blocks") or {}
    if not isinstance(blocks, dict) or len(blocks) > MAX_NODES or any(
            not isinstance(k, str) or not isinstance(v, str) or len(k) > 300 or len(v) > 120 for k, v in blocks.items()):
        raise HubError("blocks must map block names to class names")
    out = {"model": str(graph.get("model") or "")[:120], "nodes": nodes, "edges": edges, "blocks": blocks}
    for key in ("params", "trainable"):
        value = graph.get(key) or 0
        if not isinstance(value, int) or value < 0:
            raise HubError(f"{key} must be a non-negative integer")
        out[key] = value
    return out


class Graphs:
    def log_model_graph(self, actor, run_slug, name, graph) -> dict:
        """Store a model graph on a run; logging the same name again replaces it."""
        name = name or "model"
        if not isinstance(name, str) or not METRIC_KEY.fullmatch(name):
            raise HubError("graph name must be 1 to 80 letters, digits, _ . / -")
        graph = normalise_graph(graph)
        sha = self.db.put_blob(zlib.compress(json.dumps(graph, separators=(",", ":"), allow_nan=False).encode(), 6))
        ts = now()
        with self.connect(write=True) as conn:
            self._writable(conn, actor, run_slug)
            conn.execute("INSERT OR REPLACE INTO model_graphs VALUES(?,?,?,?,?,?)",
                         (run_slug, name, sha, len(graph["nodes"]), graph["params"], ts))
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (ts, run_slug))
        return {"name": name, "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}

    def model_graph(self, run_slug, name=None) -> dict:
        with self.connect() as conn:
            self._load_run(conn, run_slug)
            row = conn.execute("SELECT name, blob_sha FROM model_graphs WHERE run=? AND (name=? OR ? IS NULL) ORDER BY name",
                               (run_slug, name, name)).fetchone()
        path = self.db.blob_path(row["blob_sha"]) if row else None
        if not path:
            raise NotFound(f"run {run_slug} has no model graph" + (f" named {name!r}" if name else ""))
        return {"name": row["name"], **json.loads(zlib.decompress(path.read_bytes()))}
