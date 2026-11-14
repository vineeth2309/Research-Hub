"""Shared validation, errors, and the parts of the store that are not about accounts, runs, evals or discussion:
projects, categories/topics, the handbook, claims, events, search, inbox.

Every method that changes something takes an ``actor``: {name, kind, admin, role}, where ``role`` is the actor's
role in the project the call is about. The HTTP layer resolves it; see ``server.Api``."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from .db import Database

SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
REF = re.compile(r"(run|post|artifact|message|comment|topic|category|sample|design):([A-Za-z0-9._@:/-]{1,200})")
MENTION = re.compile(r"(?<![\w@])@([a-z0-9][a-z0-9_-]{0,39})")
DATASET_REF = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}@[A-Za-z0-9._-]{1,40}")

DEFAULT_CATEGORIES = [
    ("full-training", "Full training", "End-to-end training of a model"),
    ("ablation", "Ablation", "One change against a parent run"),
    ("hyperparameter-sweep", "Hyperparameter sweep", "Several runs varying one or two settings"),
    ("data-pipeline", "Data pipeline", "Labels, pseudo-labels, splits, augmentation"),
    ("evaluation-only", "Evaluation only", "Scoring an existing model on a dataset"),
]
VISIBILITY = ("private", "internal")  # private: members only; internal: every signed-in person can read
DEFAULT_CHANNELS = [("general", "Coordination and priorities"), ("ideas", "Half-formed ideas"),
                    ("infra", "Compute, environments, datasets")]
ROLES = ("viewer", "member", "maintainer", "owner")


def rank(role: str | None) -> int:
    return ROLES.index(role) if role in ROLES else -1


class HubError(Exception):
    status = 400


class NotFound(HubError):
    status = 404


class Forbidden(HubError):
    status = 403


class Unauthorized(HubError):
    status = 401


class Conflict(HubError):
    status = 409


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def text(data: dict, key: str, required=True, limit=20000) -> str:
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise HubError(f"{key} is required")
        return ""
    if not isinstance(value, str):
        raise HubError(f"{key} must be a string")
    value = value.strip()
    if len(value) > limit:
        raise HubError(f"{key} is longer than {limit} characters")
    return value


def slug(value, what="slug") -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise HubError(f"{what} must be lowercase letters, digits, '.', '_' or '-' (max 100): got {value!r}")
    return value


def choice(value, allowed, what):
    if value not in allowed:
        raise HubError(f"{what} must be one of {list(allowed)}, got {value!r}")
    return value


def number(value, what):
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise HubError(f"{what} must be a number, got {value!r}") from None
    if v != v or v in (float("inf"), float("-inf")):
        raise HubError(f"{what} is not finite")
    return v


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


class Core:
    def __init__(self, home):
        self.db = Database(home)
        self.connect = self.db.connect

    # ---------------------------------------------------------------- plumbing
    def _event(self, conn, actor, kind, ref, summary, project=""):
        conn.execute("INSERT INTO events(ts,project,actor,kind,ref,summary) VALUES(?,?,?,?,?,?)",
                     (now(), project, actor, kind, ref, summary[:300]))

    def _index(self, conn, ref, project, kind, title, body):
        conn.execute("DELETE FROM search WHERE ref=?", (ref,))
        conn.execute("INSERT INTO search(ref,project,kind,title,body) VALUES(?,?,?,?,?)", (ref, project, kind, title, body))

    def _participant(self, conn, name) -> dict:
        row = conn.execute("SELECT * FROM participants WHERE name=?", (name,)).fetchone()
        if not row:
            raise NotFound(f"participant {name!r} does not exist")
        return dict(row)

    def _project(self, conn, project) -> str:
        if not isinstance(project, str) or not conn.execute("SELECT 1 FROM projects WHERE slug=?", (project,)).fetchone():
            raise NotFound(f"project {project!r} does not exist, or you are not a member of it")
        return project

    def _owner_of(self, conn, ref: str) -> str | None:
        m = REF.fullmatch(ref or "")
        if not m:
            raise HubError(f"ref must look like run:<slug>, post:<slug>, design:<slug>, artifact:<id>, message:<id>, got {ref!r}")
        kind, key = m.groups()
        query = {
            "run": "SELECT owner FROM runs WHERE slug=?",
            "post": "SELECT owner FROM posts WHERE slug=?",
            "artifact": "SELECT r.owner FROM artifacts a JOIN runs r ON r.slug=a.run WHERE a.id=?",
            "message": "SELECT author FROM messages WHERE id=?",
            "comment": "SELECT author FROM comments WHERE id=?",
            "topic": "SELECT created_by FROM topics WHERE slug=?",
            "category": "SELECT created_by FROM categories WHERE slug=?",
            "sample": "SELECT r.owner FROM runs r WHERE slug=?",
            "design": "SELECT owner FROM designs WHERE slug=?",
        }[kind]
        if kind == "sample":  # sample:<run>/<set>/<id>
            key = key.split("/", 1)[0]
        if kind == "design":  # design:<slug> or design:<slug>@<rev>
            key = key.split("@", 1)[0]
        row = conn.execute(query, (key,)).fetchone()
        if not row:
            raise NotFound(f"{ref} does not exist")
        return row[0]

    def _project_of(self, conn, ref: str) -> str:
        m = REF.fullmatch(ref)
        kind, key = m.groups()
        if kind in ("run", "sample"):
            row = conn.execute("SELECT project FROM runs WHERE slug=?", (key.split("/", 1)[0],)).fetchone()
        elif kind == "post":
            row = conn.execute("SELECT project FROM posts WHERE slug=?", (key,)).fetchone()
        elif kind == "artifact":
            row = conn.execute("SELECT r.project FROM artifacts a JOIN runs r ON r.slug=a.run WHERE a.id=?", (key,)).fetchone()
        elif kind == "message":
            row = conn.execute("SELECT project FROM messages WHERE id=?", (key,)).fetchone()
        elif kind == "design":
            row = conn.execute("SELECT project FROM designs WHERE slug=?", (key.split("@", 1)[0],)).fetchone()
        elif kind == "comment":
            row = conn.execute("SELECT target FROM comments WHERE id=?", (key,)).fetchone()
            return self._project_of(conn, row[0]) if row else ""
        else:
            row = None
        return row[0] if row else ""

    def project_of(self, kind: str, key) -> str | None:
        """The project a run, post, comment, handbook proposal, claim or any ``kind:key`` ref belongs to."""
        with self.connect() as conn:
            if kind == "proposal":
                row = conn.execute("SELECT project FROM handbook_proposals WHERE id=?", (key,)).fetchone()
            elif kind == "design_proposal":
                row = conn.execute("SELECT project FROM design_proposals WHERE id=?", (key,)).fetchone()
            elif kind == "claim":
                row = conn.execute("SELECT project FROM claims WHERE resource=?", (key,)).fetchone()
            elif kind == "ref":
                return (self._project_of(conn, key) or None) if REF.fullmatch(str(key or "")) else None
            else:
                return self._project_of(conn, f"{kind}:{key}") or None
            return row[0] if row else None

    @staticmethod
    def _moderator(actor) -> bool:
        """Project maintainers and owners can act on other people's work."""
        return rank(actor.get("role")) >= rank("maintainer")

    def _require_maintainer(self, actor):
        if not actor or actor.get("kind") != "human" or not self._moderator(actor):
            raise Forbidden("only a project maintainer or owner can do this")

    @staticmethod
    def _require_member(actor):
        if not actor or actor.get("kind") not in ("agent", "human") or rank(actor.get("role")) < rank("member"):
            raise Forbidden("this needs a project member (viewers and run ingest tokens cannot do it)")

    # ---------------------------------------------------------------- projects
    def create_project(self, actor, slug_, title, description="", settings=None, visibility="private",
                       handbook: str | None = None) -> dict:
        """A new project owned by the person creating it, with default categories, channels and a first handbook."""
        if not actor or actor.get("kind") != "human":
            raise Forbidden("only a signed-in person can create a project")
        if self.site_settings()["create_projects"] == "admins" and not actor.get("admin"):
            raise Forbidden("on this hub only admins create projects")
        slug(slug_, "project slug")
        title = text({"t": title}, "t", limit=120)
        choice(visibility, VISIBILITY, "visibility")
        with self.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug_,)).fetchone():
                raise Conflict(f"project {slug_!r} already exists")
            ts, me = now(), actor["name"]
            conn.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?)",
                         (slug_, title, description or "", json.dumps(settings or {}), visibility, me, ts))
            conn.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (slug_, me, "owner", me, ts))
            for cslug, ctitle, desc in DEFAULT_CATEGORIES:
                conn.execute("INSERT INTO categories VALUES(?,?,?,?,?,?)", (slug_, cslug, ctitle, desc, me, ts))
            for cslug, ctitle in DEFAULT_CHANNELS:
                conn.execute("INSERT INTO channels VALUES(?,?,?,?,?)", (slug_, cslug, ctitle, me, ts))
            if handbook:
                conn.execute("INSERT INTO handbook VALUES(?,?,?,?,?,?)", (slug_, 1, handbook, me, "Initial handbook", ts))
                self._index(conn, f"handbook:{slug_}", slug_, "handbook", "Handbook", handbook)
            self._event(conn, me, "project.create", f"project:{slug_}", title, slug_)
        return self.get_project(slug_)

    def update_project(self, actor, slug_, data: dict) -> dict:
        self._require_maintainer(actor)
        with self.connect(write=True) as conn:
            self._project(conn, slug_)
            if "title" in data:
                conn.execute("UPDATE projects SET title=? WHERE slug=?", (text(data, "title", limit=120), slug_))
            if "description" in data:
                conn.execute("UPDATE projects SET description=? WHERE slug=?", (text(data, "description", False), slug_))
            if "settings" in data:
                if not isinstance(data["settings"], dict):
                    raise HubError("settings must be an object")
                conn.execute("UPDATE projects SET settings=? WHERE slug=?", (json.dumps(data["settings"]), slug_))
            if "visibility" in data:
                if actor.get("role") != "owner":
                    raise Forbidden("only a project owner changes who can see it")
                conn.execute("UPDATE projects SET visibility=? WHERE slug=?",
                             (choice(data["visibility"], VISIBILITY, "visibility"), slug_))
        return self.get_project(slug_)

    def delete_project(self, actor, slug_, confirm) -> dict:
        """Delete a project and everything in it: runs, posts, chat, handbook, members. Owners only."""
        if actor.get("kind") != "human" or actor.get("role") != "owner":
            raise Forbidden("only a project owner can delete the project")
        with self.connect(write=True) as conn:
            self._project(conn, slug_)
            if confirm != slug_:
                raise HubError(f"deleting a project cannot be undone; confirm by sending confirm={slug_}")
            runs = [r[0] for r in conn.execute("SELECT slug FROM runs WHERE project=?", (slug_,))]
            for run in runs:
                self._purge_run(conn, run)
            posts = [r[0] for r in conn.execute("SELECT slug FROM posts WHERE project=?", (slug_,))]
            for post in posts:
                ref = f"post:{post}"
                conn.execute("DELETE FROM comments WHERE target=?", (ref,))
                conn.execute("DELETE FROM links WHERE src=? OR dst=?", (ref, ref))
                conn.execute("DELETE FROM post_revisions WHERE slug=?", (post,))
                conn.execute("DELETE FROM citations WHERE post=?", (post,))
            for design in [r[0] for r in conn.execute("SELECT slug FROM designs WHERE project=?", (slug_,))]:
                self._purge_design(conn, design)
            conn.execute("DELETE FROM comments WHERE target IN (SELECT 'message:' || id FROM messages WHERE project=?)", (slug_,))
            conn.execute("DELETE FROM mentions WHERE message_id IN (SELECT id FROM messages WHERE project=?)", (slug_,))
            conn.execute("DELETE FROM eval_facts WHERE item IN (SELECT i.id FROM eval_items i JOIN eval_sets s "
                         "ON s.id=i.set_id WHERE s.project=?)", (slug_,))
            conn.execute("DELETE FROM eval_items WHERE set_id IN (SELECT id FROM eval_sets WHERE project=?)", (slug_,))
            conn.execute("DELETE FROM eval_set_versions WHERE set_id IN (SELECT id FROM eval_sets WHERE project=?)", (slug_,))
            for table in ("posts", "messages", "channels", "topics", "categories", "claims", "handbook",
                          "handbook_proposals", "events", "eval_sets", "memberships", "invites", "search"):
                conn.execute(f"DELETE FROM {table} WHERE project=?", (slug_,))
            conn.execute("DELETE FROM projects WHERE slug=?", (slug_,))
            self._audit(conn, actor, "project.delete", slug_, f"{len(runs)} runs, {len(posts)} posts")
        return {"deleted": slug_, "runs": len(runs), "posts": len(posts)}

    def get_project(self, slug_) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug_,)).fetchone()
            if not row:
                raise NotFound(f"project {slug_!r} does not exist")
            p = dict(row)
            p["settings"] = json.loads(p["settings"])
            return p

    def projects(self, actor) -> list[dict]:
        """The projects the actor can open, each with the actor's role in it."""
        with self.connect() as conn:
            out = rows(conn.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM runs r WHERE r.project=p.slug) AS runs,"
                " (SELECT COUNT(*) FROM runs r WHERE r.project=p.slug AND r.status='running') AS running,"
                " (SELECT COUNT(*) FROM memberships m WHERE m.project=p.slug) AS members,"
                " (SELECT MAX(ts) FROM events e WHERE e.project=p.slug) AS last_event FROM projects p ORDER BY created"))
            for p in out:
                p["settings"] = json.loads(p["settings"])
                p["role"] = self._role(conn, actor, p["slug"])
            return [p for p in out if p["role"]]

    # ------------------------------------------------------- categories, topics
    def add_category(self, actor, project, slug_, title, description=""):
        self._require_maintainer(actor)
        return self._add_taxonomy("categories", "category", actor, project, slug_, title, description)

    def add_topic(self, actor, project, slug_, title, description=""):
        self._require_member(actor)
        return self._add_taxonomy("topics", "topic", actor, project, slug_, title, description)

    def _add_taxonomy(self, table, kind, actor, project, slug_, title, description):
        slug(slug_, kind)
        title = text({"t": title}, "t", limit=120)
        with self.connect(write=True) as conn:
            self._project(conn, project)
            if conn.execute(f"SELECT 1 FROM {table} WHERE project=? AND slug=?", (project, slug_)).fetchone():
                raise Conflict(f"{kind} {slug_!r} already exists")
            conn.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?,?)",
                         (project, slug_, title, description or "", actor["name"], now()))
            self._index(conn, f"{kind}:{slug_}", project, kind, title, description or "")
            self._event(conn, actor["name"], f"{kind}.create", f"{kind}:{slug_}", f"new {kind} {title}", project)
        return {"slug": slug_, "title": title, "description": description or ""}

    def categories(self, project):
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT c.slug, c.title, c.description, c.created_by, "
                "(SELECT COUNT(*) FROM runs r WHERE r.project=c.project AND r.category=c.slug) AS runs "
                "FROM categories c WHERE project=? ORDER BY slug", (project,)))

    def topics(self, project):
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT t.slug, t.title, t.description, t.created_by, "
                "(SELECT COUNT(*) FROM posts p WHERE p.project=t.project AND p.topic=t.slug) AS posts, "
                "(SELECT COUNT(*) FROM run_topics rt JOIN runs r ON r.slug=rt.run WHERE r.project=t.project AND rt.topic=t.slug) AS runs "
                "FROM topics t WHERE project=? ORDER BY slug", (project,)))

    # ---------------------------------------------------------------- handbook
    def handbook(self, project, actor=None, rev=None) -> dict:
        with self.connect(write=True) as conn:
            self._project(conn, project)
            if rev:
                row = conn.execute("SELECT * FROM handbook WHERE project=? AND rev=?", (project, int(rev))).fetchone()
            else:
                row = conn.execute("SELECT * FROM handbook WHERE project=? ORDER BY rev DESC LIMIT 1", (project,)).fetchone()
            if not row:
                raise NotFound("no handbook yet")
            if actor and actor.get("kind") in ("agent", "human") and not rev:
                seen = json.loads(self._participant(conn, actor["name"])["handbook_seen"])
                seen[project] = row["rev"]
                conn.execute("UPDATE participants SET handbook_seen=? WHERE name=?", (json.dumps(seen), actor["name"]))
            out = dict(row)
            out["history"] = rows(conn.execute("SELECT rev, author, note, created FROM handbook WHERE project=? "
                                               "ORDER BY rev DESC LIMIT 30", (project,)))
            out["proposals"] = rows(conn.execute(
                "SELECT id, base_rev, author, note, status, created, decided_by FROM handbook_proposals "
                "WHERE project=? ORDER BY id DESC LIMIT 30", (project,)))
            return out

    def set_handbook(self, actor, project, text_, note, expected_rev=None, proposal_id=None) -> dict:
        self._require_maintainer(actor)
        text_ = text({"t": text_}, "t", limit=200000)
        note = text({"n": note}, "n", limit=300)
        with self.connect(write=True) as conn:
            self._project(conn, project)
            current = conn.execute("SELECT COALESCE(MAX(rev),0) FROM handbook WHERE project=?", (project,)).fetchone()[0]
            if expected_rev is not None and int(expected_rev) != current:
                raise Conflict(f"handbook is at rev {current}, you edited rev {expected_rev}; reload and re-apply")
            if proposal_id is not None:
                prop = conn.execute("SELECT base_rev, text FROM handbook_proposals WHERE id=? AND project=?",
                                    (int(proposal_id), project)).fetchone()
                if not prop:
                    raise NotFound(f"proposal {proposal_id} does not exist in this project")
                if prop["base_rev"] != current and prop["text"] == text_:
                    raise Conflict(f"proposal {proposal_id} was written against rev {prop['base_rev']}, and the handbook "
                                   f"is now at rev {current}; accepting it as is would undo the changes since. Merge it "
                                   "into the current text, or ask the author to propose again")
            rev = current + 1
            conn.execute("INSERT INTO handbook VALUES(?,?,?,?,?,?)", (project, rev, text_, actor["name"], note, now()))
            if proposal_id is not None:
                conn.execute("UPDATE handbook_proposals SET status='accepted', decided_by=? WHERE id=?",
                             (actor["name"], int(proposal_id)))
            self._index(conn, f"handbook:{project}", project, "handbook", "Handbook", text_)
            self._event(conn, actor["name"], "handbook.update", f"handbook:{rev}", note, project)
        return {"rev": rev}

    def propose_handbook(self, actor, project, text_, note) -> dict:
        self._require_member(actor)
        text_ = text({"t": text_}, "t", limit=200000)
        note = text({"n": note}, "n", limit=300)
        with self.connect(write=True) as conn:
            self._project(conn, project)
            base = conn.execute("SELECT COALESCE(MAX(rev),0) FROM handbook WHERE project=?", (project,)).fetchone()[0]
            cur = conn.execute("INSERT INTO handbook_proposals(project,base_rev,text,author,note,status,created) "
                               "VALUES(?,?,?,?,?,'open',?)", (project, base, text_, actor["name"], note, now()))
            self._event(conn, actor["name"], "handbook.propose", f"proposal:{cur.lastrowid}", note, project)
            return {"id": cur.lastrowid, "base_rev": base}

    def handbook_proposal(self, pid) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM handbook_proposals WHERE id=?", (int(pid),)).fetchone()
            if not row:
                raise NotFound(f"proposal {pid} does not exist")
            return dict(row)

    def reject_proposal(self, actor, pid) -> dict:
        self._require_maintainer(actor)
        with self.connect(write=True) as conn:
            cur = conn.execute("UPDATE handbook_proposals SET status='rejected', decided_by=? WHERE id=? AND status='open'",
                               (actor["name"], int(pid)))
            if not cur.rowcount:
                raise NotFound(f"no open proposal {pid}")
        return {"id": int(pid), "status": "rejected"}

    # ------------------------------------------------------------------ claims
    def claim(self, actor, project, resource, note="", hours=24.0) -> dict:
        self._require_member(actor)
        resource = text({"r": resource}, "r", limit=200)
        expires = (datetime.now(timezone.utc) + timedelta(hours=float(hours))).isoformat(timespec="seconds")
        with self.connect(write=True) as conn:
            self._project(conn, project)
            row = conn.execute("SELECT owner, expires FROM claims WHERE resource=?", (resource,)).fetchone()
            if row and row["owner"] != actor["name"] and row["expires"] > now():
                raise Conflict(f"{resource!r} is claimed by {row['owner']} until {row['expires']}; ask them in chat")
            conn.execute("INSERT OR REPLACE INTO claims VALUES(?,?,?,?,?,?)",
                         (resource, project, actor["name"], note or "", now(), expires))
            self._event(conn, actor["name"], "claim", f"claim:{resource}", note or resource, project)
        return {"resource": resource, "owner": actor["name"], "expires": expires}

    def release(self, actor, resource) -> None:
        with self.connect(write=True) as conn:
            cur = conn.execute("DELETE FROM claims WHERE resource=? AND (owner=? OR ?)",
                               (resource, actor["name"], self._moderator(actor)))
            if not cur.rowcount:
                raise NotFound("no such claim of yours")

    def claims(self, project) -> list[dict]:
        with self.connect() as conn:
            return rows(conn.execute("SELECT * FROM claims WHERE project=? AND expires>? ORDER BY created",
                                     (project, now())))

    # ------------------------------------------------------- search and events
    def search(self, project, q, limit=30) -> list[dict]:
        q = text({"q": q}, "q", limit=200)
        terms = [t for t in re.findall(r"[\w.-]+", q) if t]
        if not terms:
            return []
        match = " ".join('"' + t.replace('"', "") + '"*' for t in terms)
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT ref, kind, title, snippet(search, 4, '[', ']', ' … ', 12) AS snippet FROM search "
                "WHERE search MATCH ? AND project=? ORDER BY rank LIMIT ?", (match, project, int(limit))))

    def events(self, project, since=0, limit=100) -> list[dict]:
        with self.connect() as conn:
            return rows(conn.execute("SELECT * FROM events WHERE id>? AND project=? ORDER BY id DESC LIMIT ?",
                                     (int(since), project, min(int(limit), 500))))

    # ------------------------------------------------------------------- inbox
    def inbox(self, actor, project=None) -> dict:
        name = actor["name"]
        with self.connect() as conn:
            me = self._participant(conn, name)
            seen_rev = json.loads(me["handbook_seen"])
            owned = ("SELECT 'run:'||slug FROM runs WHERE owner=:n UNION SELECT 'post:'||slug FROM posts WHERE owner=:n "
                     "UNION SELECT 'artifact:'||a.id FROM artifacts a JOIN runs r ON r.slug=a.run WHERE r.owner=:n "
                     "UNION SELECT 'message:'||id FROM messages WHERE author=:n "
                     "UNION SELECT 'design:'||slug FROM designs WHERE owner=:n")
            feedback = rows(conn.execute(
                f"SELECT c.*, p.kind AS author_kind FROM comments c LEFT JOIN participants p ON p.name=c.author "
                f"WHERE c.parent_id IS NULL AND c.status='open' AND c.author!=:n AND c.target IN ({owned}) "
                "ORDER BY (p.kind='human') DESC, c.id", {"n": name}))
            replies = rows(conn.execute(
                "SELECT r.*, c.target AS on_target FROM comments r JOIN comments c ON c.id=r.parent_id "
                "WHERE c.author=:n AND r.author!=:n AND r.created>:seen ORDER BY r.id", {"n": name, "seen": me["inbox_seen_at"]}))
            mentions = rows(conn.execute(
                "SELECT m.* FROM messages m JOIN mentions x ON x.message_id=m.id WHERE x.participant=:n "
                "AND m.created>:seen ORDER BY m.id", {"n": name, "seen": me["inbox_seen_at"]}))
            thread_replies = rows(conn.execute(
                "SELECT m.* FROM messages m JOIN messages root ON root.id=m.parent_id WHERE root.author=:n "
                "AND m.author!=:n AND m.created>:seen ORDER BY m.id", {"n": name, "seen": me["inbox_seen_at"]}))
            mine = [r[0] for r in conn.execute("SELECT slug FROM projects") if self._role(conn, actor, r[0])]
            projects = [p for p in mine if not project or p == project]
            handbooks = []
            for p in projects:
                hb = conn.execute("SELECT project, rev, author, note, created FROM handbook WHERE project=? "
                                  "ORDER BY rev DESC LIMIT 1", (p,)).fetchone()
                if hb and hb["rev"] > seen_rev.get(p, 0):
                    handbooks.append({**dict(hb), "seen": seen_rev.get(p, 0),
                                      "action": f"run `hub handbook --project {p}` and follow the new revision"})
            proposals = []
            if actor.get("kind") == "human":
                proposals = [p for p in rows(conn.execute(
                    "SELECT id, project, base_rev, author, note, created FROM handbook_proposals WHERE status='open'"))
                    if p["project"] in projects and rank(self._role(conn, actor, p["project"])) >= rank("maintainer")]
            seen = {"n": name, "seen": me["inbox_seen_at"]}
            designs = [d for d in rows(conn.execute(
                "SELECT d.slug, d.project, d.title, d.rev, r.author, r.note, r.created FROM designs d JOIN design_revisions r "
                "ON r.design=d.slug AND r.rev=d.rev WHERE r.author!=:n AND r.created>:seen ORDER BY r.created", seen))
                if d["project"] in projects]
            design_proposals = []
            if actor.get("kind") == "human":
                design_proposals = [p for p in rows(conn.execute(
                    "SELECT id, design, project, base_rev, author, note, created FROM design_proposals WHERE status='open'"))
                    if p["project"] in projects and rank(self._role(conn, actor, p["project"])) >= rank("member")]
            decisions = rows(conn.execute(
                "SELECT id, design, project, status, decided_by, note FROM design_proposals WHERE author=:n "
                "AND status!='open' AND decided>:seen ORDER BY id", seen))
            stale = rows(conn.execute(
                "SELECT slug, project, status, updated FROM runs WHERE owner=? AND status='running' AND updated<?",
                (name, (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(timespec="seconds"))))
            return {"participant": name, "handbooks": handbooks, "feedback": feedback, "replies": replies,
                    "mentions": mentions, "thread_replies": thread_replies, "handbook_proposals": proposals,
                    "designs": designs, "design_proposals": design_proposals, "design_decisions": decisions,
                    "stale_runs": stale}

    def ack_inbox(self, actor) -> None:
        with self.connect(write=True) as conn:
            conn.execute("UPDATE participants SET inbox_seen_at=? WHERE name=?", (now(), actor["name"]))
