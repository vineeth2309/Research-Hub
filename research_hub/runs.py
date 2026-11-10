"""Runs: registration, provenance, status rules, metrics, summary values, artifacts, notes, tables and comparison."""

from __future__ import annotations

import base64
import json
import re
import secrets

from .core import DATASET_REF, Conflict, Forbidden, HubError, NotFound, choice, hash_token, now, rows, slug, text

STATUSES = ("planned", "running", "finished", "failed", "abandoned")
TERMINAL = ("finished", "failed", "abandoned")
VERDICTS = ("supports", "refutes", "inconclusive")
ARTIFACT_KINDS = ("image", "plot", "table", "file")
ARTIFACT_ROLES = ("", "tracked", "failure")
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
        "svg": "image/svg+xml", "json": "application/json", "txt": "text/plain", "md": "text/markdown",
        "csv": "text/csv", "log": "text/plain", "yaml": "text/yaml", "yml": "text/yaml", "html": "text/html"}
METRIC_KEY = re.compile(r"[A-Za-z0-9_./-]{1,80}")
TEXT_FIELDS = ("title", "summary", "hypothesis", "rationale", "expected")
PROVENANCE = ("app", "repo", "branch", "commit_sha", "config_path", "command", "dataset", "output_dataset")
STATUS_ORDER = "CASE r.status WHEN 'running' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END"


def _datasets(fields):
    for key in ("dataset", "output_dataset"):
        value = fields.get(key)
        if not value:
            continue
        refs = [r.strip() for r in value.split(",")]
        bad = [r for r in refs if not DATASET_REF.fullmatch(r)]
        if bad:
            raise HubError(f"{key} must be dataset references name@version, comma-separated for several; bad: {bad}")
        fields[key] = ",".join(refs)


class Runs:
    def create_run(self, actor, project, data: dict) -> dict:
        self._require_member(actor)
        name = data.get("slug") or data.get("name")
        run_slug = slug(name, "run slug")
        fields = {k: text(data, k, required=(k == "title"), limit=300 if k == "title" else 20000) for k in TEXT_FIELDS}
        opt = {k: text(data, k, required=False, limit=2000) for k in PROVENANCE}
        _datasets(opt)
        status = choice(data.get("status", "running"), ("planned", "running"), "initial status")
        topics = data.get("topics") or []
        if not isinstance(topics, list):
            raise HubError("topics must be a list of topic slugs")
        parent = data.get("parent")
        if parent in ("", "none"):
            parent = None
        config_text = data.get("config_text")
        if config_text is None and isinstance(data.get("config"), dict):
            config_text = json.dumps(data["config"], indent=2, sort_keys=True)
        pinned = data.get("pinned") or []
        if not isinstance(pinned, list) or any(not isinstance(k, str) for k in pinned):
            raise HubError("pinned must be a list of metric keys")
        ingest = "ingest_" + secrets.token_urlsafe(24)
        with self.connect(write=True) as conn:
            settings = json.loads(conn.execute("SELECT settings FROM projects WHERE slug=?",
                                               (self._project(conn, project),)).fetchone()[0])
            category = data.get("category") or settings.get("default_category") or "full-training"
            if not conn.execute("SELECT 1 FROM categories WHERE project=? AND slug=?", (project, category)).fetchone():
                known = [r[0] for r in conn.execute("SELECT slug FROM categories WHERE project=?", (project,))]
                raise HubError(f"unknown category {category!r} in {project}; known: {known}")
            if settings.get("strict") and actor.get("kind") == "agent":
                self._check_strict(conn, data, fields, opt, config_text, parent)
            for t in topics:
                if not conn.execute("SELECT 1 FROM topics WHERE project=? AND slug=?", (project, t)).fetchone():
                    raise HubError(f"unknown topic {t!r}; register it with `hub topic add` first")
            if parent and not conn.execute("SELECT 1 FROM runs WHERE slug=?", (parent,)).fetchone():
                raise HubError(f"parent run {parent!r} does not exist")
            if conn.execute("SELECT 1 FROM runs WHERE slug=?", (run_slug,)).fetchone():
                raise Conflict(f"run {run_slug!r} already exists; pick a new name (runs are never reused)")
            config_sha = self.db.put_blob(config_text.encode()) if config_text is not None else ""
            ts = now()
            conn.execute(
                "INSERT INTO runs(slug,project,title,owner,category,app,status,summary,hypothesis,rationale,expected,repo,"
                "branch,commit_sha,config_path,config_sha,command,parent,dataset,output_dataset,pinned,"
                "ingest_token_hash,created,started,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_slug, project, fields["title"], actor["name"], category, opt["app"], status, fields["summary"],
                 fields["hypothesis"], fields["rationale"], fields["expected"], opt["repo"], opt["branch"],
                 opt["commit_sha"], opt["config_path"], config_sha, opt["command"], parent, opt["dataset"],
                 opt["output_dataset"], json.dumps(pinned), hash_token(ingest), ts, ts if status == "running" else "", ts))
            for t in topics:
                conn.execute("INSERT INTO run_topics VALUES(?,?)", (run_slug, t))
            for ref in data.get("motivated_by") or []:
                self._owner_of(conn, ref)
                conn.execute("INSERT OR IGNORE INTO links VALUES(?,?,?,?,?)",
                             (f"run:{run_slug}", ref, "motivated_by", actor["name"], ts))
            self._index_run(conn, run_slug)
            self._event(conn, actor["name"], "run.create", f"run:{run_slug}", f"{status}: {fields['title']}", project)
        return {"slug": run_slug, "project": project, "status": status, "ingest_token": ingest}

    @staticmethod
    def _check_strict(conn, data, fields, opt, config_text, parent):
        """Research projects: agents must state why, what they expect, and what they are building on."""
        missing = [k for k in ("summary", "hypothesis", "rationale", "expected") if not fields[k]]
        if missing:
            raise HubError(f"this project requires {missing} on every agent run (see the handbook)")
        if parent is None and data.get("parent") != "none":
            raise HubError("parent is required: the baseline run slug, or 'none' for a first baseline")
        if data.get("status", "running") == "running":
            lacking = [k for k in ("branch", "commit_sha", "config_path") if not opt.get(k)]
            if lacking or config_text is None:
                raise HubError("a running run here needs branch, commit_sha, config_path and a config snapshot "
                               f"(missing: {lacking + ([] if config_text is not None else ['config_text'])}); "
                               "`hub run start` reads them from git")
            if not opt.get("dataset"):
                raise HubError("a running run here needs dataset: the input data as name@version")

    def _index_run(self, conn, run_slug):
        r = conn.execute("SELECT * FROM runs WHERE slug=?", (run_slug,)).fetchone()
        body = "\n".join([r["summary"], r["hypothesis"], r["rationale"], r["expected"], r["conclusion"], r["category"],
                          r["branch"], r["config_path"], r["owner"], r["dataset"], r["output_dataset"]])
        self._index(conn, f"run:{run_slug}", r["project"], "run", f"{run_slug} {r['title']}", body)

    def _load_run(self, conn, run_slug) -> dict:
        row = conn.execute("SELECT * FROM runs WHERE slug=?", (run_slug,)).fetchone()
        if not row:
            raise NotFound(f"run {run_slug!r} does not exist")
        return dict(row)

    def update_run(self, actor, run_slug, data: dict) -> dict:
        allowed = set(TEXT_FIELDS) | set(PROVENANCE) | {"status", "conclusion", "verdict", "config_text", "config",
                                                        "pinned"}
        unknown = set(data) - allowed
        if unknown:
            raise HubError(f"cannot update {sorted(unknown)} on a run")
        with self.connect(write=True) as conn:
            run = self._load_run(conn, run_slug)
            if actor.get("kind") == "ingest":
                if actor.get("run") != run_slug or set(data) - {"status", "conclusion", "pinned"}:
                    raise Forbidden("an ingest token can only report status for its own run")
                if data.get("status") not in (None, "running", "failed"):
                    raise Forbidden("an ingest token can only mark its run running or failed; the owner closes it")
            elif actor["name"] != run["owner"] and not self._moderator(actor):
                raise Forbidden(f"only {run['owner']} or a project maintainer can change this run; comment instead")
            changes = {}
            for key in set(TEXT_FIELDS) | set(PROVENANCE) | {"conclusion"}:
                if key in data:
                    changes[key] = text(data, key, required=(key == "title"), limit=20000)
            _datasets(changes)
            if "pinned" in data:
                if not isinstance(data["pinned"], list):
                    raise HubError("pinned must be a list of metric keys")
                changes["pinned"] = json.dumps([str(k) for k in data["pinned"]][:12])
            config_text = data.get("config_text")
            if config_text is None and isinstance(data.get("config"), dict):
                config_text = json.dumps(data["config"], indent=2, sort_keys=True)
            if config_text is not None:
                if run["status"] in TERMINAL:
                    raise HubError("the config of a closed run cannot change")
                changes["config_sha"] = self.db.put_blob(str(config_text).encode())
            if "verdict" in data:
                verdict = data["verdict"]
                if verdict is not None:
                    choice(verdict, VERDICTS, "verdict")
                if verdict in ("supports", "refutes"):
                    blocking = conn.execute(
                        "SELECT id, author FROM comments WHERE target=? AND kind='objection' AND status='open' "
                        "AND parent_id IS NULL", (f"run:{run_slug}",)).fetchall()
                    if blocking:
                        ids = ", ".join(f"#{b['id']} by {b['author']}" for b in blocking)
                        raise Conflict(f"open objections block a {verdict} verdict: {ids}. Answer them and mark them "
                                       "acknowledged/resolved, or use 'inconclusive'")
                changes["verdict"] = verdict
            if "status" in data:
                status = choice(data["status"], STATUSES, "status")
                if run["status"] in TERMINAL and status != run["status"]:
                    raise HubError(f"run is already {run['status']}; runs never reopen, start a new one")
                if status == "finished" and run["status"] == "planned":
                    raise HubError("a planned run never started; mark it abandoned instead")
                if status in TERMINAL and not (changes.get("conclusion") or run["conclusion"]):
                    raise HubError(f"a {status} run needs a conclusion: what happened and what to do next")
                if status == "finished" and not (changes.get("verdict", run["verdict"]) or not run["hypothesis"]):
                    raise HubError("a finished run with a hypothesis needs a verdict: supports, refutes or inconclusive")
                changes["status"] = status
                if status == "running" and not run["started"]:
                    changes["started"] = now()
                if status in TERMINAL:
                    changes["ended"] = now()
            if changes:
                changes["updated"] = now()
                sets = ", ".join(f"{k}=?" for k in changes)
                conn.execute(f"UPDATE runs SET {sets} WHERE slug=?", (*changes.values(), run_slug))
                self._index_run(conn, run_slug)
                described = ", ".join(f"{k}={v}" for k, v in changes.items()
                                      if k in ("status", "verdict") and v)
                self._event(conn, actor["name"], "run.update", f"run:{run_slug}", described or "edited", run["project"])
            return self._get_run(conn, run_slug)

    def issue_ingest_token(self, actor, run_slug) -> str:
        token = "ingest_" + secrets.token_urlsafe(24)
        with self.connect(write=True) as conn:
            run = self._load_run(conn, run_slug)
            if actor["name"] != run["owner"] and not self._moderator(actor):
                raise Forbidden("only the run owner can issue its ingest token")
            conn.execute("UPDATE runs SET ingest_token_hash=? WHERE slug=?", (hash_token(token), run_slug))
        return token

    def _writable(self, conn, actor, run_slug, allow_closed=False) -> dict:
        run = self._load_run(conn, run_slug)
        if actor.get("kind") == "ingest":
            if actor.get("run") != run_slug:
                raise Forbidden("ingest token belongs to another run")
        elif actor["name"] != run["owner"] and not self._moderator(actor):
            raise Forbidden(f"only {run['owner']} logs data to this run")
        if run["status"] in ("finished", "abandoned") and not (allow_closed and actor.get("kind") != "ingest"):
            raise HubError(f"run is {run['status']}; it no longer accepts data")
        return run

    # ---------------------------------------------------------------- deleting
    def _purge_run(self, conn, run_slug):
        """Remove a run and everything logged to it. Files stay in the blob store: other runs may share them."""
        ref, samples = f"run:{run_slug}", f"sample:{run_slug}/"
        comments = [r[0] for r in conn.execute(
            "SELECT id FROM comments WHERE target=? OR substr(target, 1, ?)=? "
            "OR target IN (SELECT 'artifact:' || id FROM artifacts WHERE run=?)", (ref, len(samples), samples, run_slug))]
        for comment in comments:
            conn.execute("DELETE FROM comments WHERE id=?", (comment,))
            conn.execute("DELETE FROM search WHERE ref=?", (f"comment:{comment}",))
        for table in ("run_topics", "run_notes", "metrics", "run_summary", "artifacts", "charts", "model_graphs",
                      "eval_results", "eval_layers"):
            conn.execute(f"DELETE FROM {table} WHERE run=?", (run_slug,))
        conn.execute("DELETE FROM links WHERE src=? OR dst=?", (ref, ref))
        conn.execute("DELETE FROM search WHERE ref=?", (ref,))
        conn.execute("UPDATE runs SET parent=NULL WHERE parent=?", (run_slug,))
        conn.execute("DELETE FROM runs WHERE slug=?", (run_slug,))

    def delete_run(self, actor, run_slug, confirm) -> dict:
        """Delete a run for good. Only a person may: the run's owner, or a project maintainer or owner."""
        if actor.get("kind") != "human":
            raise Forbidden("only a person can delete a run; an agent marks its run abandoned instead")
        with self.connect(write=True) as conn:
            run = self._load_run(conn, run_slug)
            if actor["name"] != run["owner"] and not self._moderator(actor):
                raise Forbidden("only the run's owner or a project maintainer can delete it")
            if confirm != run_slug:
                raise HubError(f"deleting a run cannot be undone; confirm by sending confirm={run_slug}")
            self._purge_run(conn, run_slug)
            self._event(conn, actor["name"], "run.delete", f"run:{run_slug}", run["title"], run["project"])
            self._audit(conn, actor, "run.delete", run_slug, f"project {run['project']}, owner {run['owner']}")
        return {"deleted": run_slug}

    # ----------------------------------------------------------------- logging
    def log_metrics(self, actor, run_slug, points: list) -> int:
        if not isinstance(points, list) or not points:
            raise HubError("points must be a non-empty list of {key, step, value}")
        out, ts = [], now()
        for p in points:
            try:
                key, step, value = str(p["key"]), int(p["step"]), float(p["value"])
            except (KeyError, TypeError, ValueError):
                raise HubError(f"bad metric point {p!r}; need key, integer step, numeric value") from None
            if not METRIC_KEY.fullmatch(key):
                raise HubError(f"metric key {key!r} must use letters, digits, _ . / -")
            if value != value or value in (float("inf"), float("-inf")):
                raise HubError(f"metric {key} at step {step} is not finite")
            out.append((run_slug, key, step, value, ts))
        with self.connect(write=True) as conn:
            self._writable(conn, actor, run_slug)
            conn.executemany("INSERT OR REPLACE INTO metrics VALUES(?,?,?,?,?)", out)
            conn.execute("UPDATE runs SET updated=?, status=CASE WHEN status='planned' THEN 'running' ELSE status END,"
                         " started=CASE WHEN started='' THEN ? ELSE started END WHERE slug=?", (ts, ts, run_slug))
        return len(out)

    def set_summary(self, actor, run_slug, values: dict) -> dict:
        if not isinstance(values, dict) or not values:
            raise HubError("summary must map metric key -> value or {value, direction}")
        with self.connect(write=True) as conn:
            run = self._writable(conn, actor, run_slug, allow_closed=True)
            for key, spec in values.items():
                if not isinstance(spec, dict):
                    spec = {"value": spec}
                direction = choice(spec.get("direction", "max"), ("max", "min", "none"), "direction")
                conn.execute("INSERT OR REPLACE INTO run_summary VALUES(?,?,?,?)",
                             (run_slug, str(key)[:80], float(spec["value"]), direction))
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (now(), run_slug))
            self._event(conn, actor["name"], "run.summary", f"run:{run_slug}", ", ".join(map(str, values)), run["project"])
            return self._get_run(conn, run_slug)

    def add_artifact(self, actor, run_slug, name, data_b64, kind="image", step=None, caption="", mime=None,
                     epoch=None, sample="", role="") -> dict:
        choice(kind, ARTIFACT_KINDS, "artifact kind")
        choice(role or "", ARTIFACT_ROLES, "artifact role")
        name = text({"n": name}, "n", limit=200)
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError):
            raise HubError("data must be base64") from None
        mime = mime or MIME.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")
        try:
            sha = self.db.put_blob(data)
        except ValueError as e:
            raise HubError(str(e)) from None
        with self.connect(write=True) as conn:
            run = self._writable(conn, actor, run_slug)
            cur = conn.execute(
                "INSERT INTO artifacts(run,step,epoch,sample,role,kind,name,caption,blob_sha,mime,author,created) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_slug, None if step is None else int(step), None if epoch is None else int(epoch),
                 str(sample or "")[:300], role or "", kind, name, caption or "", sha, mime, actor["name"], now()))
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (now(), run_slug))
            self._event(conn, actor["name"], "artifact.add", f"run:{run_slug}", f"{kind} {name}", run["project"])
            return {"id": cur.lastrowid, "blob_sha": sha, "url": f"/blobs/{sha}"}

    def add_note(self, actor, run_slug, body) -> dict:
        body = text({"b": body}, "b", limit=4000)
        with self.connect(write=True) as conn:
            run = self._writable(conn, actor, run_slug, allow_closed=True)
            cur = conn.execute("INSERT INTO run_notes(run,author,body,created) VALUES(?,?,?,?)",
                               (run_slug, actor["name"], body, now()))
            conn.execute("UPDATE runs SET updated=? WHERE slug=?", (now(), run_slug))
            self._event(conn, actor["name"], "run.note", f"run:{run_slug}", body, run["project"])
            return {"id": cur.lastrowid}

    # ----------------------------------------------------------------- reading
    def get_run(self, run_slug) -> dict:
        with self.connect() as conn:
            return self._get_run(conn, run_slug)

    def _get_run(self, conn, run_slug) -> dict:
        run = self._load_run(conn, run_slug)
        run.pop("ingest_token_hash")
        run["pinned"] = json.loads(run["pinned"])
        run["topics"] = [r[0] for r in conn.execute("SELECT topic FROM run_topics WHERE run=?", (run_slug,))]
        run["summary_metrics"] = rows(conn.execute("SELECT key,value,direction FROM run_summary WHERE run=? ORDER BY key",
                                                   (run_slug,)))
        if run["parent"]:
            parent = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM run_summary WHERE run=?",
                                                                 (run["parent"],))}
            for m in run["summary_metrics"]:
                m["parent_value"] = parent.get(m["key"])
        run["metric_keys"] = [r[0] for r in conn.execute("SELECT DISTINCT key FROM metrics WHERE run=? ORDER BY key",
                                                         (run_slug,))]
        last = conn.execute("SELECT MAX(step) FROM metrics WHERE run=? AND key NOT LIKE 'system/%'",
                            (run_slug,)).fetchone()[0]  # system metrics count seconds, not training steps
        run["last_step"] = last
        run["charts"] = conn.execute("SELECT COUNT(DISTINCT name) FROM charts WHERE run=?", (run_slug,)).fetchone()[0]
        run["model_graphs"] = rows(conn.execute("SELECT name, n_nodes, params FROM model_graphs WHERE run=? ORDER BY name",
                                                (run_slug,)))
        run["artifacts"] = rows(conn.execute(
            "SELECT id,step,epoch,sample,role,kind,name,caption,blob_sha,mime,created FROM artifacts WHERE run=? "
            "ORDER BY step, id", (run_slug,)))
        run["notes"] = rows(conn.execute("SELECT id,author,body,created FROM run_notes WHERE run=? ORDER BY id DESC",
                                         (run_slug,)))
        run["children"] = [r[0] for r in conn.execute("SELECT slug FROM runs WHERE parent=? ORDER BY created", (run_slug,))]
        run["links"] = rows(conn.execute("SELECT src,dst,relation FROM links WHERE src=? OR dst=?",
                                         (f"run:{run_slug}", f"run:{run_slug}")))
        run["eval_sets"] = self._eval_index(conn, run_slug)
        run["comments"] = self._comments_for(conn, [f"run:{run_slug}"] + [f"artifact:{a['id']}" for a in run["artifacts"]])
        run["open_comments"] = sum(1 for c in run["comments"] if c["status"] == "open" and c["parent_id"] is None
                                   and c["author"] != run["owner"])
        return run

    @staticmethod
    def _run_filters(project, f: dict):
        where, args = ["r.project=?"], [project]
        for col in ("category", "status", "owner"):
            if f.get(col):
                vals = str(f[col]).split(",")
                where.append(f"r.{col} IN ({','.join('?' * len(vals))})")
                args += vals
        if f.get("topic"):
            where.append("r.slug IN (SELECT run FROM run_topics WHERE topic=?)")
            args.append(f["topic"])
        if f.get("dataset"):
            where.append("r.dataset LIKE ?")
            args.append(f"%{f['dataset']}%")
        if f.get("q"):
            where.append("(r.slug LIKE ? OR r.title LIKE ? OR r.summary LIKE ?)")
            args += [f"%{f['q']}%"] * 3
        return " AND ".join(where), args

    def list_runs(self, project, filters=None, limit=50, offset=0) -> dict:
        where, args = self._run_filters(project, filters or {})
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM runs r WHERE {where}", args).fetchone()[0]
            out = rows(conn.execute(
                "SELECT r.slug,r.project,r.title,r.owner,r.category,r.status,r.verdict,r.summary,r.branch,r.commit_sha,"
                "r.parent,r.dataset,r.created,r.started,r.ended,r.updated,"
                "(SELECT COUNT(*) FROM comments c WHERE c.target='run:'||r.slug AND c.status='open' AND c.parent_id IS NULL"
                " AND c.author!=r.owner) AS open_comments,"
                "(SELECT MAX(step) FROM metrics m WHERE m.run=r.slug AND m.key NOT LIKE 'system/%') AS last_step "
                f"FROM runs r WHERE {where} ORDER BY {STATUS_ORDER}, r.updated DESC LIMIT ? OFFSET ?",
                args + [min(int(limit), 500), max(int(offset), 0)]))
            return {"runs": out, "total": total}

    def run_table(self, project, filters=None, columns=(), sort=None, desc=True, limit=50, offset=0) -> dict:
        """Runs as a table with chosen summary-metric columns; sortable by any of them."""
        where, args = self._run_filters(project, filters or {})
        columns = [c for c in columns if METRIC_KEY.fullmatch(c)][:16]
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM runs r WHERE {where}", args).fetchone()[0]
            order = f"{STATUS_ORDER}, r.updated DESC"
            if sort in columns:
                order = f"(SELECT value FROM run_summary s WHERE s.run=r.slug AND s.key=?) {'DESC' if desc else 'ASC'} NULLS LAST"
                args = args + [sort]
            elif sort in ("updated", "created", "slug", "owner", "status"):
                order = f"r.{sort} {'DESC' if desc else 'ASC'}"
            out = rows(conn.execute(
                "SELECT r.slug,r.title,r.owner,r.category,r.status,r.verdict,r.summary,r.parent,r.dataset,r.updated,"
                f"r.created FROM runs r WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                args + [min(int(limit), 500), max(int(offset), 0)]))
            slugs = [r["slug"] for r in out]
            values = {}
            if slugs and columns:
                marks = ",".join("?" * len(slugs))
                for r in conn.execute(f"SELECT run, key, value FROM run_summary WHERE run IN ({marks}) AND key IN "
                                      f"({','.join('?' * len(columns))})", slugs + columns):
                    values.setdefault(r["run"], {})[r["key"]] = r["value"]
            for r in out:
                r["values"] = values.get(r["slug"], {})
            keys = rows(conn.execute(
                "SELECT s.key, COUNT(*) AS n FROM run_summary s JOIN runs r ON r.slug=s.run WHERE r.project=? "
                "GROUP BY s.key ORDER BY n DESC, s.key", (project,)))
            return {"runs": out, "total": total, "columns": columns, "available": keys}

    def metrics(self, run_slug, keys=None) -> dict:
        with self.connect() as conn:
            self._load_run(conn, run_slug)
            sql, args = "SELECT key,step,value FROM metrics WHERE run=?", [run_slug]
            if keys:
                sql += f" AND key IN ({','.join('?' * len(keys))})"
                args += list(keys)
            out: dict[str, list] = {}
            for r in conn.execute(sql + " ORDER BY key, step", args):
                out.setdefault(r["key"], []).append([r["step"], r["value"]])
            return out

    def config_text(self, run_slug) -> str:
        with self.connect() as conn:
            run = self._load_run(conn, run_slug)
        path = self.db.blob_path(run["config_sha"])
        return path.read_text(errors="replace") if path else ""

    def compare(self, slugs: list[str]) -> dict:
        """Summary values, metric curves and a config diff for 2-8 runs."""
        slugs = [s for s in slugs if s][:8]
        if len(slugs) < 2:
            raise HubError("compare needs at least two run slugs")
        with self.connect() as conn:
            runs = {s: self._load_run(conn, s) for s in slugs}
            summary = {s: {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM run_summary WHERE run=?",
                                                                      (s,))} for s in slugs}
            directions = {r["key"]: r["direction"] for s in slugs for r in conn.execute(
                "SELECT key,direction FROM run_summary WHERE run=?", (s,))}
            curves: dict[str, dict] = {}
            for s in slugs:
                for r in conn.execute("SELECT key,step,value FROM metrics WHERE run=? ORDER BY key, step", (s,)):
                    curves.setdefault(r["key"], {}).setdefault(s, []).append([r["step"], r["value"]])
        configs = {}
        for s in slugs:
            path = self.db.blob_path(runs[s]["config_sha"])
            configs[s] = _flatten(_parse_config(path.read_text(errors="replace"))) if path else {}
        keys = sorted({k for c in configs.values() for k in c})
        diff = [{"key": k, **{s: configs[s].get(k) for s in slugs}} for k in keys
                if len({json.dumps(configs[s].get(k), sort_keys=True) for s in slugs}) > 1]
        shared = [k for k, by in curves.items() if len(by) > 1]
        return {"runs": [{k: runs[s][k] for k in ("slug", "title", "owner", "status", "verdict", "parent", "dataset",
                                                  "branch", "commit_sha", "category")} for s in slugs],
                "summary": summary, "directions": directions, "curves": {k: curves[k] for k in shared},
                "config_diff": diff}


def _parse_config(text_: str):
    try:
        return json.loads(text_)
    except ValueError:
        pass
    out: dict = {}
    stack = [(-1, out)]
    for line in text_.splitlines():  # minimal YAML: nested "key: value" mappings, enough for a diff
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        node = stack[-1][1] if stack else out
        value = value.strip()
        if value == "":
            node[key] = {}
            stack.append((indent, node[key]))
        else:
            node[key] = value.strip("'\"")
    return out


def _flatten(obj, prefix="") -> dict:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}."))
        return out
    return {prefix[:-1]: obj}
