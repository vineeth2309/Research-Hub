"""The hub as MCP tools, for agents that review and discuss work but have no shell: ``hub mcp``.

Speaks the Model Context Protocol over stdio (one JSON-RPC message per line) and is a thin layer over the same
HTTP API and API key as the CLI, so access rules and the audit log are unchanged. It reads HUB_URL, HUB_TOKEN and
HUB_PROJECT; run one copy per agent, with that agent's own key. Tools cover reading, reviewing and discussing.
Training code keeps logging through the Python client, and nothing here can delete or manage access.
"""

from __future__ import annotations

import base64
import json
import sys

from . import __version__
from .cli import _fmt_design, _fmt_inbox, _fmt_run, _fmt_runs, _fmt_samples
from .client import Hub, HubRequestError

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXT = 20_000
MAX_IMAGES = 4
INSTRUCTIONS = ("Research Hub: experiment tracking shared by people and AI agents. Start a session with `inbox`, then "
                "`handbook`. Answer open feedback on your runs before starting new work. Log training results from "
                "code with the Python client (research_hub.hub), not through these tools.")


def _s(description, **extra):
    return {"type": "string", "description": description, **extra}


def _schema(required=(), **properties):
    return {"type": "object", "properties": properties, "required": list(required)}


RUN = _s("Run name (slug)")
DESIGN = {"type": "object", "description": (
    "{nodes: [{id, kind: box|group|text, label, detail?, color?: blue|green|amber|red|violet, group?: <group id>}], "
    "edges: [{from, to, label?, dashed?}]}. Leave x, y, w, h off nodes you add.")}
TOOLS = {
    "inbox": ("What is waiting for you: open feedback on your runs, replies, @mentions and handbook changes.",
              _schema(ack={"type": "boolean", "description": "Mark mentions and replies as seen"})),
    "handbook": ("The project's rules: what it is for, which datasets and metrics matter, how runs are named.", _schema()),
    "run_list": ("Runs in the project, newest first.",
                 _schema(status=_s("planned, running, finished, failed or abandoned"), owner=_s("Account name"),
                         q=_s("Text to search for in titles and summaries"),
                         limit={"type": "integer", "description": "How many (default 20)"})),
    "run_get": ("One run: what it tested, its provenance, summary metrics, notes and every comment on it.",
                _schema(["run"], run=RUN)),
    "run_compare": ("Summary metrics and config differences of two to eight runs side by side.",
                    _schema(["runs"], runs={"type": "array", "items": {"type": "string"}, "description": "Run names"})),
    "samples": ("Per-sample evaluation results of a run, filtered and sorted. Use sample_image to look at one.",
                _schema(["run"], run=RUN, set=_s("Eval set name; optional when the run has only one"),
                        step={"type": "integer", "description": "Checkpoint step (default: the latest)"},
                        outcome=_s("correct, missed, false_alarm, wrong_class, mismatch or unscored"),
                        class_true=_s("True class"), class_pred=_s("Predicted class"),
                        facts={"type": "object", "description": "Facts to match exactly, e.g. {\"camera\": \"c2\"}"},
                        value_min={"type": "number"}, value_max={"type": "number"},
                        vs=_s("Another run to compare each sample against"),
                        vs_outcome=_s("Keep samples where the other run had this outcome"),
                        sort=_s("error (default), -error, score, -score or sample"),
                        limit={"type": "integer", "description": "How many (default 20, at most 100)"},
                        offset={"type": "integer"})),
    "reviews": ("People's reviews of the samples of an eval set: class, severity 0 to 10, category, difficulty, bad image, "
                "comment, reviewer, time. Only people write them. Class Healthy means not a defect.",
                _schema(["set"], set=_s("Eval set name"), since=_s("Only reviews written after this ISO time"),
                        history={"type": "boolean", "description": "Every review, not only the current one"})),
    "sample_image": ("Look at one evaluation sample: its image and up to three of its mask or heatmap layers, with "
                     "what was true and what the run predicted.",
                     _schema(["run", "sample"], run=RUN, sample=_s("Sample id, from samples"),
                             set=_s("Eval set name; optional when the run has only one"),
                             step={"type": "integer", "description": "Checkpoint step (default: the latest)"},
                             layers={"type": "array", "items": {"type": "string"},
                                     "description": "Layer names to show (default: the first three)"})),
    "comment": ("Comment on a run, post, design, sample or message. Replies answer a comment by its id.",
                _schema(["target", "body"], target=_s("run:<name>, post:<name>, design:<name>, sample:<run>/<set>/<sample> or message:<id>"),
                        body=_s("Markdown"), kind=_s("note (default), question, request, objection, support or response"),
                        reply_to={"type": "integer", "description": "Id of the comment being answered"},
                        anchor=_s("What exactly it is about, e.g. 'chart: val/loss, step 1100'"))),
    "resolve": ("Set a comment's status. Resolving a person's comment needs a reference to what answers it.",
                _schema(["id"], id={"type": "integer"}, status=_s("resolved (default), acknowledged or open"),
                        ref=_s("What answers it, e.g. run:<follow-up-run>"))),
    "note": ("Add a dated note to the timeline of one of your runs.", _schema(["run", "body"], run=RUN, body=_s("Text"))),
    "msg_read": ("Read a chat channel.",
                 _schema(channel=_s("Channel (default general)"), since={"type": "integer", "description": "Only after this message id"},
                         limit={"type": "integer", "description": "How many (default 30)"})),
    "msg_send": ("Post to a chat channel. @name reaches that account's inbox.",
                 _schema(["body"], channel=_s("Channel (default general)"), body=_s("Markdown"),
                         reply_to={"type": "integer", "description": "Message id to thread under"})),
    "design_list": ("Architecture boards of the project: boxes, groups and arrows that people and agents draw together.",
                    _schema()),
    "design_get": ("One design as an outline of its nodes and connections, with open proposals and comments. Set "
                   "json to get the nodes and edges to edit.",
                   _schema(["design"], design=_s("Design name (slug)"), json={"type": "boolean"},
                           rev={"type": "integer", "description": "An earlier revision (default: the latest)"})),
    "design_create": ("Start a new design. Nodes without x and y are laid out for you.",
                      _schema(["design", "title", "graph"], design=_s("New design name (slug)"), title=_s("Title"),
                              description=_s("What it is for"), graph=DESIGN)),
    "design_propose": ("Propose a changed design as its next revision. A person accepts or rejects it. Send the whole "
                       "design, starting from design_get with json.",
                       _schema(["design", "graph", "note"], design=_s("Design name (slug)"), graph=DESIGN,
                               note=_s("What changes and why"))),
    "search": ("Full-text search across runs, posts, comments and messages in the project.", _schema(["q"], q=_s("Words to find"))),
}


def _text(value) -> dict:
    text = value if isinstance(value, str) else json.dumps(value, indent=1, default=str)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f"\n… cut at {MAX_TEXT} characters; narrow the request"
    return {"type": "text", "text": text}


def _image(hub: Hub, sha: str) -> dict | None:
    data, mime = hub.blob(sha)
    return {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mime} if mime.startswith("image/") else None


def _eval_set(hub: Hub, run: str, wanted) -> str:
    if wanted:
        return wanted
    sets = [s["set"] for s in hub.get(f"/api/runs/{run}")["eval_sets"]]
    if len(sets) != 1:
        raise HubRequestError(400, f"say which eval set: {sets}" if sets else f"run {run} has no per-sample results")
    return sets[0]


def call(hub: Hub, name: str, a: dict) -> list[dict]:
    """Run one tool and return MCP content blocks."""
    if name == "inbox":
        box = hub.get("/api/inbox", project=hub.project)
        if a.get("ack"):
            hub.post("/api/inbox/ack")
        return [_text(_fmt_inbox(box) or "Nothing is waiting for you.")]
    if name == "handbook":
        h = hub.get("/api/handbook")
        return [_text(f"Handbook of {h['project']}, revision {h['rev']} by {h['author']}\n\n{h['text']}")]
    if name == "run_list":
        page = hub.get("/api/runs", status=a.get("status"), owner=a.get("owner"), q=a.get("q"), limit=a.get("limit", 20))
        return [_text(f"{_fmt_runs(page['runs'])}\n({page['total']} total)")]
    if name == "run_get":
        return [_text(_fmt_run(hub.get(f"/api/runs/{a['run']}")))]
    if name == "run_compare":
        res = hub.get("/api/compare", runs=",".join(a["runs"]))
        return [_text({"summary": res["summary"], "config_differences": res["config_diff"],
                       "curves_in_common": sorted(res["curves"])})]
    if name == "samples":
        q = {k: a.get(k) for k in ("step", "outcome", "class_true", "class_pred", "value_min", "value_max", "vs",
                                   "vs_outcome", "offset")}
        q.update({f"fact.{k}": v for k, v in (a.get("facts") or {}).items()})
        res = hub.get(f"/api/runs/{a['run']}/eval/samples", set=_eval_set(hub, a["run"], a.get("set")),
                      sort=a.get("sort", "error"), limit=min(int(a.get("limit", 20)), 100), **q)
        return [_text(_fmt_samples(res))]
    if name == "reviews":
        res = hub.get("/api/eval-sets/reviews", set=a["set"], since=a.get("since"), history="1" if a.get("history") else None)
        return [_text({"set": res["set"], "options": res["options"], "reviews": res["reviews"][:200],
                       "note": "cut at 200 reviews; use `hub review list --csv` for all" if len(res["reviews"]) > 200 else ""})]
    if name == "sample_image":
        eval_set = _eval_set(hub, a["run"], a.get("set"))
        s = hub.get(f"/api/runs/{a['run']}/eval/sample", set=eval_set, sample=a["sample"])
        steps = [x for x in s["steps"] if a.get("step") is None or x["step"] == a["step"]]
        if not steps:
            raise HubRequestError(404, f"no results at step {a.get('step')}; steps: {[x['step'] for x in s['steps']]}")
        at = steps[-1]
        layers = {**s["static_layers"], **at["layers"]}
        base = layers.pop("image", None)
        chosen = [n for n in (a.get("layers") or sorted(layers)) if n in layers][:MAX_IMAGES - 1]
        blocks = [_text({"sample": s["sample"], "set": eval_set, "step": at["step"], "facts": s["facts"],
                         "true": at["truth"] or s["truth"], "predicted": at["pred"], "outcome": at["outcome"],
                         "error": at["error"], "images_below": (["image"] if base else []) + chosen,
                         "other_layers": [n for n in sorted(layers) if n not in chosen]})]
        for sha in ([base] if base else []) + [layers[n] for n in chosen]:
            image = _image(hub, sha)
            if image:
                blocks.append(image)
        return blocks
    if name == "comment":
        c = hub.post("/api/comments", {"target": a["target"], "body": a["body"], "kind": a.get("kind", "note"),
                                       "anchor": a.get("anchor", ""), "parent_id": a.get("reply_to")})
        return [_text(f"Comment #{c['id']} posted on {a['target']}.")]
    if name == "resolve":
        c = hub.patch(f"/api/comments/{int(a['id'])}", {"status": a.get("status", "resolved"), "resolution_ref": a.get("ref", "")})
        return [_text(f"Comment #{c['id']} is now {c['status']}.")]
    if name == "note":
        hub.post(f"/api/runs/{a['run']}/notes", {"body": a["body"]})
        return [_text(f"Note added to {a['run']}.")]
    if name == "msg_read":
        channel = a.get("channel", "general")
        messages = hub.get(f"/api/channels/{channel}/messages", since=a.get("since", 0), limit=a.get("limit", 30))
        return [_text("\n".join(f"[{m['id']}] {m['created']} {m['author']}" + (f" (in thread {m['parent_id']})" if m["parent_id"] else "")
                                + f": {m['body']}" for m in messages) or f"#{channel} is empty.")]
    if name == "msg_send":
        m = hub.post(f"/api/channels/{a.get('channel', 'general')}/messages", {"body": a["body"], "parent_id": a.get("reply_to")})
        return [_text(f"Message {m['id']} sent to #{a.get('channel', 'general')}.")]
    if name == "design_list":
        return [_text("\n".join(f"{d['slug']}: {d['title']} (rev {d['rev']}, {d['n_nodes']} nodes, by {d['owner']})"
                                for d in hub.get("/api/designs")) or "No designs yet.")]
    if name == "design_get":
        d = hub.get(f"/api/designs/{a['design']}", rev=a.get("rev"))
        return [_text(d["graph"] if a.get("json") else _fmt_design(d))]
    if name == "design_create":
        d = hub.post("/api/designs", {"slug": a["design"], "title": a["title"], "description": a.get("description", ""),
                                      "graph": a["graph"]})
        return [_text(f"Design {d['slug']} created with {d['nodes']} nodes.")]
    if name == "design_propose":
        p = hub.post(f"/api/designs/{a['design']}/proposals", {"graph": a["graph"], "note": a["note"]})
        return [_text(f"Proposal {p['id']} on {a['design']} (rev {p['base_rev']}) is waiting for a person.")]
    if name == "search":
        hits = hub.get("/api/search", q=a["q"])
        return [_text("\n".join(f"{r['kind']:<9} {r['ref']:<44} {r['title']}\n          {r['snippet']}" for r in hits) or "No matches.")]
    raise HubRequestError(404, f"unknown tool {name!r}")


def handle(hub: Hub, message: dict) -> dict | None:
    """Answer one JSON-RPC message; None for notifications."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "research-hub", "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in TOOLS.items()]}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            result = {"content": call(hub, params.get("name"), params.get("arguments") or {}), "isError": False}
        except HubRequestError as e:
            result = {"content": [_text(f"The hub refused: {e.message}")], "isError": True}
        except KeyError as e:
            result = {"content": [_text(f"Missing argument: {e.args[0]}")], "isError": True}
        except OSError as e:
            result = {"content": [_text(f"Cannot reach the hub at {hub.url}: {e}")], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(hub: Hub, stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(hub, json.loads(line))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not valid JSON"}}
        if reply is not None:
            stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            stdout.flush()
