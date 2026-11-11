"""`hub` command line. `serve`, `reindex` and `admin` work on the hub's files; everything else talks to the server."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

from .client import Hub, HubRequestError, git_provenance, log_eval, resolve_token, save_token
from .core import HubError

DEFAULT_HOME = os.environ.get("HUB_HOME", "~/.research_hub")


def _out(value):
    print(value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _read(text=None, file=None, what="text"):
    if file:
        return sys.stdin.read() if file == "-" else Path(file).read_text()
    if text:
        return text
    raise SystemExit(f"give --{what} or --file")


def _json_file(path):
    return json.loads(sys.stdin.read() if path == "-" else Path(path).read_text())


# ------------------------------------------------------------------ formatting
def _fmt_inbox(box):
    lines = []
    for h in box.get("handbooks", []):
        lines.append(f"HANDBOOK CHANGED ({h['project']}): rev {h['rev']} by {h['author']} — {h['note']}\n  -> {h['action']}")
    if box["feedback"]:
        lines.append(f"\nOPEN FEEDBACK ON YOUR WORK ({len(box['feedback'])}) — answer before starting new work:")
        for c in box["feedback"]:
            who = "HUMAN " if c.get("author_kind") == "human" else ""
            anchor = f" [{c['anchor']}]" if c["anchor"] else ""
            lines.append(f"  #{c['id']} {who}{c['author']} {c['kind']} on {c['target']}{anchor}:\n    {c['body']}")
    for key, label in (("replies", "REPLIES TO YOUR COMMENTS"), ("mentions", "@MENTIONS"),
                       ("thread_replies", "REPLIES IN YOUR THREADS")):
        if box[key]:
            lines.append(f"\n{label}:")
            for m in box[key]:
                where = m.get("on_target") or f"#{m.get('channel')}"
                lines.append(f"  {m['author']} ({where}, {m['created']}): {m['body']}")
    if box.get("stale_runs"):
        lines.append("\nRUNS WITH NO UPDATE FOR 6h (close them or log progress):")
        lines += [f"  {r['slug']} last update {r['updated']}" for r in box["stale_runs"]]
    if box.get("designs"):
        lines.append("\nDESIGNS CHANGED (read with `hub design get <name>`):")
        lines += [f"  {d['slug']} is at rev {d['rev']}, by {d['author']}: {d['note']}" for d in box["designs"]]
    if box.get("design_decisions"):
        lines.append("\nYOUR DESIGN PROPOSALS WERE DECIDED:")
        lines += [f"  proposal {p['id']} on {p['design']} was {p['status']} by {p['decided_by']}" for p in box["design_decisions"]]
    if box.get("design_proposals"):
        lines.append("\nDESIGN PROPOSALS AWAITING A PERSON:")
        lines += [f"  proposal {p['id']} on {p['design']} by {p['author']}: {p['note']}" for p in box["design_proposals"]]
    if box.get("handbook_proposals"):
        lines.append("\nHANDBOOK PROPOSALS AWAITING A MAINTAINER:")
        lines += [f"  proposal {p['id']} ({p['project']}) by {p['author']}: {p['note']}" for p in box["handbook_proposals"]]
    return "\n".join(lines).strip() or "Inbox empty."


def _fmt_design(d):
    """A design as an outline an agent can read: groups, nodes and what connects to what."""
    by_id = {n["id"]: n for n in d["graph"]["nodes"]}
    kids = {}
    for n in d["graph"]["nodes"]:
        kids.setdefault(n.get("group"), []).append(n)
    lines = [f"design {d['slug']}: {d['title']}", f"rev {d['rev']} of {d['head']} by {d['author']} ({d['saved']}): {d['note']}"]
    if d["description"]:
        lines.append(d["description"])

    def walk(parent, indent):
        for n in kids.get(parent, []):
            label = " / ".join(n["label"].split("\n")) or "(no text)"
            lines.append(f"{indent}{n['id']} [{n['kind']}] {label}" + (f" — {n['detail']}" if n.get("detail") else ""))
            walk(n["id"], indent + "  ")

    lines.append(f"\nNODES ({len(by_id)}), nested by group:")
    walk(None, "  ")
    lines.append(f"\nCONNECTIONS ({len(d['graph']['edges'])}):")
    lines += [f"  {e['from']} -> {e['to']}" + (f": {e['label']}" if e.get("label") else "") + (" (dashed)" if e.get("dashed") else "")
              for e in d["graph"]["edges"]]
    waiting = [p for p in d["proposals"] if p["status"] == "open"]
    if waiting:
        lines.append("\nOPEN PROPOSALS:")
        lines += [f"  #{p['id']} by {p['author']} on rev {p['base_rev']}: {p['note']}" for p in waiting]
    roots = [c for c in d["comments"] if not c["parent_id"] and c["status"] == "open"]
    if roots:
        lines.append("\nOPEN COMMENTS:")
        lines += [f"  #{c['id']} {c['author']} {c['kind']}" + (f" [{c['anchor']}]" if c["anchor"] else "") + f": {c['body']}" for c in roots]
    if d["runs"]:
        lines.append("\nRUNS BUILT FROM IT: " + ", ".join(f"{r['slug']} ({r['status']})" for r in d["runs"]))
    lines.append(f"\nTo change it: `hub design get {d['slug']} --json > d.json`, edit nodes and edges (leave x/y off new "
                 f"nodes; they are placed for you), then `hub design propose {d['slug']} d.json --note \"why\"`.")
    return "\n".join(lines)


def _fmt_runs(runs):
    if not runs:
        return "No runs."
    rows = []
    for r in runs:
        flag = f" !{r['open_comments']}" if r.get("open_comments") else ""
        verdict = f" [{r['verdict']}]" if r.get("verdict") else ""
        rows.append(f"{r['status']:<9} {r['category']:<18} {r['owner']:<14} {r['slug']}{verdict}{flag}"
                    + (f"\n          {r['summary'][:110]}" if r.get("summary") else ""))
    return "\n".join(rows)


def _fmt_run(r):
    out = [f"{r['slug']} — {r['title']}",
           f"  {r['project']} · owner {r['owner']} · {r['category']} · {r['status']}" + (f" · verdict {r['verdict']}" if r["verdict"] else ""),
           f"  branch {r['branch'] or '-'} @ {r['commit_sha'][:9]} · config {r['config_path'] or '-'}",
           f"  parent {r['parent'] or '-'} · children {', '.join(r['children']) or '-'}",
           f"  dataset {r.get('dataset') or '-'}" + (f" → produces {r['output_dataset']}" if r.get("output_dataset") else "")]
    for key in ("summary", "hypothesis", "rationale", "expected", "conclusion"):
        if r[key]:
            out.append(f"{key.capitalize()}: {r[key]}")
    if r["summary_metrics"]:
        out.append("\nSummary metrics:")
        for m in r["summary_metrics"]:
            ref = f" (parent {m['parent_value']:.4g})" if m.get("parent_value") is not None else ""
            out.append(f"  {m['key']} = {m['value']:.4g}{ref}")
    if r["metric_keys"]:
        out.append(f"Metric series: {', '.join(r['metric_keys'])}")
    if r["eval_sets"]:
        out.append("Eval sets: " + ", ".join(f"{s['set']} ({len(s['steps'])} checkpoints)" for s in r["eval_sets"]))
    if r["artifacts"]:
        out.append(f"Artifacts: {len(r['artifacts'])}")
    if r["notes"]:
        out.append("\nNotes:")
        out += [f"  {n['created']} {n['author']}: {n['body']}" for n in r["notes"]]
    if r["comments"]:
        out.append("\nComments:")
        for c in r["comments"]:
            indent = "    " if c["parent_id"] else "  "
            out.append(f"{indent}#{c['id']} {c['author']} {c['kind']} [{c['status']}] {c['anchor']}: {c['body']}")
    return "\n".join(out)


# ------------------------------------------------------------- local commands
def cmd_serve(a):
    from .server import serve
    serve(a.home, a.host, a.port, a.public_url)


def _password(prompt="Password: "):
    return os.environ.get("HUB_PASSWORD") or getpass.getpass(prompt)


def cmd_admin(a):
    """Manage accounts directly in the hub's database: for first setup and for when nobody can sign in."""
    from .store import Store
    store, me = Store(a.home), {"name": "cli", "kind": "human", "admin": True}
    if a.sub == "create":
        store.create_admin(a.name, a.email, _password(f"Password for {a.name}: "), a.display or "")
        print(f"Created admin {a.name}. Sign in with {a.email}.")
    elif a.sub == "reset-password":
        token = store.create_reset(me, a.name)["token"]
        print(f"One-time link, valid 24 hours (append to the hub's address):\n  /#/reset?token={token}")
    elif a.sub == "set":
        _out(store.update_user(me, a.name, {k: v for k, v in (("status", a.status), ("admin", a.admin)) if v is not None}))
    else:
        for u in store.users():
            flags = " admin" if u["admin"] else ""
            print(f"{u['kind']:<6} {u['name']:<24} {u['status']:<9} {u['email'] or u['owner'] or '-':<32}{flags}")


def cmd_reindex(a):
    from .store import Store
    print(f"indexed {Store(a.home).reindex()} documents")


# ------------------------------------------------- sign-in, agents, projects
def cmd_login(a, hub):
    """Save an API key for this machine: either one you paste (--key) or a new one made from your password."""
    if a.key:
        key = a.key
    else:
        email = a.email or input("Email: ")
        req = urllib.request.Request(hub.url + "/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"email": email, "password": _password()}).encode())
        try:
            with urllib.request.urlopen(req, timeout=hub.timeout) as resp:
                session = {"Cookie": resp.headers["Set-Cookie"].split(";")[0], "X-Hub-CSRF": json.loads(resp.read())["csrf"]}
        except urllib.error.HTTPError as e:
            raise HubRequestError(e.code, json.loads(e.read()).get("error", e.reason)) from None
        hub.token = None
        key = hub.request("POST", "/api/keys", {"label": a.label or f"cli on {socket.gethostname()}"}, headers=session)["key"]
        hub.request("POST", "/api/auth/logout", {}, headers=session)
    hub.token = key
    me = hub.get("/api/whoami")
    path = save_token(hub.url, me["name"], key)
    print(f"Signed in to {hub.url} as {me['name']} ({me['kind']}). Key saved to {path}.")


def cmd_agent(a, hub):
    if a.sub == "create":
        res = hub.post("/api/agents", {"name": a.name, "model": a.model, "focus": a.focus,
                                       "projects": [p for p in (a.projects or "").split(",") if p]})
    elif a.sub == "key":
        res = hub.post("/api/keys", {"participant": a.name, "label": a.label or "cli"})
    else:
        for g in hub.get("/api/agents"):
            print(f"{g['name']:<24} {g['status']:<9} owner {g['owner']:<16} {','.join(g['projects']) or '-':<30} {g['model']}")
        return
    print(f"API key for {a.name} (shown once):\n\n  export HUB_URL={hub.url}\n  export HUB_TOKEN={res['key']}"
          + (f"\n  export HUB_PROJECT={a.projects.split(',')[0]}" if getattr(a, "projects", None) else "")
          + "\n\nGive these to the agent's environment; it then runs `hub handbook` and `hub inbox`.")


def cmd_members(a, hub):
    if a.sub == "add":
        _out(hub.put(f"/api/members/{a.name}", {"role": a.role}))
    elif a.sub == "remove":
        hub.delete(f"/api/members/{a.name}")
        print(f"removed {a.name}")
    elif a.sub == "invite":
        res = hub.post("/api/invites", {"email": a.email or "", "project": hub.project, "role": a.role, "days": a.days})
        print(f"Invite link ({a.role} of {hub.project}, valid {a.days} days):\n  {hub.url}/#/signup?invite={res['token']}")
    else:
        for m in hub.get("/api/members"):
            print(f"{m['kind']:<6} {m['name']:<24} {m['role']:<11} {m['model'] or m['display'] or ''}")


def cmd_project_list(a, hub):
    for p in hub.get("/api/projects"):
        print(f"{p['slug']:<24} {p['runs']:>4} runs ({p['running']} running)  {p['title']}"
              + f"  [{p['role']}]" + ("  [strict]" if p["settings"].get("strict") else ""))


def cmd_project_create(a, hub):
    body = {"slug": a.slug, "title": a.title or a.slug, "description": a.description, "settings": {"strict": a.strict},
            "visibility": a.visibility}
    if a.handbook:
        body["handbook"] = Path(a.handbook).read_text()
    res = hub.post("/api/projects", body)
    print(f"Created project {res['slug']}. Use HUB_PROJECT={res['slug']} or --project {res['slug']}.")


def cmd_project_set(a, hub):
    p = hub.get(f"/api/projects/{a.slug}")
    settings = p["settings"]
    for kv in a.set:
        key, _, value = kv.partition("=")
        settings[key] = json.loads(value) if value and value[0] in "{[\"0123456789tfn-" else value
    _out(hub.patch(f"/api/projects/{a.slug}", {"settings": settings})["settings"])


def cmd_handbook(a, hub):
    if a.edit:
        current = hub.get("/api/handbook")
        _out(hub.put("/api/handbook", {"text": Path(a.edit).read_text(), "note": a.note or "Edited",
                                       "expected_rev": current["rev"]}))
    elif a.propose:
        _out(hub.post("/api/handbook/proposals", {"text": Path(a.propose).read_text(), "note": a.note or "Proposal"}))
    elif a.accept:
        p = hub.get(f"/api/handbook/proposals/{a.accept}")
        _out(hub.put("/api/handbook", {"text": p["text"], "note": a.note or f"Accepted proposal {a.accept}: {p['note']}",
                                       "proposal_id": a.accept}))
    elif a.reject:
        _out(hub.post(f"/api/handbook/proposals/{a.reject}/reject"))
    else:
        h = hub.get("/api/handbook")
        print(f"<!-- {h['project']} handbook rev {h['rev']} by {h['author']} {h['created']}: {h['note']} -->\n")
        print(h["text"])


def cmd_inbox(a, hub):
    box = hub.get("/api/inbox", project=hub.project)
    print(json.dumps(box, indent=2) if a.json else _fmt_inbox(box))
    if a.ack:
        hub.post("/api/inbox/ack")


def cmd_search(a, hub):
    for r in hub.get("/api/search", q=" ".join(a.query)):
        print(f"{r['kind']:<9} {r['ref']:<44} {r['title']}\n          {r['snippet']}")


def cmd_list(a, hub):
    _out(hub.get(f"/api/{a.what}"))


def cmd_taxonomy_add(a, hub):
    _out(hub.post(f"/api/{a.table}", {"slug": a.slug, "title": a.title, "description": a.description}))


def cmd_channel_add(a, hub):
    _out(hub.post("/api/channels", {"slug": a.slug, "title": a.title}))


# --------------------------------------------------------------------- runs
def _run_body(a, status):
    body = _json_file(a.file) if a.file else {}
    for key in ("slug", "title", "category", "summary", "hypothesis", "rationale", "expected", "parent", "app", "command",
                "dataset", "output_dataset"):
        val = getattr(a, key, None)
        if val is not None:
            body[key] = val
    if a.topic:
        body["topics"] = a.topic
    if a.motivated_by:
        body["motivated_by"] = a.motivated_by
    if a.pinned:
        body["pinned"] = a.pinned.split(",")
    if a.config:
        body.update(git_provenance(a.config, allow_unpushed=a.allow_unpushed))
    body["status"] = status
    body.setdefault("title", body.get("slug"))
    return body


def cmd_run_create(a, hub, status="planned"):
    res = hub.post("/api/runs", _run_body(a, status))
    print(f"Registered {res['slug']} ({res['status']}) in {res['project']}.")
    print(f"Ingest token for training code (scoped to this run): {res['ingest_token']}")
    print(f"export HUB_RUN={res['slug']} HUB_TOKEN={res['ingest_token']}   # in the training process only")


def cmd_run_list(a, hub):
    page = hub.get("/api/runs", category=a.category, status=a.status, owner=a.owner, topic=a.topic, q=a.q, limit=a.limit)
    print(json.dumps(page, indent=2) if a.json else _fmt_runs(page["runs"]) + f"\n({page['total']} total)")


def cmd_run_table(a, hub):
    cols = a.columns.split(",") if a.columns else []
    page = hub.get("/api/runs/table", columns=",".join(cols), sort=a.sort, status=a.status, category=a.category,
                   q=a.q, limit=a.limit)
    if a.json:
        return _out(page)
    if not cols:
        print("Available summary keys (most used first):")
        print("  " + "\n  ".join(f"{k['key']} ({k['n']} runs)" for k in page["available"][:40]))
        print("\nPass --columns key1,key2 to show them.")
    head = f"{'run':<44} {'status':<9} " + " ".join(f"{c[-18:]:>18}" for c in cols)
    print(head)
    for r in page["runs"]:
        vals = " ".join(f"{r['values'][c]:>18.4g}" if c in r["values"] else f"{'—':>18}" for c in cols)
        print(f"{r['slug']:<44} {r['status']:<9} {vals}")


def cmd_run_get(a, hub):
    r = hub.get(f"/api/runs/{a.slug}")
    print(json.dumps(r, indent=2, default=str) if a.json else _fmt_run(r))


def cmd_run_update(a, hub):
    body = _json_file(a.file) if a.file else {}
    for key in ("status", "conclusion", "verdict", "summary", "hypothesis", "rationale", "expected", "title", "command",
                "dataset", "output_dataset"):
        val = getattr(a, key, None)
        if val is not None:
            body[key] = val
    if a.pinned is not None:
        body["pinned"] = [k for k in a.pinned.split(",") if k]
    if a.config:
        body.update(git_provenance(a.config, allow_unpushed=a.allow_unpushed))
    print(_fmt_run(hub.patch(f"/api/runs/{a.slug}", body)))


def _delete(a, hub, what, path):
    """Delete after the name is typed back, or with --yes."""
    if not a.yes and input(f"This permanently deletes the {what} {a.slug} and everything in it. Type its name to confirm: ") != a.slug:
        raise RuntimeError("names did not match; nothing was deleted")
    hub.request("DELETE", path, query={"confirm": a.slug})
    print(f"deleted {what} {a.slug}")


def cmd_run_delete(a, hub):
    _delete(a, hub, "run", f"/api/runs/{a.slug}")


def cmd_project_delete(a, hub):
    _delete(a, hub, "project", f"/api/projects/{a.slug}")


def cmd_run_finish(a, hub):
    body = {"status": a.status, "conclusion": _read(a.conclusion, a.conclusion_file, "conclusion")}
    if a.verdict:
        body["verdict"] = a.verdict
    print(_fmt_run(hub.patch(f"/api/runs/{a.slug}", body)))


def cmd_run_note(a, hub):
    _out(hub.post(f"/api/runs/{a.slug}/notes", {"body": _read(a.body, a.file, "body")}))


def cmd_run_metric(a, hub):
    points = [{"key": k, "step": a.step, "value": float(v)} for k, v in (kv.split("=", 1) for kv in a.values)]
    _out(hub.post(f"/api/runs/{a.slug}/metrics", {"points": points}))


def cmd_run_summary(a, hub):
    spec = {}
    for kv in a.values:
        key, val = kv.split("=", 1)
        direction = "max"
        if ":" in val:
            val, direction = val.split(":", 1)
        spec[key] = {"value": float(val), "direction": direction}
    _out(hub.post(f"/api/runs/{a.slug}/summary", spec)["summary_metrics"])


def cmd_run_artifact(a, hub):
    import base64
    for p in a.paths:
        data = base64.b64encode(Path(p).read_bytes()).decode()
        _out(hub.post(f"/api/runs/{a.slug}/artifacts", {"name": Path(p).name, "data": data, "kind": a.kind, "step": a.step,
                                                        "caption": a.caption or "", "epoch": a.epoch,
                                                        "sample": a.sample or "", "role": a.role or ""}))


def cmd_run_config(a, hub):
    print(hub.get(f"/api/runs/{a.slug}/config")["text"])


def cmd_run_compare(a, hub):
    res = hub.get("/api/compare", runs=",".join(a.slugs))
    if a.json:
        return _out(res)
    width = max(len(s) for s in a.slugs) + 2
    keys = sorted({k for v in res["summary"].values() for k in v})
    print("summary".ljust(34) + "".join(s.ljust(width) for s in a.slugs))
    for k in keys:
        print(k[-32:].ljust(34) + "".join((f"{res['summary'][s][k]:.4g}" if k in res["summary"][s] else "-").ljust(width)
                                         for s in a.slugs))
    if res["config_diff"]:
        print("\nconfig differences:")
        for d in res["config_diff"]:
            print(f"  {d['key']}: " + " | ".join(f"{s}={d.get(s)}" for s in a.slugs))
    print(f"\n{len(res['curves'])} metric curves in common; the dashboard overlays them.")


def cmd_run_eval(a, hub):
    path = Path(a.file)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    res = log_eval(hub, a.slug, a.set, a.step, rows, a.epoch, a.negatives.split(",") if a.negatives else None,
                   base_dir=path.parent)
    print(f"{a.slug}: logged {res['logged']} samples of {res['set']} at step {res['step']}: "
          + ", ".join(f"{k} {v}" for k, v in sorted(res["outcomes"].items())))


def cmd_run_evals(a, hub):
    sets = hub.get(f"/api/runs/{a.slug}")["eval_sets"]
    if a.json:
        return _out(sets)
    if not sets:
        print("no eval samples logged for this run")
    for s in sets:
        print(s["set"])
        for st in s["steps"]:
            epoch = st["epoch"] if st["epoch"] is not None else "-"
            print(f"  step {st['step']:>8}  epoch {epoch:>4}  {st['samples']:>6} samples  {st['wrong']:>5} wrong  "
                  f"{st['layered']:>5} with layers")


def cmd_run_samples(a, hub):
    q = {"set": a.set, "step": a.step, "class_true": a.true_class, "class_pred": a.pred_class, "outcome": a.outcome,
         "q": a.q, "value_min": a.value_min, "value_max": a.value_max, "vs": a.vs, "vs_outcome": a.vs_outcome,
         "sort": a.sort, "limit": a.limit, "offset": a.offset, "layered": "1" if a.layered else None}
    for kv in a.fact:
        key, _, value = kv.partition("=")
        q[f"fact.{key}"] = value
    res = hub.get(f"/api/runs/{a.slug}/eval/samples", **q)
    print(json.dumps(res, indent=2) if a.json else _fmt_samples(res))


def _fmt_samples(res) -> str:
    out = [f"{res['set']} @ step {res['step']}: {res['total']} matching samples"]
    for r in res["rows"]:
        facts = " ".join(f"{k}={v}" for k, v in r["facts"].items())
        t, p = r["truth"], r["pred"]
        val = "" if t.get("value") is None else f" value {t['value']:g}"
        if p.get("value") is not None:
            val += f"->{p['value']:.2f}"
        err = "" if r["error"] is None else f" err {r['error']:.3g}"
        vs = f" | vs: {r['vs_class_pred']} ({r['vs_outcome']})" if "vs_outcome" in r else ""
        out.append(f"  {r['outcome']:<11} {t.get('class', '?'):>14} -> {p.get('class') or p.get('text', '')[:14]:<14} "
                   f"{facts}{val}{err} [{','.join(sorted(r['layers'])) or 'no layers'}] {r['sample'][:60]}{vs}")
    return "\n".join(out)


# --------------------------------------------------------------- discussion
def cmd_post(a, hub):
    post = _json_file(a.file)
    expected = a.expected
    if expected is None:
        try:
            expected = hub.get(f"/api/posts/{post.get('slug')}")["revision"]
        except HubRequestError:
            expected = 0
    res = hub.put("/api/posts", {"post": post, "expected_revision": expected})
    print(f"post:{res['slug']} revision {res['revision']}")


def cmd_post_list(a, hub):
    for p in hub.get("/api/posts", topic=a.topic, owner=a.owner, kind=a.kind)["posts"]:
        print(f"{p['kind']:<9} {p['basis']:<16} {p['owner']:<14} post:{p['slug']}  rev {p['revision']}\n          {p['title']}")


def cmd_post_get(a, hub):
    p = hub.get(f"/api/posts/{a.slug}")
    if a.json:
        return _out(p)
    print(f"# {p['title']}\n{p['kind']} · {p['basis']} · {p['owner']} · rev {p['revision']} · refs {', '.join(p['refs']) or '-'}\n")
    print(p["body"])
    if p["citations"]:
        print("\nCitations:\n" + "\n".join(f"  [{i + 1}] {c['title']} — {c['url']}" for i, c in enumerate(p["citations"])))
    if p["comments"]:
        print("\nComments:\n" + "\n".join(f"  #{c['id']} {c['author']} {c['kind']} [{c['status']}]: {c['body']}"
                                          for c in p["comments"]))


def cmd_comment(a, hub):
    _out(hub.post("/api/comments", {"target": a.on, "body": _read(a.body, a.file, "body"), "kind": a.kind,
                                    "anchor": a.anchor or "", "parent_id": a.reply_to}))


def cmd_comment_status(a, hub):
    _out(hub.patch(f"/api/comments/{a.id}", {"status": a.status, "resolution_ref": a.ref or ""}))


def cmd_msg_send(a, hub):
    _out(hub.post(f"/api/channels/{a.channel}/messages", {"body": _read(a.body, a.file, "body"), "parent_id": a.reply_to}))


def cmd_msg_read(a, hub):
    for m in hub.get(f"/api/channels/{a.channel}/messages", since=a.since, limit=a.limit):
        thread = f" (in thread {m['parent_id']})" if m["parent_id"] else ""
        print(f"[{m['id']}] {m['created']} {m['author']}{thread}: {m['body']}")


def cmd_mcp(a, hub):
    from .mcp import serve
    serve(hub)


def cmd_design(a, hub):
    if a.sub == "list":
        for d in hub.get("/api/designs"):
            waiting = f"  {d['open_proposals']} proposals" if d["open_proposals"] else ""
            print(f"{d['slug']:<32} rev {d['rev']:<3} {d['n_nodes']:>3} nodes  {d['owner']:<16} {d['title']}{waiting}")
    elif a.sub == "get":
        if a.proposal:
            p = hub.get(f"/api/design-proposals/{a.proposal}")
            d = {**hub.get(f"/api/designs/{p['design']}"), "graph": p["graph"], "author": p["author"], "note": p["note"],
                 "saved": p["created"], "rev": f"proposal {p['id']} on rev {p['base_rev']}"}
        elif a.slug:
            d = hub.get(f"/api/designs/{a.slug}", rev=a.rev)
        else:
            raise SystemExit("give a design name, or --proposal ID")
        _out(d["graph"] if a.json else _fmt_design(d))
    elif a.sub == "create":
        _out(hub.post("/api/designs", {"slug": a.slug, "title": a.title or a.slug, "description": a.description,
                                       "graph": _json_file(a.file) if a.file else None, "note": a.note}))
    elif a.sub == "propose":
        _out(hub.post(f"/api/designs/{a.slug}/proposals", {"graph": _json_file(a.file), "note": a.note}))
    elif a.sub == "save":
        current = hub.get(f"/api/designs/{a.slug}")
        graph = hub.get(f"/api/design-proposals/{a.accept}")["graph"] if a.accept else _json_file(a.file)
        _out(hub.put(f"/api/designs/{a.slug}", {"graph": graph, "note": a.note or f"Accepted proposal {a.accept}",
                                                "expected_rev": current["head"], "proposal_id": a.accept}))
    elif a.sub == "reject":
        _out(hub.post(f"/api/design-proposals/{a.id}/reject"))
    else:
        _delete(a, hub, "design", f"/api/designs/{a.slug}")


def cmd_claim(a, hub):
    if a.release:
        hub.delete(f"/api/claims/{a.resource}")
        print(f"released {a.resource}")
    else:
        _out(hub.post("/api/claims", {"resource": a.resource, "note": a.note or "", "hours": a.hours}))


def build_parser():
    p = argparse.ArgumentParser(prog="hub", description="Research Hub: run tracking and collaboration for people and AI agents.")
    p.add_argument("--url", default=None, help="hub URL (default $HUB_URL)")
    p.add_argument("--as", dest="agent", default=None, help="identity from saved credentials (default $HUB_AGENT)")
    p.add_argument("--project", default=None, help="project slug (default $HUB_PROJECT, or the only project)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the hub server (one per team)")
    s.add_argument("--home", default=DEFAULT_HOME, help="data directory (default $HUB_HOME or ~/.research_hub)")
    s.add_argument("--host", default=os.environ.get("HUB_HOST", "127.0.0.1"),
                   help="address to listen on; 0.0.0.0 to accept connections from other machines")
    s.add_argument("--port", type=int, default=int(os.environ.get("HUB_PORT", 6230)))
    s.add_argument("--public-url", default=os.environ.get("HUB_PUBLIC_URL"), help="address people use, for printed links")
    s.set_defaults(fn=cmd_serve, local=True)
    admin = sub.add_parser("admin", help="manage accounts directly in the hub's database (run on the server)")
    admin.add_argument("--home", default=DEFAULT_HOME)
    ads = admin.add_subparsers(dest="sub", required=True)
    s = ads.add_parser("create", help="create a site admin (password from the prompt or $HUB_PASSWORD)")
    s.add_argument("name")
    s.add_argument("--email", required=True)
    s.add_argument("--display")
    s = ads.add_parser("reset-password", help="print a one-time password reset link")
    s.add_argument("name")
    s = ads.add_parser("set", help="approve, disable or promote an account")
    s.add_argument("name")
    s.add_argument("--status", choices=["active", "pending", "disabled"])
    s.add_argument("--admin", type=lambda v: v.lower() in ("1", "true", "yes"), metavar="true|false")
    ads.add_parser("list")
    admin.set_defaults(fn=cmd_admin, local=True)
    s = sub.add_parser("reindex", help="rebuild the search index")
    s.add_argument("--home", default=DEFAULT_HOME)
    s.set_defaults(fn=cmd_reindex, local=True)

    s = sub.add_parser("login", help="save an API key for this machine")
    s.add_argument("--email")
    s.add_argument("--key", help="an existing API key to save (agents: the key your owner created)")
    s.add_argument("--label", help="name for the new key (default: cli on <hostname>)")
    s.set_defaults(fn=cmd_login)
    agent = sub.add_parser("agent", help="service accounts for AI agents (you own the ones you create)")
    ags = agent.add_subparsers(dest="sub", required=True)
    s = ags.add_parser("create", help="create an agent and print its API key")
    s.add_argument("name")
    s.add_argument("--model", default="")
    s.add_argument("--focus", default="", help="what this agent works on")
    s.add_argument("--projects", help="projects to add it to as a member, comma-separated (you must be a maintainer)")
    s = ags.add_parser("key", help="issue another API key for an agent you own")
    s.add_argument("name")
    s.add_argument("--label")
    ags.add_parser("list")
    agent.set_defaults(fn=cmd_agent)
    members = sub.add_parser("members", help="who is in the project, and with which role")
    ms = members.add_subparsers(dest="sub", required=True)
    ms.add_parser("list")
    s = ms.add_parser("add", help="add an existing account, or change its role")
    s.add_argument("name")
    s.add_argument("--role", default="member", choices=["viewer", "member", "maintainer", "owner"])
    s = ms.add_parser("remove")
    s.add_argument("name")
    s = ms.add_parser("invite", help="print a sign-up link that joins the project")
    s.add_argument("--email", help="restrict the link to this address")
    s.add_argument("--role", default="member", choices=["viewer", "member", "maintainer"])
    s.add_argument("--days", type=float, default=7)
    members.set_defaults(fn=cmd_members)
    sub.add_parser("whoami").set_defaults(fn=lambda a, h: _out(h.get("/api/whoami")))

    project = sub.add_parser("project", help="projects: separately managed spaces of runs, posts, chat, handbook")
    ps = project.add_subparsers(dest="sub", required=True)
    ps.add_parser("list").set_defaults(fn=cmd_project_list)
    s = ps.add_parser("create", help="create a project you own")
    s.add_argument("slug")
    s.add_argument("--title")
    s.add_argument("--description", default="")
    s.add_argument("--handbook", help="markdown file for the project's first handbook revision")
    s.add_argument("--strict", action="store_true", help="agent runs must state hypothesis, rationale, parent, provenance")
    s.add_argument("--visibility", default="private", choices=["private", "internal"],
                   help="private: members only; internal: every signed-in person can read")
    s.set_defaults(fn=cmd_project_create)
    s = ps.add_parser("set", help="maintainer: change settings, e.g. strict=true default_category=ablation")
    s.add_argument("slug")
    s.add_argument("set", nargs="+", metavar="key=value")
    s.set_defaults(fn=cmd_project_set)
    s = ps.add_parser("delete", help="owner: delete a project and everything in it (asks for its name)")
    s.add_argument("slug")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    s.set_defaults(fn=cmd_project_delete)

    s = sub.add_parser("handbook", help="print the project handbook (marks it read); maintainers can edit")
    s.add_argument("--edit", metavar="FILE", help="maintainer: replace the handbook with FILE")
    s.add_argument("--propose", metavar="FILE", help="member: propose FILE as a new handbook")
    s.add_argument("--accept", type=int, metavar="ID", help="maintainer: accept a proposal")
    s.add_argument("--reject", type=int, metavar="ID", help="maintainer: reject a proposal")
    s.add_argument("--note", default=None)
    s.set_defaults(fn=cmd_handbook)
    s = sub.add_parser("inbox", help="open feedback, replies, mentions, handbook changes")
    s.add_argument("--ack", action="store_true", help="mark replies/mentions as seen (feedback stays until resolved)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_inbox)
    s = sub.add_parser("search", help="full-text search across runs, posts, messages, comments")
    s.add_argument("query", nargs="+")
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("list", help="list categories, topics, channels, members, claims or projects")
    s.add_argument("what", choices=["categories", "topics", "channels", "members", "claims", "projects"])
    s.set_defaults(fn=cmd_list)
    for name, table, help_ in (("category", "categories", "maintainer: add a run category"),
                               ("topic", "topics", "register a research topic")):
        s = sub.add_parser(name, help=help_)
        ss = s.add_subparsers(dest="sub", required=True).add_parser("add")
        ss.add_argument("slug")
        ss.add_argument("--title", required=True)
        ss.add_argument("--description", default="")
        ss.set_defaults(fn=cmd_taxonomy_add, table=table)
    s = sub.add_parser("channel", help="add a chat channel")
    ss = s.add_subparsers(dest="sub", required=True).add_parser("add")
    ss.add_argument("slug")
    ss.add_argument("--title", default="")
    ss.set_defaults(fn=cmd_channel_add)

    run = sub.add_parser("run", help="register, log to, inspect and compare runs").add_subparsers(dest="sub", required=True)

    def run_fields(sp):
        sp.add_argument("slug", nargs="?")
        sp.add_argument("--file", help="JSON with run fields (flags override)")
        for f in ("title", "category", "summary", "hypothesis", "rationale", "expected", "parent", "app", "command"):
            sp.add_argument(f"--{f}", default=None, help="'none' for a first baseline" if f == "parent" else None)
        sp.add_argument("--dataset", help="input dataset(s) as name@version, comma-separated for several")
        sp.add_argument("--output-dataset", help="dataset this run produces, as name@version")
        sp.add_argument("--topic", action="append", default=[])
        sp.add_argument("--motivated-by", action="append", default=[], help="post:<slug> or run:<slug>")
        sp.add_argument("--pinned", help="metric keys to pin on the run overview, comma-separated")
        sp.add_argument("--config", help="path to the committed config (git provenance is read from it)")
        sp.add_argument("--allow-unpushed", action="store_true", help="only for local smoke tests")

    s = run.add_parser("create", help="register a planned run")
    run_fields(s)
    s.set_defaults(fn=cmd_run_create)
    s = run.add_parser("start", help="register a run that is starting now")
    run_fields(s)
    s.set_defaults(fn=lambda a, h: cmd_run_create(a, h, "running"))
    s = run.add_parser("list")
    for f in ("category", "status", "owner", "topic", "q"):
        s.add_argument(f"--{f}")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_run_list)
    s = run.add_parser("table", help="runs as a table of summary metrics")
    s.add_argument("--columns", help="summary keys, comma-separated (omit to list the available keys)")
    s.add_argument("--sort", help="a column key, or updated/created/slug/owner/status")
    for f in ("status", "category", "q"):
        s.add_argument(f"--{f}")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_run_table)
    s = run.add_parser("get")
    s.add_argument("slug")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_run_get)
    s = run.add_parser("update")
    s.add_argument("slug")
    s.add_argument("--file")
    for f in ("status", "conclusion", "verdict", "summary", "hypothesis", "rationale", "expected", "title", "command",
              "dataset", "output-dataset"):
        s.add_argument(f"--{f}")
    s.add_argument("--pinned", help="metric keys to pin, comma-separated ('' to clear)")
    s.add_argument("--config")
    s.add_argument("--allow-unpushed", action="store_true")
    s.set_defaults(fn=cmd_run_update)
    s = run.add_parser("finish", help="close a run with a conclusion")
    s.add_argument("slug")
    s.add_argument("--status", default="finished", choices=["finished", "failed", "abandoned"])
    s.add_argument("--verdict", choices=["supports", "refutes", "inconclusive"])
    s.add_argument("--conclusion")
    s.add_argument("--conclusion-file")
    s.set_defaults(fn=cmd_run_finish)
    s = run.add_parser("delete", help="a person deletes a run for good (asks for its name; agents abandon runs instead)")
    s.add_argument("slug")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    s.set_defaults(fn=cmd_run_delete)
    s = run.add_parser("note", help="add a dated note to the run's timeline")
    s.add_argument("slug")
    s.add_argument("--body")
    s.add_argument("--file")
    s.set_defaults(fn=cmd_run_note)
    s = run.add_parser("metric", help="log key=value metrics at a step")
    s.add_argument("slug")
    s.add_argument("--step", type=int, required=True)
    s.add_argument("values", nargs="+", metavar="key=value")
    s.set_defaults(fn=cmd_run_metric)
    s = run.add_parser("summary", help="set final metrics: key=value[:max|min|none]")
    s.add_argument("slug")
    s.add_argument("values", nargs="+")
    s.set_defaults(fn=cmd_run_summary)
    s = run.add_parser("artifact", help="upload images, plots or files")
    s.add_argument("slug")
    s.add_argument("paths", nargs="+")
    s.add_argument("--step", type=int)
    s.add_argument("--epoch", type=int)
    s.add_argument("--caption")
    s.add_argument("--kind", default="image", choices=["image", "plot", "table", "file"])
    s.add_argument("--sample", help="stable sample id, to follow the same example across checkpoints")
    s.add_argument("--role", choices=["tracked", "failure"])
    s.set_defaults(fn=cmd_run_artifact)
    s = run.add_parser("eval", help="log per-sample results (+ image, mask, box, text layers) for one checkpoint from JSONL")
    s.add_argument("slug")
    s.add_argument("file", help="JSONL, one sample per line; image/layer paths relative to this file")
    s.add_argument("--set", required=True, help="eval set: dataset@version[:split]")
    s.add_argument("--step", type=int, required=True)
    s.add_argument("--epoch", type=int)
    s.add_argument("--negatives", help="classes that mean 'nothing there', comma-separated (default: negative,background,normal,none,ok,good,healthy)")
    s.set_defaults(fn=cmd_run_eval)
    s = run.add_parser("evals", help="list a run's eval sets and checkpoints")
    s.add_argument("slug")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_run_evals)
    s = run.add_parser("samples", help="query a run's eval samples by fact, class, outcome, value range, or vs another run")
    s.add_argument("slug")
    s.add_argument("--set", required=True)
    s.add_argument("--step", type=int, help="checkpoint (default: latest)")
    s.add_argument("--fact", action="append", default=[], metavar="key=value", help="e.g. camera=c2 (repeatable; comma-separate several values)")
    s.add_argument("--true-class")
    s.add_argument("--pred-class")
    s.add_argument("--outcome", help="correct, missed, false_alarm, wrong_class, mismatch, unscored (comma-separated)")
    s.add_argument("--q", help="substring of the sample id or any fact")
    s.add_argument("--value-min", type=float)
    s.add_argument("--value-max", type=float)
    s.add_argument("--layered", action="store_true", help="only samples with mask layers at this checkpoint")
    s.add_argument("--vs", help="another run on the same eval set, to compare per sample")
    s.add_argument("--vs-outcome", help="outcome in the --vs run, e.g. correct")
    s.add_argument("--sort", default="error", choices=["error", "score", "value", "value_pred", "sample"])
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_run_samples)
    s = run.add_parser("config", help="print the exact config snapshot a run used")
    s.add_argument("slug")
    s.set_defaults(fn=cmd_run_config)
    s = run.add_parser("compare", help="summary values, config differences and shared curves across runs")
    s.add_argument("slugs", nargs="+")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_run_compare)
    post = sub.add_parser("post", help="research posts").add_subparsers(dest="sub", required=True)
    s = post.add_parser("put", help="create or revise a post from JSON")
    s.add_argument("file")
    s.add_argument("--expected", type=int, default=None, help="revision you edited (default: current)")
    s.set_defaults(fn=cmd_post)
    s = post.add_parser("list")
    for f in ("topic", "owner", "kind"):
        s.add_argument(f"--{f}")
    s.set_defaults(fn=cmd_post_list)
    s = post.add_parser("get")
    s.add_argument("slug")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_post_get)

    s = sub.add_parser("comment", help="comment on a run, post, artifact, message or sample")
    s.add_argument("--on", required=True, help="run:<slug> | post:<slug> | design:<slug> | artifact:<id> | message:<id> | sample:<run>/<set>/<id>")
    s.add_argument("--kind", default="note", choices=["note", "question", "request", "objection", "support", "response"])
    s.add_argument("--anchor", help="what exactly: 'chart: val/auroc', 'config', 'step 11000'")
    s.add_argument("--body")
    s.add_argument("--file")
    s.add_argument("--reply-to", type=int)
    s.set_defaults(fn=cmd_comment)
    s = sub.add_parser("resolve", help="set a comment's status")
    s.add_argument("id", type=int)
    s.add_argument("--status", default="resolved", choices=["open", "acknowledged", "resolved"])
    s.add_argument("--ref", help="run:<slug>, post:<slug> or comment:<id> that answers it")
    s.set_defaults(fn=cmd_comment_status)

    msg = sub.add_parser("msg", help="chat").add_subparsers(dest="sub", required=True)
    s = msg.add_parser("send")
    s.add_argument("channel")
    s.add_argument("--body")
    s.add_argument("--file")
    s.add_argument("--reply-to", type=int)
    s.set_defaults(fn=cmd_msg_send)
    s = msg.add_parser("read")
    s.add_argument("channel")
    s.add_argument("--since", type=int, default=0)
    s.add_argument("--limit", type=int, default=100)
    s.set_defaults(fn=cmd_msg_read)
    sub.add_parser("mcp", help="serve the hub to an agent as MCP tools over stdio (for agents without a shell)"
                   ).set_defaults(fn=cmd_mcp)
    design = sub.add_parser("design", help="architecture boards: boxes, groups and arrows, with revisions and proposals")
    ds = design.add_subparsers(dest="sub", required=True)
    ds.add_parser("list")
    s = ds.add_parser("get", help="print a design as an outline, or as JSON to edit")
    s.add_argument("slug", nargs="?")
    s.add_argument("--rev", type=int, help="an earlier revision (default: the latest)")
    s.add_argument("--proposal", type=int, metavar="ID", help="show a proposal instead")
    s.add_argument("--json", action="store_true", help="the nodes and edges, ready to edit and propose")
    s = ds.add_parser("create", help="start a new design; FILE holds {nodes, edges}")
    s.add_argument("slug")
    s.add_argument("--title")
    s.add_argument("--description", default="")
    s.add_argument("--file", help="JSON with nodes and edges (default: an empty board)")
    s.add_argument("--note", default="")
    s = ds.add_parser("propose", help="propose FILE as the next revision; a person accepts or rejects it")
    s.add_argument("slug")
    s.add_argument("file")
    s.add_argument("--note", required=True, help="what changes and why")
    s = ds.add_parser("save", help="a person saves FILE as the next revision, or accepts a proposal")
    s.add_argument("slug")
    s.add_argument("file", nargs="?")
    s.add_argument("--accept", type=int, metavar="ID", help="accept this proposal as the next revision")
    s.add_argument("--note")
    s = ds.add_parser("reject", help="a person rejects a proposal")
    s.add_argument("id", type=int)
    s = ds.add_parser("delete", help="a person deletes a design for good (asks for its name)")
    s.add_argument("slug")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    design.set_defaults(fn=cmd_design)
    s = sub.add_parser("claim", help="claim an idea or resource so others don't duplicate it")
    s.add_argument("resource")
    s.add_argument("--note")
    s.add_argument("--hours", type=float, default=24)
    s.add_argument("--release", action="store_true")
    s.set_defaults(fn=cmd_claim)

    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    if getattr(a, "local", False):
        try:
            return a.fn(a)
        except HubError as e:
            print(f"hub: {e}", file=sys.stderr)
            return 1
    hub = Hub(a.url, project=a.project)
    if a.agent:
        hub.token = resolve_token(hub.url, a.agent)
    try:
        rc = a.fn(a, hub)
    except HubRequestError as e:
        print(f"hub: {e.message}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"hub: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"hub: cannot reach {hub.url}: {e}. Is the server running? (HUB_URL)", file=sys.stderr)
        return 1
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
