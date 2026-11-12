"""Python API for logging to the hub. Standard library only; Pillow and numpy are used when present.

    from research_hub import hub
    run = hub.init(project="detectors", name="yolo-n-baseline", config={"lr": 1e-3}, dataset="coco8@1.0")
    run.log({"val/map50": 0.71, "train/loss": 0.41}, step=1000, epoch=2)
    run.log_images(["worst_0412.png"], step=1000, epoch=2, sample="0412", role="failure", caption="missed a small box")
    run.log_eval(rows, step=1000, epoch=2, eval_set="coco8@1.0:val")
    run.log_chart("eval/roc", hub.plots.roc_curve(y_true, y_score))        # see research_hub/plots.py
    run.log_histogram("weights/head", model.head.weight, step=1000)
    run.log_table("predictions", dataframe)
    run.note("resumed from last.ckpt")
    run.summary({"val/map50": 0.73})
    run.finish(conclusion="…")

In a job that only has HUB_URL / HUB_RUN / HUB_TOKEN (a run's ingest token), use ``hub.init(resume=True)``.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import plots
from . import system as sysmetrics

DEFAULT_URL = "http://localhost:6230"
CRED_PATH = Path(os.environ.get("HUB_CREDENTIALS", "~/.config/research_hub/credentials.json")).expanduser()
SPOOL_DIR = Path(os.environ.get("HUB_SPOOL", "~/.cache/research_hub/spool")).expanduser()
EVAL_CHUNK = 1000
FLUSH_POINTS = 500     # metric points buffered before they are sent ...
FLUSH_SECONDS = 2.0    # ... or this long since the last send, whichever comes first
UPLOAD_BYTES = 24 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}")


class HubRequestError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


# ------------------------------------------------------------------ credentials
def _load_creds() -> dict:
    try:
        return json.loads(CRED_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_token(url: str, name: str, token: str) -> Path:
    creds = _load_creds()
    creds.setdefault(url, {})[name] = token
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.touch(mode=0o600)
    CRED_PATH.write_text(json.dumps(creds, indent=2))
    return CRED_PATH


def resolve_token(url: str, name: str | None = None) -> str | None:
    """HUB_TOKEN wins; otherwise the saved token for HUB_AGENT (or the only saved identity) at this URL."""
    if os.environ.get("HUB_TOKEN"):
        return os.environ["HUB_TOKEN"]
    saved = _load_creds().get(url, {})
    name = name or os.environ.get("HUB_AGENT")
    if name:
        return saved.get(name)
    return next(iter(saved.values())) if len(saved) == 1 else None


class Hub:
    """Thin JSON client. ``project`` is sent on every call so project-scoped routes need no query parameter."""

    def __init__(self, url: str | None = None, token: str | None = None, project: str | None = None, timeout=30):
        self.url = (url or os.environ.get("HUB_URL") or DEFAULT_URL).rstrip("/")
        self.token = token or resolve_token(self.url)
        self.project = project or os.environ.get("HUB_PROJECT")
        self.timeout = timeout

    def request(self, method: str, path: str, body=None, query=None, headers=None):
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if self.project:
            req.add_header("X-Hub-Project", self.project)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read()).get("error", e.reason)
            except ValueError:
                message = e.reason
            raise HubRequestError(e.code, message) from None

    def get(self, path, **query):
        return self.request("GET", path, query=query)

    def post(self, path, body=None):
        return self.request("POST", path, body or {})

    def put(self, path, body):
        return self.request("PUT", path, body)

    def patch(self, path, body):
        return self.request("PATCH", path, body)

    def delete(self, path):
        return self.request("DELETE", path)

    def blob(self, sha: str) -> tuple[bytes, str]:
        """A logged file by its id: (bytes, content type)."""
        req = urllib.request.Request(f"{self.url}/blobs/{sha}", headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read(), resp.headers.get_content_type()
        except urllib.error.HTTPError as e:
            raise HubRequestError(e.code, f"file {sha[:12]} could not be read: {e.reason}") from None


# -------------------------------------------------------------------- provenance
def _git(args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _clean_remote(url: str) -> str:
    url = re.sub(r"^git@([^:]+):", r"https://\1/", url)
    return re.sub(r"\.git$", "", url)


def git_provenance(config_path: str | Path, allow_unpushed: bool = False) -> dict:
    """Branch, commit, repo and the committed text of ``config_path``. Refuses uncommitted or unpushed code."""
    path = Path(config_path).resolve()
    if not path.exists():
        raise RuntimeError(f"config file {path} does not exist")
    root = Path(_git(["rev-parse", "--show-toplevel"], path.parent))
    rel = path.relative_to(root).as_posix()
    try:
        committed = _git(["cat-file", "-p", f"HEAD:{rel}"], root)
    except subprocess.CalledProcessError:
        raise RuntimeError(f"{rel} is not committed on HEAD; commit it (git add {rel} && git commit)") from None
    if committed != path.read_text():
        raise RuntimeError(f"{rel} has uncommitted changes; commit them so the run is reproducible")
    dirty = _git(["status", "--porcelain", "--untracked-files=no"], root)
    if dirty:
        raise RuntimeError(f"tracked files have uncommitted changes; commit or stash them first:\n{dirty}")
    commit = _git(["rev-parse", "HEAD"], root)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    repo = ""
    try:
        repo = _clean_remote(_git(["remote", "get-url", "origin"], root))
    except subprocess.CalledProcessError:
        pass
    if not allow_unpushed:
        try:
            upstream = _git(["rev-parse", "--abbrev-ref", "@{upstream}"], root)
            if _git(["rev-list", "--count", f"{upstream}..HEAD"], root) != "0":
                raise RuntimeError(f"HEAD is ahead of {upstream}; push first so others can check out the commit")
        except subprocess.CalledProcessError:
            raise RuntimeError(f"branch {branch} has no upstream; push it (git push -u origin {branch})") from None
    return {"branch": branch, "commit_sha": commit, "config_path": rel, "config_text": committed, "repo": repo}


# ---------------------------------------------------------------------- the run
def _scalar(v):
    if hasattr(v, "item"):  # numpy scalars, 0-d tensors
        v = v.item()
    if isinstance(v, bool):
        return float(v)
    v = float(v)
    return v if v == v and abs(v) != float("inf") else None


def _flatten(metrics: dict, prefix="") -> dict:
    out = {}
    for k, v in metrics.items():
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}/"))
        else:
            s = _scalar(v)
            if s is not None:
                out[f"{prefix}{k}"] = s
    return out


def init(name: str | None = None, *, project: str | None = None, title: str | None = None, config=None,
         category: str | None = None, parent: str | None = None, dataset: str | None = None, resume: bool = False,
         hub: Hub | None = None, allow_unpushed: bool = False, system=None, system_interval: float | None = None,
         **fields) -> Run:
    """Register a run and return a Run to log to. Like ``wandb.init``.

    ``config`` is a dict (stored as the config snapshot) or a path to a committed config file (git provenance is
    recorded from it). Extra ``fields`` are run fields: summary, hypothesis, rationale, expected, topics, pinned,
    app, command, output_dataset, motivated_by. ``resume=True`` attaches to ``name`` (or HUB_RUN) instead.

    ``system=True`` samples CPU, memory, GPU and CPU temperature in the background every ``system_interval``
    seconds (default 15); pass a list such as ``["gpu", "cpu"]`` to pick. HUB_SYSTEM and HUB_SYSTEM_INTERVAL
    set the same from the environment. See ``research_hub/system.py``.
    """
    wanted = sysmetrics.parts(os.environ.get("HUB_SYSTEM") if system is None else system)
    interval = system_interval or float(os.environ.get("HUB_SYSTEM_INTERVAL") or 15)
    hub = hub or Hub(project=project)
    if resume:
        slug = name or os.environ.get("HUB_RUN")
        if not slug:
            raise RuntimeError("resume needs a run name or HUB_RUN")
        run = Run(slug, hub)
        state = run._send("PATCH", f"/api/runs/{slug}", {"status": "running"}, spool=False, quiet=True) or {}
        began = state.get("started") or state.get("created")
        run._watch_system(wanted, interval, datetime.fromisoformat(began).timestamp() if began else time.time())
        return run
    if not name:  # the script's name plus the time, e.g. train-yolo-20260301-141502
        stem = re.sub(r"[^a-z0-9]+", "-", Path(sys.argv[0] or "run").stem.lower()).strip("-") or "run"
        name = f"{stem[:60]}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    body = {"slug": name, "title": title or name, "status": "running", "category": category, "parent": parent,
            "dataset": dataset, "command": " ".join(shlex.quote(a) for a in sys.argv), **fields}
    if project:
        body["project"] = project
    if isinstance(config, (str, Path)):
        body.update(git_provenance(config, allow_unpushed))
    elif config is not None:
        body["config"] = config
    body = {k: v for k, v in body.items() if v is not None}
    created = hub.post("/api/runs", body)
    run = Run(created["slug"], hub)
    run.ingest_token = created["ingest_token"]  # for a subprocess or job that should only log to this run
    run._watch_system(wanted, interval, time.time())
    return run


class Run:
    """Logs to one run. Network failures are spooled to disk and replayed later, so a hub outage never kills training."""

    def __init__(self, slug: str, hub: Hub):
        self.slug = slug
        self.hub = hub
        self.ingest_token = None
        self.spool = SPOOL_DIR / f"{slug}.jsonl"
        self._warned = False
        self._monitor = None
        self._points: list[dict] = []   # metric points waiting to be sent
        self._sent_at = 0.0
        atexit.register(self.flush)

    def _watch_system(self, wanted, interval, started):
        if wanted:
            self._monitor = sysmetrics.Monitor(self._log_system, wanted, interval, started)
            self._monitor.start()

    def _log_system(self, values: dict, seconds: int):
        """Called from the monitor thread: best effort, never spooled, so it cannot disturb the training thread."""
        points = [{"key": k, "step": seconds, "value": v} for k, v in values.items()]
        try:
            self.hub.request("POST", f"/api/runs/{self.slug}/metrics", {"points": points})
        except (HubRequestError, urllib.error.URLError, TimeoutError, OSError):
            pass

    def _send(self, method, path, body, spool=True, quiet=False):
        if not path.endswith("/metrics"):
            self.flush()  # keep the order: buffered metrics go before anything else, and before the run closes
        self._flush()
        for attempt in range(3):
            try:
                return self.hub.request(method, path, body)
            except HubRequestError as e:
                if e.status in (400, 401, 403, 404, 409):
                    if quiet:
                        return None
                    raise
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(1.5 * (attempt + 1))
        if spool:
            self.spool.parent.mkdir(parents=True, exist_ok=True)
            with self.spool.open("a") as f:
                f.write(json.dumps({"method": method, "path": path, "body": body}) + "\n")
            if not self._warned:
                print(f"[hub] {self.hub.url} unreachable; spooling to {self.spool}", file=sys.stderr)
                self._warned = True
        return None

    def _flush(self):
        if not self.spool.exists():
            return
        pending = self.spool.read_text().splitlines()
        keep = []
        for i, line in enumerate(pending):
            item = json.loads(line)
            try:
                self.hub.request(item["method"], item["path"], item["body"])
            except HubRequestError:
                continue  # rejected for good; drop it
            except (urllib.error.URLError, TimeoutError, OSError):
                keep = pending[i:]
                break
        if keep:
            self.spool.write_text("\n".join(keep) + "\n")
        else:
            self.spool.unlink(missing_ok=True)

    def log(self, metrics: dict, step: int, epoch: int | None = None):
        """Log scalars at a step. Nested dicts flatten to ``a/b`` keys; numpy and tensor scalars are accepted."""
        flat = _flatten(metrics)
        if epoch is not None:
            flat["epoch"] = float(epoch)
        self._points += [{"key": k, "step": int(step), "value": v} for k, v in flat.items()]
        if len(self._points) >= FLUSH_POINTS or time.monotonic() - self._sent_at >= FLUSH_SECONDS:
            self.flush()

    def flush(self):
        """Send buffered metrics now. Logging every step costs one request every two seconds, not one per step;
        everything is also sent before any other call on the run and when the program exits."""
        if self._points:
            points, self._points = self._points, []
            self._sent_at = time.monotonic()
            self._send("POST", f"/api/runs/{self.slug}/metrics", {"points": points})

    def log_images(self, paths, step=None, epoch=None, caption="", sample="", role="", kind="image"):
        """Upload visuals. ``sample`` (a stable id) and ``role`` 'tracked'|'failure' place them on the checkpoint slider."""
        for path in ([paths] if isinstance(paths, (str, Path)) else paths):
            path = Path(path)
            self._send("POST", f"/api/runs/{self.slug}/artifacts",
                       {"name": path.name, "data": base64.b64encode(path.read_bytes()).decode(), "kind": kind,
                        "step": step, "epoch": epoch, "caption": caption, "sample": sample, "role": role})

    def log_file(self, path, caption="", step=None):
        self.log_images(path, step=step, caption=caption, kind="file")

    def log_eval(self, rows: list[dict], step: int, eval_set: str, epoch: int | None = None, negatives=None,
                 base_dir=None) -> dict | None:
        """Per-sample results for one checkpoint; see ``log_eval`` below for the row format."""
        self.flush()
        try:
            return log_eval(self.hub, self.slug, eval_set, step, rows, epoch, negatives, base_dir)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"[hub] eval upload for step {step} failed ({e}); re-run it when the hub is back", file=sys.stderr)
            return None

    def log_chart(self, name: str, chart: dict, step: int | None = None):
        """Log a chart built with ``research_hub.plots``. A new ``step`` adds a version; the same step replaces it."""
        return self._send("POST", f"/api/runs/{self.slug}/charts", {"name": name, "step": step, "chart": chart})

    def log_table(self, name: str, data, columns=None, step: int | None = None):
        """Log a table: a DataFrame, a dict of columns, a list of dicts, or a 2-D array with ``columns`` names."""
        return self.log_chart(name, plots.table(data, columns), step)

    def log_histogram(self, name: str, values, step: int | None = None, bins: int = 64):
        """Log the distribution of an array or tensor (weights, gradients, scores); log it per step to watch it move."""
        return self.log_chart(name, plots.histogram(value=values, bins=bins), step)

    def log_figure(self, name: str, figure, step: int | None = None, caption: str = ""):
        """Log a matplotlib figure as a picture. Charts logged with ``log_chart`` stay interactive; this does not."""
        if not hasattr(figure, "savefig"):
            raise TypeError("log_figure takes a matplotlib figure; build other charts with research_hub.plots")
        out = io.BytesIO()
        figure.savefig(out, format="png", dpi=144, bbox_inches="tight")
        return self._send("POST", f"/api/runs/{self.slug}/artifacts",
                          {"name": f"{name.replace('/', '-')}.png", "data": base64.b64encode(out.getvalue()).decode(),
                           "kind": "plot", "step": step, "caption": caption or name})

    def watch(self, model, name: str = "model"):
        """Log a PyTorch model's architecture from its first training step: layers, shapes, connections, losses.

        Call once before training. Nothing extra is run and the hooks are removed after that step. See
        ``research_hub/modelgraph.py``.
        """
        from . import modelgraph  # imported here because it needs torch
        modelgraph.watch(model, lambda graph: self.log_model_graph(graph, name))

    def log_model_graph(self, graph: dict, name: str = "model"):
        """Log a graph captured by hand with ``research_hub.modelgraph.Trace``."""
        return self._send("POST", f"/api/runs/{self.slug}/model-graph", {"name": name, "graph": graph})

    def set_config(self, config: dict):
        """Store (or replace) the run's config snapshot; used when the config is only known after ``init``."""
        return self._send("PATCH", f"/api/runs/{self.slug}", {"config": config})

    def note(self, body: str):
        return self._send("POST", f"/api/runs/{self.slug}/notes", {"body": body})

    def summary(self, values: dict, direction: str = "max"):
        """Final or best values shown in tables and compared with the parent: {key: value or {value, direction}}."""
        spec = {k: v if isinstance(v, dict) else {"value": float(v), "direction": direction} for k, v in values.items()}
        return self._send("POST", f"/api/runs/{self.slug}/summary", spec)

    def finish(self, conclusion: str, status: str = "finished", verdict: str | None = None):
        if self._monitor:
            self._monitor.stop()
        body = {"status": status, "conclusion": conclusion}
        if verdict:
            body["verdict"] = verdict
        return self._send("PATCH", f"/api/runs/{self.slug}", body, spool=False)

    def fail(self, conclusion: str):
        return self.finish(conclusion, status="failed")


# ------------------------------------------------------------------ eval upload
def _pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


def encode_layer(src, kind: str) -> tuple[bytes, list[int] | None]:
    """Compact encoding for an eval image or layer, with the [width, height] it had before it was shrunk.

    kind 'image': the input image as WebP, max 512 px. 'map': a 0..1 prediction map as 8-bit PNG, max 192 px.
    'mask': a binary ground-truth mask as 1-bit PNG, max 512 px. 'raw': bytes sent unchanged (audio, files).
    ``src`` is a path, bytes, or a numpy array (HxW for map/mask, HxWx3 for image; floats in 0..1 or uint8).
    The size is None for bytes sent unchanged.
    """
    Image = _pil()
    if kind == "raw" or Image is None:
        if isinstance(src, (bytes, bytearray)):
            return bytes(src), None
        if isinstance(src, (str, Path)):
            return Path(src).read_bytes(), None
        raise RuntimeError("encoding arrays needs Pillow (pip install pillow)")
    if isinstance(src, (str, Path)):
        img = Image.open(src)
    elif isinstance(src, (bytes, bytearray)):
        img = Image.open(io.BytesIO(src))
    else:
        import numpy as np
        arr = np.asarray(src)
        if arr.dtype != np.uint8:
            arr = (np.clip(arr.astype("float32"), 0, 1) * 255).round().astype(np.uint8)
        img = Image.fromarray(arr.squeeze())
    size = list(img.size)
    out = io.BytesIO()
    if kind == "image":
        img = img.convert("RGB")
        img.thumbnail((512, 512))
        img.save(out, "WEBP", quality=80)
    elif kind == "mask":
        img = img.convert("L")
        img.thumbnail((512, 512), Image.NEAREST)
        img.point(lambda v: 255 if v >= 128 else 0).convert("1").save(out, "PNG", optimize=True)
    else:
        img = img.convert("L")
        img.thumbnail((192, 192), Image.BILINEAR)
        img.save(out, "PNG", optimize=True)
    return out.getvalue(), size


def upload_blobs(hub: Hub, blobs: dict) -> None:
    """Upload {sha: bytes} the hub does not have yet, in batches."""
    shas = list(blobs)
    missing = []
    for i in range(0, len(shas), 5000):
        missing += hub.post("/api/blobs/missing", {"shas": shas[i:i + 5000]})["missing"]
    batch, size = [], 0
    for sha in missing:
        data = blobs[sha]
        if batch and (size + len(data) > UPLOAD_BYTES or len(batch) >= 400):
            hub.post("/api/blobs", {"files": batch})
            batch, size = [], 0
        batch.append(base64.b64encode(data).decode())
        size += len(data) * 4 // 3
    if batch:
        hub.post("/api/blobs", {"files": batch})


def _collect_layers(row: dict, base_dir, blobs: dict) -> dict:
    """Encode a row's image/audio/masks/heatmaps into ``blobs`` and replace them in the row with blob ids.

    The image is stored shrunk, so the row also gets ``size``: the image's own [width, height], which is what
    box coordinates are measured in."""
    def ref(src, kind):
        if isinstance(src, str) and SHA.fullmatch(src):
            return src
        if isinstance(src, (str, Path)) and base_dir and not Path(src).is_absolute():
            src = Path(base_dir) / src
        data, size = encode_layer(src, kind)
        if kind == "image" and size:
            row.setdefault("size", size)
        sha = hashlib.sha256(data).hexdigest()
        blobs[sha] = data
        return sha

    for side, group, kind in (("true", "masks", "mask"), ("pred", "masks", "map"), ("pred", "heatmaps", "map")):
        part = row.get(side) or {}
        if part.get(group):
            row[side] = {**part, group: {n: ref(src, kind) for n, src in part[group].items() if src is not None}}
    for key, kind in (("image", "image"), ("audio", "raw")):
        if row.get(key) is not None:
            row[key] = ref(row[key], kind)
    return row


def log_eval(hub: Hub, slug: str, eval_set: str, step: int, rows: list[dict], epoch: int | None = None,
             negatives=None, base_dir=None) -> dict:
    """Log one checkpoint's per-sample results for an eval set.

    Row: {"sample": <stable id>, "facts": {"camera": "c2", "site": "north"},  # any keys, every one a filter
          "image": path|bytes|array,                                          # stored once per sample
          "size": [width, height],                    # of the image boxes are measured in; filled in from "image"
          "true": {"class": "cat", "value": 4, "boxes": [[x,y,w,h,label]], "masks": {"object": mask}, "text": "…"},
          "pred": {"class": "dog", "score": 0.9, "value": 3.2, "boxes": [[x,y,w,h,label,score]],
                   "masks": {"object": prob_map}, "heatmaps": {"attention": map}, "text": "…"},
          "error": 1.4, "metrics": {"dice": 0.71}}
    Boxes are in pixels of the image you pass, whatever size it is stored at.
    The hub derives the outcome (correct / missed / false alarm / wrong class / mismatch) from what is present.
    Uploads are content-addressed: an image or mask sent twice costs nothing the second time.
    """
    totals: dict[str, int] = {}
    logged = 0
    for start in range(0, len(rows), EVAL_CHUNK):
        blobs: dict = {}
        chunk = [_collect_layers(dict(r), base_dir, blobs) for r in rows[start:start + EVAL_CHUNK]]
        if blobs:
            upload_blobs(hub, blobs)
        result = hub.post(f"/api/runs/{slug}/eval", {"set": eval_set, "step": int(step), "epoch": epoch, "rows": chunk,
                                                      "negatives": negatives})
        logged += result["logged"]
        for k, v in result["outcomes"].items():
            totals[k] = totals.get(k, 0) + v
    return {"logged": logged, "set": eval_set, "step": int(step), "outcomes": totals}
