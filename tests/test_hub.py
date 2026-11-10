"""End-to-end tests through the HTTP API, the Python client and the CLI."""

import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from research_hub import client as hubclient
from research_hub.cli import main as cli
from research_hub.server import Api, make_handler
from research_hub.store import Store

PASSWORD = "correct horse battery"
STRICT = dict(category="ablation", summary="s", hypothesis="h", rationale="r", expected="e", parent="none",
              dataset="shapes@1.0", branch="exp/x", commit_sha="a" * 40, config_path="cfg.yaml", config_text="k: 8\n")


def png() -> bytes:
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (100, 100, 100)).save(buf, "PNG")
    return buf.getvalue()


class Site:
    """A running hub with an admin (ada) who owns two projects: strict `research` and plain `detectors`."""

    def __init__(self, url, store, api):
        self.url, self.store, self.api = url, store, api
        store.create_admin("ada", "ada@example.org", PASSWORD)
        admin = {"name": "ada", "kind": "human", "admin": True}
        self.ada = self.hub(store.create_key(admin, "ada", "tests")["key"])
        self.ada.post("/api/projects", {"slug": "research", "title": "Research", "settings": {"strict": True}})
        self.ada.post("/api/projects", {"slug": "detectors", "title": "Detectors"})

    def hub(self, key=None, project=None):
        h = hubclient.Hub(self.url, key, project=project)
        h.token = key
        return h

    def agent(self, name, projects=("research", "detectors"), project="research"):
        key = self.ada.post("/api/agents", {"name": name, "projects": list(projects)})["key"]
        hubclient.save_token(self.url, name, key)
        return self.hub(key, project)

    def browser(self, email, password=PASSWORD):
        """Sign in the way the dashboard does; returns (status, body) callables bound to the session."""
        def call(method, path, body=None, cookie=None, csrf=None):
            req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body or {}).encode(),
                                         headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {}),
                                                  **({"X-Hub-CSRF": csrf} if csrf else {})})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read()), r.headers
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read()), e.headers
        status, body, headers = call("POST", "/api/auth/login", {"email": email, "password": password})
        cookie, token = (headers.get("Set-Cookie") or "").split(";")[0], body.get("csrf")
        return status, body, lambda method, path, data=None, csrf=token: call(method, path, data, cookie, csrf)[:2]


@pytest.fixture
def site(tmp_path, monkeypatch):
    store = Store(tmp_path / "hub")
    api = Api(store)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}"
    monkeypatch.setenv("HUB_URL", url)
    for var in ("HUB_TOKEN", "HUB_PROJECT", "HUB_AGENT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(hubclient, "CRED_PATH", tmp_path / "creds.json")
    monkeypatch.setattr(hubclient, "SPOOL_DIR", tmp_path / "spool")
    yield Site(url, store, api)
    httpd.shutdown()


def denied(match):
    return pytest.raises(hubclient.HubRequestError, match=match)


def test_accounts_roles_and_access(tmp_path, site, monkeypatch, capsys):
    anonymous = site.hub()
    # nothing is readable without signing in, and the first admin needs the code printed by the server
    for path in ("/api/projects", "/api/runs?project=research", "/api/whoami"):
        with denied("sign in"):
            anonymous.get(path)
    fresh = Api(Store(tmp_path / "fresh"))
    setup = {"name": "root", "email": "root@example.org", "password": PASSWORD}
    assert "wrong setup code" in _error(fresh, "POST", "/api/auth/setup", {**setup, "code": "guess"})
    done, cookies = fresh.dispatch("POST", "/api/auth/setup", {}, {**setup, "code": fresh.setup_code}, {})
    assert done["name"] == "root" and "HttpOnly" in cookies[0] and not fresh.store.needs_setup()
    assert "already set up" in _error(fresh, "POST", "/api/auth/setup", {**setup, "name": "x", "code": "y"})

    # sign-up is by invitation: a project invite creates the account and the membership in one step
    assert anonymous.get("/api/auth/state") == {"setup": False, "signup": "invite", "site_name": "Research Hub",
                                                 "version": anonymous.get("/api/health")["version"]}
    person = {"name": "bo", "email": "bo@example.org", "password": PASSWORD}
    with denied("by invitation"):
        anonymous.post("/api/auth/signup", person)
    invite = site.ada.post("/api/invites", {"project": "research", "role": "viewer", "email": "bo@example.org"})["token"]
    with denied("different email"):
        anonymous.post("/api/auth/signup", {**person, "email": "eve@example.org", "invite": invite})
    with denied("10 to 200"):
        anonymous.post("/api/auth/signup", {**person, "password": "short", "invite": invite})
    assert anonymous.post("/api/auth/signup", {**person, "invite": invite})["status"] == "active"
    with denied("invalid, used or expired"):
        anonymous.post("/api/auth/signup", {**person, "name": "bo2", "email": "bo2@example.org", "invite": invite})

    # browser session: cookie + CSRF header; a viewer reads their project and nothing else
    status, body, bo = site.browser("bo@example.org")
    assert status == 200 and body["name"] == "bo"
    assert [(p["slug"], p["role"]) for p in bo("GET", "/api/projects")[1]] == [("research", "viewer")]
    assert bo("GET", "/api/runs?project=detectors")[0] == 404  # private project: not even its existence
    assert bo("POST", "/api/topics?project=research", {"slug": "t", "title": "T"})[0] == 403  # viewers do not write
    assert bo("POST", "/api/keys", {"label": "laptop"}, csrf="forged")[0] == 403  # cross-site request forgery
    key = bo("POST", "/api/keys", {"label": "laptop"})[1]["key"]
    assert site.hub(key).get("/api/whoami")["name"] == "bo"
    site.ada.patch("/api/projects/detectors", {"visibility": "internal"})
    assert bo("GET", "/api/runs?project=detectors")[1]["total"] == 0  # internal: any signed-in person may read

    # roles: a maintainer manages members but cannot grant above their own role or strand the project ownerless
    site.ada.put("/api/members/bo?project=research", {"role": "maintainer"})
    with denied("cannot grant the owner"):
        site.hub(key).put("/api/members/bo?project=research", {"role": "owner"})
    with denied("only owner"):
        site.ada.put("/api/members/ada?project=research", {"role": "member"})
    agent = site.agent("scout", projects=("research",))
    assert agent.get("/api/whoami")["owner"] == "ada"
    with denied("viewer or a member"):
        site.ada.put("/api/members/scout?project=research", {"role": "maintainer"})
    with denied("signed-in person"):  # an agent cannot mint keys or more agents
        agent.post("/api/keys", {"label": "more"})
    with denied("not found"):
        agent.get("/api/runs?project=detectors")

    # a run's ingest token logs to that run only
    run = agent.post("/api/runs", {"slug": "r1", "title": "r1", **STRICT})
    ingest = site.hub(run["ingest_token"])
    ingest.post("/api/runs/r1/metrics", {"points": [{"key": "loss", "step": 1, "value": 0.5}]})
    for call in (lambda: ingest.get("/api/runs?project=research"), lambda: ingest.get("/api/inbox"),
                 lambda: ingest.post("/api/comments", {"target": "run:r1", "body": "x"})):
        with denied("only log to that run"):
            call()
    # logged files need a sign-in too
    sha = agent.post("/api/runs/r1/artifacts", {"name": "a.png", "data": __import__("base64").b64encode(png()).decode()})["blob_sha"]
    with pytest.raises(urllib.error.HTTPError, match="401"):
        urllib.request.urlopen(f"{site.url}/blobs/{sha}")
    ok = urllib.request.urlopen(urllib.request.Request(f"{site.url}/blobs/{sha}", headers={"Authorization": f"Bearer {key}"}))
    assert ok.headers["Content-Type"] == "image/png" and "frame-ancestors 'none'" in ok.headers["Content-Security-Policy"]

    # revoking a key, disabling an account and resetting a password all take effect immediately
    key_id = site.ada.get("/api/keys?participant=scout")[0]["id"]
    site.ada.delete(f"/api/keys/{key_id}")
    with denied("revoked"):
        agent.get("/api/whoami")
    with denied("last active admin"):
        site.ada.patch("/api/admin/users/ada", {"admin": False})
    with denied("site admin"):
        site.hub(key).get("/api/admin/users")
    reset = site.ada.post("/api/admin/users/bo/reset")["token"]
    anonymous.post("/api/auth/reset", {"token": reset, "password": "a brand new password"})
    assert bo("GET", "/api/projects")[0] == 401  # the old session ended with the old password
    assert site.browser("bo@example.org")[0] == 401 and site.browser("bo@example.org", "a brand new password")[0] == 200
    site.ada.patch("/api/admin/users/bo", {"status": "disabled"})
    with denied("not active"):
        site.hub(key).get("/api/whoami")
    # repeated wrong passwords are slowed down, and everything above is in the audit log
    codes = [site.browser("ada@example.org", "wrong password")[0] for _ in range(9)]
    assert codes[0] == 401 and codes[-1] == 429
    actions = {e["action"] for e in site.ada.get("/api/admin/audit")["entries"]}
    assert {"login.failed", "key.revoke", "member.set", "password.reset", "user.update", "agent.create"} <= actions

    # the CLI signs in with a pasted key and manages agents
    assert cli(["login", "--key", site.ada.token]) == 0 and "as ada" in capsys.readouterr().out
    assert cli(["--as", "ada", "agent", "create", "helper", "--projects", "research"]) == 0
    assert "HUB_TOKEN=hub_" in capsys.readouterr().out


def _error(api, method, path, body):
    try:
        api.dispatch(method, path, {}, body, {})
    except Exception as e:
        return str(e)
    return ""


def test_plain_tracking_and_research_rules(site, capsys):
    agent, other = site.agent("agent-a"), site.agent("agent-b")
    # plain tracking: no hypothesis, no git, just init / log / summary / finish
    run = hubclient.init("yolo-n", project="detectors", config={"lr": 1e-3, "model": {"depth": 0.33}},
                         dataset="coco8@1.0", hub=site.hub(agent.token))
    for step in range(3):
        run.log({"val": {"map50": 0.5 + step / 10}, "train/loss": 1 / (step + 1)}, step=step * 100, epoch=step)
    run.note("resumed from last.ckpt")
    run.summary({"val/map50": 0.7, "train/loss": {"value": 0.33, "direction": "min"}})
    run.finish("good enough")
    r = agent.get("/api/runs/yolo-n")
    assert (r["project"], r["status"], r["last_step"], r["notes"][0]["body"]) == ("detectors", "finished", 200, "resumed from last.ckpt")
    assert agent.get("/api/runs/yolo-n/metrics")["val/map50"] == [[0, 0.5], [100, 0.6], [200, 0.7]]
    assert "depth" in agent.get("/api/runs/yolo-n/config")["text"]
    table = agent.get("/api/runs/table", project="detectors", columns="val/map50", sort="val/map50")
    assert table["runs"][0]["values"] == {"val/map50": 0.7} and table["available"][0]["key"] in ("val/map50", "train/loss")
    with denied("no longer accepts"):
        run.log({"x": 1}, step=300)
    # a training job that only holds the run's ingest token resumes and logs
    job = hubclient.init("yolo-s", project="detectors", hub=site.hub(agent.token))
    resumed = hubclient.init("yolo-s", resume=True, hub=site.hub(job.ingest_token))
    resumed.log({"train/loss": 0.2}, step=10)
    assert agent.get("/api/runs/yolo-s")["last_step"] == 10

    # the research project is strict: agents must state why; the verdict gate applies
    with denied("requires"):
        hubclient.init("dino-k8", project="research", config={"k": 8}, hub=site.hub(agent.token))
    agent.post("/api/runs", {"slug": "dino-k8", "title": "k=8", **STRICT})
    with denied("only agent-a"):
        other.patch("/api/runs/dino-k8", {"summary": "mine now"})
    obj = other.post("/api/comments", {"target": "run:dino-k8", "kind": "objection", "body": "k changed vs parent"})
    with denied("open objections"):
        agent.patch("/api/runs/dino-k8", {"status": "finished", "verdict": "supports", "conclusion": "ok"})
    agent.patch(f"/api/comments/{obj['id']}", {"status": "acknowledged"})
    agent.patch("/api/runs/dino-k8", {"status": "finished", "verdict": "supports", "conclusion": "AUROC +0.022"})
    assert agent.get("/api/runs", project="research")["runs"][0]["verdict"] == "supports"
    cmp = agent.get("/api/compare", runs="yolo-n,dino-k8")
    assert {d["key"] for d in cmp["config_diff"]} == {"lr", "model.depth", "k"} and cmp["curves"] == {}
    # a project maintainer can correct anyone's run
    assert site.ada.patch("/api/runs/dino-k8", {"summary": "k=8, reviewed"})["summary"] == "k=8, reviewed"

    assert cli(["--as", "agent-a", "--project", "detectors", "run", "table", "--columns", "val/map50"]) == 0
    assert "yolo-n" in capsys.readouterr().out
    assert cli(["--as", "agent-a", "run", "get", "dino-k8"]) == 0
    assert "AUROC +0.022" in capsys.readouterr().out


def test_eval_samples_for_every_task_type(site, tmp_path):
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    hub = site.agent("agent-e")
    run = hubclient.init("multi", project="research", title="multi", **STRICT, hub=hub)
    img = np.full((64, 64, 3), 0.4, dtype=np.float32)
    mask = np.zeros((64, 64), dtype=np.float32)
    mask[20:40, 20:40] = 1
    val = "shapes@1.0:val"
    rows = [
        {"sample": "s1", "facts": {"site": "north", "camera": "c12"}, "image": img,
         "true": {"class": "crack", "value": 8, "masks": {"object": mask}},
         "pred": {"class": "normal", "value": 0.6, "score": 0.9, "masks": {"object": mask * 0.5},
                  "heatmaps": {"attention": mask * 0.25}}},
        {"sample": "s2", "facts": {"site": "north"}, "true": {"class": "normal"}, "pred": {"class": "dent"}},
        {"sample": "d1", "facts": {"camera": "c9"}, "true": {"boxes": [[10, 10, 20, 20, "dent"]]},
         "pred": {"boxes": [[12, 11, 20, 20, "dent", 0.8], [50, 50, 5, 5, "dent", 0.3]]}},
        {"sample": "d2", "true": {"boxes": [[10, 10, 20, 20, "dent"]]}, "pred": {"boxes": []}},
        {"sample": "r1", "true": {"value": 3.0}, "pred": {"value": 2.5}},
        {"sample": "t1", "true": {"text": "a red square"}, "pred": {"text": "A red  square"}},
        {"sample": "t2", "true": {"text": "a red square"}, "pred": {"text": "a blue circle"}},
    ]
    res = run.log_eval(rows, step=1000, eval_set=val, epoch=1)
    assert res["outcomes"] == {"missed": 2, "false_alarm": 1, "wrong_class": 1, "unscored": 1, "correct": 1, "mismatch": 1}
    page = hub.get("/api/runs/multi/eval/samples", set=val)
    by = {r["sample"]: r for r in page["rows"]}
    assert by["s1"]["outcome"] == "missed" and set(by["s1"]["layers"]) == {"image", "object_gt", "object", "attention"}
    assert by["d1"]["metrics"] == {"tp": 1, "fp": 1, "fn": 0} and by["d1"]["outcome"] == "wrong_class"
    assert by["d2"]["outcome"] == "missed" and by["r1"]["error"] == 0.5 and by["t2"]["outcome"] == "mismatch"
    # any fact is a filter; several values of one fact are OR-ed, different facts AND-ed
    assert [r["sample"] for r in hub.get("/api/runs/multi/eval/samples", set=val, **{"fact.site": "north"})["rows"]] == ["s1", "s2"]
    assert hub.get("/api/runs/multi/eval/samples", set=val, **{"fact.camera": "c12,c9"})["total"] == 2
    assert hub.get("/api/runs/multi/eval/samples", set=val, outcome="missed", **{"fact.camera": "c12"})["total"] == 1
    facets = hub.get("/api/runs/multi/eval/facets", set=val)
    assert facets["kinds"] == {"boxes": True, "text": True, "value": True, "layers": True}
    assert facets["layers"] == {"attention": "heatmap", "object": "mask", "object_gt": "mask"}
    assert facets["facts"]["site"] == [["north", 2, 2]] and ["crack", "normal", 1] in facets["confusion"]
    # the stored map is the real probability map, decoded from the 8-bit PNG layer
    layer = urllib.request.urlopen(urllib.request.Request(f"{site.url}/blobs/{by['s1']['layers']['object']}",
                                                          headers={"Authorization": f"Bearer {hub.token}"}))
    got = np.asarray(Image.open(io.BytesIO(layer.read())).convert("L").resize((64, 64))) / 255
    assert 0.4 < got[25:35, 25:35].mean() < 0.6 and got[:10, :10].mean() < 0.05

    # a later checkpoint only overwrites what it sends; the sample timeline carries both steps
    run.log_eval([{"sample": "s1", "pred": {"class": "crack"}}], step=2000, eval_set=val, epoch=2)
    timeline = hub.get("/api/runs/multi/eval/sample", set=val, sample="s1")
    assert [(s["step"], s["outcome"]) for s in timeline["steps"]] == [(1000, "missed"), (2000, "correct")]
    assert timeline["truth"]["class"] == "crack" and set(timeline["static_layers"]) == {"image", "object_gt"}
    with denied("relabelled"):
        run.log_eval([{"sample": "s1", "true": {"class": "dent"}}], step=3000, eval_set=val)
    # another run on the same set shares the facts and compares per sample
    other = hubclient.init("multi-b", project="research", title="b", **{**STRICT, "parent": "multi"}, hub=hub)
    other.log_eval([{"sample": "s1", "pred": {"class": "crack"}}, {"sample": "s2", "pred": {"class": "normal"}}],
                   step=10, eval_set=val)
    fixed = hub.get("/api/runs/multi/eval/samples", set=val, step=1000, vs="multi-b", vs_outcome="correct")
    assert {r["sample"]: r["facts"].get("site") for r in fixed["rows"]} == {"s1": "north", "s2": "north"}
    # evaluation after closing, from a JSONL file through the CLI; the caller names the negative class
    run.finish("done", verdict="inconclusive")
    (tmp_path / "gt.png").write_bytes(png())
    (tmp_path / "res.jsonl").write_text(json.dumps({"sample": "m1", "facts": {"site": "south"}, "true": {"class": "dent"},
                                                    "pred": {"class": "clean"}, "image": "gt.png"}) + "\n")
    assert cli(["--as", "agent-e", "--project", "research", "run", "eval", "multi", str(tmp_path / "res.jsonl"),
                "--set", "field@2.1", "--step", "2000", "--negatives", "clean"]) == 0
    assert [s["set"] for s in hub.get("/api/runs/multi")["eval_sets"]] == ["field@2.1", val]
    assert hub.get("/api/runs/multi/eval/samples", set="field@2.1")["rows"][0]["outcome"] == "missed"


def test_plots_tables_and_system_metrics(site, monkeypatch):
    np = pytest.importorskip("numpy")
    from research_hub import plots
    from research_hub.integrations.sklearn import log_classifier

    site.agent("agent-a", project="detectors")
    monkeypatch.setenv("HUB_AGENT", "agent-a")
    monkeypatch.setenv("HUB_PROJECT", "detectors")
    run = hubclient.init("plots", system=["cpu", "memory"], system_interval=1)
    rng = np.random.default_rng(0)
    truth = rng.integers(0, 2, 400)
    score = np.clip(truth * 0.4 + rng.uniform(0, 0.6, 400), 0, 1)

    # charts from arrays, a list of dicts and numpy scalars; the server stores what the builders produce
    run.log_chart("eval/roc", plots.roc_curve(truth, score))
    run.log_chart("eval/confusion", plots.confusion_matrix(truth, score > 0.5, normalize="true"))
    run.log_chart("data/sizes", plots.scatter([{"w": 1, "h": np.float32(2), "kind": "a"}, {"w": 3, "h": float("nan"), "kind": "b"}],
                                              x="w", y="h", color="kind"))
    run.log_table("eval/rows", {"sample": ["a", "b"], "score": np.array([0.25, 0.75])})
    for step in (10, 20, 30):
        run.log_histogram("weights/head", rng.normal(0, step, 500), step=step, bins=16)
    index = {c["name"]: c for c in site.ada.get(f"/api/runs/{run.slug}/charts")}
    assert {n: c["kind"] for n, c in index.items()} == {
        "eval/roc": "line", "eval/confusion": "heatmap", "data/sizes": "scatter", "eval/rows": "table",
        "weights/head": "histogram"}
    assert index["weights/head"]["steps"] == [10, 20, 30] and index["eval/roc"]["steps"] == []
    roc = site.ada.get(f"/api/runs/{run.slug}/chart", name="eval/roc")
    assert roc["encoding"] == {"x": "fpr", "y": "tpr", "color": "class", "text": "threshold"} and roc["step"] is None
    assert roc["data"]["columns"]["class"][0].startswith("1 (AUC 0.9")
    assert site.ada.get(f"/api/runs/{run.slug}/chart", name="data/sizes")["data"]["columns"]["h"] == [2.0, None]
    hist = site.ada.get(f"/api/runs/{run.slug}/chart", name="weights/head", step=20, history=1)
    assert hist["step"] == 20 and [h["step"] for h in hist["history"]] == [10, 20, 30]
    assert sum(hist["data"]["columns"]["count"]) == 500
    assert site.ada.get(f"/api/runs/{run.slug}")["charts"] == 5

    # one call for a scikit-learn style estimator
    class Model:
        classes_ = np.array(["ok", "defect"])

        def predict(self, x):
            return self.classes_[(x[:, 0] > 0.5).astype(int)]

        def predict_proba(self, x):
            return np.c_[1 - x[:, 0], x[:, 0]]

    summary = log_classifier(run, Model(), score[:, None], Model.classes_[truth], prefix="test")
    assert 0.8 < summary["test/accuracy"] <= 1
    logged = {c["name"] for c in site.ada.get(f"/api/runs/{run.slug}/charts")}
    assert {"test/confusion_matrix", "test/roc", "test/precision_recall", "test/calibration", "test/per_class"} <= logged

    # what the server refuses
    with denied("needs encoding"):
        run.log_chart("bad", {"kind": "scatter", "data": {"columns": {"a": [1]}}, "encoding": {"x": "a"}})
    with denied("same number of rows"):
        run.log_chart("bad", {"kind": "table", "data": {"columns": {"a": [1], "b": [1, 2]}}})
    with denied("not in the data"):
        run.log_chart("bad", {"kind": "pie", "data": {"columns": {"a": [1]}}, "encoding": {"label": "a", "value": "b"}})
    with denied("only agent-a logs"):  # another member cannot write charts into this run
        site.agent("agent-b", project="detectors").post(f"/api/runs/{run.slug}/charts", {"name": "x", "chart": plots.pie(label=["a"], value=[1])})

    # two runs with a chart of the same name are offered side by side
    other = hubclient.init("plots-2")
    other.log_chart("eval/roc", plots.roc_curve(truth, 1 - score))
    shared = site.ada.get("/api/compare/charts", runs=f"{run.slug},{other.slug}")
    assert [(c["name"], c["runs"]) for c in shared] == [("eval/roc", [run.slug, other.slug])]

    # the background monitor logged machine readings, with seconds as the step, and they do not count as training steps
    run.log({"loss": 1.0}, step=7)
    deadline = time.time() + 15
    while "system/cpu_percent" not in site.ada.get(f"/api/runs/{run.slug}/metrics") and time.time() < deadline:
        time.sleep(0.2)
    metrics = site.ada.get(f"/api/runs/{run.slug}/metrics")
    assert 0 <= metrics["system/cpu_percent"][0][1] <= 100 and metrics["system/process_memory_gb"][0][1] > 0
    assert site.ada.get(f"/api/runs/{run.slug}")["last_step"] == 7
    run.finish("done")
    assert run._monitor.done.is_set()  # stopped with the run


def test_deleting_runs_and_projects(site, monkeypatch, capsys):
    np = pytest.importorskip("numpy")
    from research_hub import plots

    agent = site.agent("agent-a", project="detectors")
    monkeypatch.setenv("HUB_AGENT", "agent-a")
    monkeypatch.setenv("HUB_PROJECT", "detectors")
    keep, gone = hubclient.init("keep"), hubclient.init("gone", parent="keep")
    child = hubclient.init("child", parent="gone")
    gone.log({"loss": 1.0}, step=1)
    gone.log_chart("eval/pie", plots.pie(label=["a"], value=[1]))
    gone.log_eval([{"sample": "s1", "image": np.zeros((4, 4, 3)), "true": {"class": "a"}, "pred": {"class": "b"}}], step=1,
                  eval_set="shapes@1.0:val")
    comment = site.ada.post("/api/comments", {"target": "run:gone", "body": "why this seed?", "kind": "question"})

    # an agent cannot delete even its own run, and a person must send the run's name back
    with denied("only a person can delete"):
        agent.request("DELETE", "/api/runs/gone", query={"confirm": "gone"})
    with denied("cannot be undone"):
        site.ada.delete("/api/runs/gone")
    with denied("cannot be undone"):
        site.ada.request("DELETE", "/api/runs/gone", query={"confirm": "keep"})
    assert site.ada.get("/api/runs/gone")["charts"] == 1

    assert site.ada.request("DELETE", "/api/runs/gone", query={"confirm": "gone"}) == {"deleted": "gone"}
    with denied("does not exist|not found"):
        site.ada.get("/api/runs/gone")
    with site.store.connect() as conn:  # nothing of the run is left behind
        for table in ("metrics", "charts", "eval_results", "eval_layers", "artifacts", "run_notes"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run='gone'").fetchone()[0] == 0
        assert not conn.execute("SELECT 1 FROM comments WHERE id=?", (comment["id"],)).fetchone()
    assert site.ada.get(f"/api/runs/{child.slug}")["parent"] is None and site.ada.get(f"/api/runs/{keep.slug}")["children"] == []
    assert site.ada.get("/api/search", project="detectors", q="gone") == []
    assert site.ada.get("/api/admin/audit")["entries"][0]["action"] == "run.delete"

    # the CLI asks for the name; a project goes only for an owner, and takes everything with it
    hubclient.save_token(site.url, "ada", site.ada.token)
    monkeypatch.setattr("builtins.input", lambda prompt: "wrong")
    assert cli(["--as", "ada", "run", "delete", "child"]) == 1 and "nothing was deleted" in capsys.readouterr().err
    with denied("owner"):
        agent.request("DELETE", "/api/projects/detectors", query={"confirm": "detectors"})
    with denied("cannot be undone"):
        site.ada.delete("/api/projects/detectors")
    hubclient.init("elsewhere", hub=site.agent("agent-b", project="research"), **STRICT)
    assert cli(["--as", "ada", "project", "delete", "detectors", "--yes"]) == 0
    assert [p["slug"] for p in site.ada.get("/api/projects")] == ["research"]
    with site.store.connect() as conn:
        for table in ("runs", "memberships", "channels", "handbook", "events", "eval_sets", "search"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project='detectors'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM metrics WHERE run IN ('keep', 'child')").fetchone()[0] == 0
    assert site.ada.get("/api/runs/elsewhere")["project"] == "research"  # the other project is untouched


def test_mcp_tools_for_an_agent_without_a_shell(site, monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    owner = site.agent("agent-a", project="detectors")
    monkeypatch.setenv("HUB_AGENT", "agent-a")
    monkeypatch.setenv("HUB_PROJECT", "detectors")
    run = hubclient.init("yolo-n", title="YOLO nano")
    run.log_eval([{"sample": "img-1", "facts": {"camera": "c2"}, "image": np.full((16, 16, 3), 0.5),
                   "true": {"class": "cat", "masks": {"object": np.eye(16)}},
                   "pred": {"class": "dog", "score": 0.9, "masks": {"object": np.eye(16) * 0.8}}, "error": 0.9},
                  {"sample": "img-2", "facts": {"camera": "c1"}, "true": {"class": "cat"}, "pred": {"class": "cat"}}],
                 step=5, eval_set="pets@1.0:val")

    # a reviewer agent that only has MCP: one server process, its own key, newline-delimited JSON-RPC
    key = site.ada.post("/api/agents", {"name": "reviewer", "projects": ["detectors"]})["key"]
    env = {**os.environ, "HUB_URL": site.url, "HUB_TOKEN": key, "HUB_PROJECT": "detectors", "HUB_CREDENTIALS": str(tmp_path / "none.json")}
    env.pop("HUB_AGENT", None)
    server = subprocess.Popen([sys.executable, "-m", "research_hub", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, env=env)
    ids = iter(range(1, 100))

    def rpc(method, **params):
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": next(ids), "method": method, "params": params}) + "\n")
        server.stdin.flush()
        return json.loads(server.stdout.readline())["result"]

    def tool(name, **arguments):
        return rpc("tools/call", name=name, arguments=arguments)

    try:
        hello = rpc("initialize", protocolVersion="2025-06-18", capabilities={}, clientInfo={"name": "test", "version": "0"})
        assert hello["protocolVersion"] == "2025-06-18" and hello["serverInfo"]["name"] == "research-hub"
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")  # no reply expected
        names = {t["name"] for t in rpc("tools/list")["tools"]}
        assert {"inbox", "handbook", "run_get", "samples", "sample_image", "comment", "resolve", "msg_send"} <= names
        assert not [n for n in names if "delete" in n or "member" in n or "key" in n]

        assert "YOLO nano" in tool("run_get", run="yolo-n")["content"][0]["text"]
        listed = tool("samples", run="yolo-n", outcome="wrong_class", facts={"camera": "c2"})["content"][0]["text"]
        assert "1 matching samples" in listed and "img-1" in listed and "img-2" not in listed
        seen = tool("sample_image", run="yolo-n", sample="img-1")["content"]
        assert json.loads(seen[0]["text"])["predicted"]["class"] == "dog"
        shown = json.loads(seen[0]["text"])["images_below"]  # the photo, then the true and the predicted mask
        assert len(shown) == 3 and shown[0] == "image" and [b["type"] for b in seen] == ["text", "image", "image", "image"]
        assert seen[1]["mimeType"] == "image/webp" and seen[2]["mimeType"] == "image/png"
        assert base64.b64decode(seen[1]["data"])[:4] == b"RIFF"

        said = tool("comment", target="run:yolo-n", kind="question", body="Why is 'img-1' a \"dog\"? $HOME `x`")
        assert not said["isError"]
        comment = owner.get("/api/runs/yolo-n")["comments"][0]
        assert comment["author"] == "reviewer" and comment["body"] == "Why is 'img-1' a \"dog\"? $HOME `x`"  # nothing mangled
        assert not tool("msg_send", body="@agent-a see my question on run:yolo-n")["isError"]
        assert "see my question" in tool("msg_read")["content"][0]["text"]

        # refusals come back as tool errors the model can read, and the server keeps running
        refused = tool("note", run="yolo-n", body="not my run")
        assert refused["isError"] and "only agent-a logs" in refused["content"][0]["text"]
        assert tool("run_get")["isError"] and tool("nope")["isError"]
        assert rpc("ping") == {}
    finally:
        server.stdin.close()
        server.wait(timeout=10)


def test_model_graph_from_one_training_step(site, monkeypatch):
    site.agent("agent-a", project="detectors")
    monkeypatch.setenv("HUB_AGENT", "agent-a")
    monkeypatch.setenv("HUB_PROJECT", "detectors")
    run = hubclient.init("graph")

    # the server stores what it understands and refuses the rest
    graph = {"model": "Tiny", "params": 10, "nodes": [{"id": "a", "kind": "input", "name": "x", "type": "Input", "out_shape": [2, 3]},
                                                     {"id": "b", "kind": "module", "name": "fc", "type": "Linear", "junk": "dropped"}],
             "edges": [{"from": "a", "to": "b", "shape": [2, 3]}]}
    assert run.log_model_graph(graph, name="by-hand") == {"name": "by-hand", "nodes": 2, "edges": 1}
    stored = site.ada.get(f"/api/runs/{run.slug}/model-graph", name="by-hand")
    assert stored["nodes"][1] == {"id": "b", "kind": "module", "name": "fc", "type": "Linear"} and stored["params"] == 10
    with denied("between two nodes"):
        run.log_model_graph({**graph, "edges": [{"from": "a", "to": "missing"}]})
    with denied("finite number"):
        run.log_model_graph({**graph, "nodes": [{"id": "a", "kind": "op", "grad_norm": "big"}]})

    # an ordinary training loop with one added line
    torch = pytest.importorskip("torch")
    nn = torch.nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(3, 8, 3, padding=1), nn.ReLU())
            self.body = nn.Conv2d(8, 8, 3, padding=1)
            self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(8, 4))

        def forward(self, x):
            x = self.stem(x)
            return self.head(x + self.body(x))  # a skip connection, written as plain tensor maths

    torch.manual_seed(0)
    model = Net()
    optimiser = torch.optim.SGD(model.parameters(), lr=0.1)
    run.watch(model)
    for _ in range(2):
        loss = nn.functional.cross_entropy(model(torch.randn(2, 3, 8, 8)), torch.tensor([1, 3]))
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
    assert all(p.grad is not None for p in model.parameters())  # the step itself was untouched
    assert torch.Tensor.backward.__qualname__ == "Tensor.backward" and not any(m._forward_hooks for m in model.modules())

    g = site.ada.get(f"/api/runs/{run.slug}/model-graph", name="model")
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    assert g["model"] == "Net" and g["params"] == sum(p.numel() for p in model.parameters())
    assert nodes["stem.0"]["type"] == "Conv2d" and nodes["stem.0"]["out_shape"] == [2, 8, 8, 8] and nodes["stem.0"]["grad_norm"] > 0
    add = next(n for n in g["nodes"] if n["type"] == "Add")
    assert {("stem.1", add["id"]), ("body", add["id"]), (add["id"], "head.0")} <= edges  # both arms of the skip
    assert ("input:input", "stem.0") in edges and nodes["input:input"]["out_shape"] == [2, 3, 8, 8]
    losses = {n["loss"]: n for n in g["nodes"] if n["kind"] == "loss"}
    assert set(losses) == {"total"} and losses["total"]["type"] == "NllLoss" and losses["total"]["value"] > 0
    assert [m["name"] for m in site.ada.get(f"/api/runs/{run.slug}")["model_graphs"]] == ["by-hand", "model"]

    def train(name):
        run.watch(model, name=name)
        for _ in range(2):
            optimiser.zero_grad()
            nn.functional.cross_entropy(model(torch.randn(2, 3, 8, 8)), torch.tensor([1, 3])).backward()
            optimiser.step()
        assert torch.Tensor.backward.__qualname__ == "Tensor.backward" and not any(m._forward_hooks for m in model.modules())

    # a graph too large to send has its deepest blocks folded into one node each
    from research_hub import modelgraph
    monkeypatch.setattr(modelgraph, "MAX_NODES", 7)
    train("folded")
    folded = site.ada.get(f"/api/runs/{run.slug}/model-graph", name="folded")
    assert {n["id"] for n in folded["nodes"]} >= {"block:stem", "block:head", "body", "input:input"} and len(folded["nodes"]) == 7
    assert {("input:input", "block:stem"), ("block:stem", "body")} <= {(e["from"], e["to"]) for e in folded["edges"]}

    # a hook that fails (say, out of memory while reading statistics) costs the diagram, never the training step
    def out_of_memory(tensor):
        raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(modelgraph, "_sample", out_of_memory)
    train("broken")
    assert all(p.grad is not None for p in model.parameters())
    assert [m["name"] for m in site.ada.get(f"/api/runs/{run.slug}")["model_graphs"]] == ["by-hand", "folded", "model"]


def test_projects_handbook_feedback_and_chat(site, capsys):
    a, b, ada = site.agent("agent-a"), site.agent("agent-b"), site.hub(site.ada.token, "research")
    a.post("/api/runs", {"slug": "r1", "title": "r1", **STRICT})
    # projects are separate: runs, channels, handbook
    a_det = site.hub(a.token, "detectors")
    assert a_det.get("/api/runs")["total"] == 0
    a_det.post("/api/channels/general/messages", {"body": "hello detectors"})
    assert a.get("/api/channels/general/messages") == []
    # handbook: members propose, maintainers accept; a stale proposal cannot silently undo newer edits
    base = a.get("/api/handbook")
    stale = a.post("/api/handbook/proposals", {"text": base["text"] + "\nAgent rule.", "note": "add a rule"})
    with denied("maintainer"):
        a.put("/api/handbook", {"text": "mine", "note": "takeover"})
    ada.put("/api/handbook", {"text": base["text"] + "\nHuman rule.", "note": "newer", "expected_rev": base["rev"]})
    with denied("written against rev"):
        ada.put("/api/handbook", {"text": base["text"] + "\nAgent rule.", "note": "accept", "proposal_id": stale["id"]})
    ada.put("/api/handbook", {"text": base["text"] + "\nHuman rule.\nAgent rule.", "note": "merged", "proposal_id": stale["id"]})
    assert a.get("/api/inbox", project="research")["handbooks"][0]["rev"] == 3
    a.get("/api/handbook")
    assert a.get("/api/inbox", project="research")["handbooks"] == []
    # feedback: a person's comment must be answered with a reference; the owner's own notes are not feedback
    a.post("/api/comments", {"target": "run:r1", "kind": "note", "body": "paused at step 10"})
    c = ada.post("/api/comments", {"target": "run:r1", "kind": "request", "body": "please add a seed control"})
    with denied("resolution_ref"):
        a.patch(f"/api/comments/{c['id']}", {"status": "resolved"})
    a.post("/api/comments", {"target": "run:r1", "kind": "response", "body": "queued", "parent_id": c["id"]})
    listed = ada.get("/api/comments", status="open")
    assert [(x["kind"], x["self_note"]) for x in listed["comments"]] == [("request", False), ("note", True)]
    assert ada.get("/api/comments", status="open", **{"from": "human"})["total"] == 1
    assert [x["id"] for x in a.get("/api/inbox")["feedback"]] == [c["id"]]
    a.patch(f"/api/comments/{c['id']}", {"status": "resolved", "resolution_ref": "run:r1"})
    assert a.get("/api/inbox")["feedback"] == []
    # chat mentions reach the inbox; search finds the run; the activity feed is per project
    b.post("/api/channels/general/messages", {"body": "@agent-a see run:r1"})
    assert a.get("/api/inbox")["mentions"][0]["author"] == "agent-b"
    assert a.get("/api/search", q="r1")[0]["ref"] == "run:r1"
    assert {e["project"] for e in a.get("/api/events")} == {"research"}
    assert cli(["--as", "agent-a", "--project", "research", "inbox"]) == 0
    assert "@MENTIONS" in capsys.readouterr().out
