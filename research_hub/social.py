"""Research posts with citations and revisions, threaded comments with status, chat with @mentions."""

from __future__ import annotations

import json

from .core import MENTION, REF, Conflict, Forbidden, HubError, NotFound, choice, now, rows, slug, text

POST_KINDS = ("summary", "finding", "question", "proposal", "decision", "reference")
BASES = ("literature", "observed", "hypothesis", "user_requirement", "mixed")
COMMENT_KINDS = ("note", "question", "request", "objection", "support", "response")
COMMENT_STATUSES = ("open", "acknowledged", "resolved")


class Social:
    # ------------------------------------------------------------------- posts
    def put_post(self, actor, project, data: dict, expected_revision: int) -> dict:
        self._require_member(actor)
        post_slug = slug(data.get("slug"), "post slug")
        title = text(data, "title", limit=300)
        body = text(data, "body", limit=200000)
        kind = choice(data.get("kind", "finding"), POST_KINDS, "kind")
        basis = choice(data.get("basis", "observed"), BASES, "basis")
        citations = data.get("citations") or []
        refs = data.get("refs") or []
        if not isinstance(citations, list) or not isinstance(refs, list):
            raise HubError("citations and refs must be lists")
        if basis == "literature" and not citations:
            raise HubError("a literature post needs citations: [{title, url, venue}]")
        if basis == "observed" and not any(r.startswith("run:") for r in refs):
            raise HubError("an observed post must reference the runs it draws on: refs: ['run:<slug>', ...]")
        for c in citations:
            if not isinstance(c, dict) or not c.get("title") or not c.get("url"):
                raise HubError("each citation needs title and url")
        with self.connect(write=True) as conn:
            self._project(conn, project)
            topic = data.get("topic")
            if not conn.execute("SELECT 1 FROM topics WHERE project=? AND slug=?", (project, topic)).fetchone():
                raise HubError(f"unknown topic {topic!r}; register it with `hub topic add`")
            for ref in refs:
                self._owner_of(conn, ref)
            ts = now()
            existing = conn.execute("SELECT owner, revision, project FROM posts WHERE slug=?", (post_slug,)).fetchone()
            if existing:
                if existing["owner"] != actor["name"] and actor.get("kind") != "human":
                    raise Forbidden(f"only {existing['owner']} revises this post; comment on it instead")
                if existing["revision"] != int(expected_revision):
                    raise Conflict(f"post is at revision {existing['revision']}; re-read it and apply your edit again")
                revision = existing["revision"] + 1
                conn.execute("UPDATE posts SET topic=?,kind=?,basis=?,title=?,body=?,revision=?,updated=? WHERE slug=?",
                             (topic, kind, basis, title, body, revision, ts, post_slug))
                conn.execute("DELETE FROM citations WHERE post=?", (post_slug,))
                conn.execute("DELETE FROM links WHERE src=? AND relation='references'", (f"post:{post_slug}",))
            else:
                revision = 1
                conn.execute("INSERT INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (post_slug, project, topic, actor["name"], kind, basis, title, body, 1, ts, ts))
            for i, c in enumerate(citations):
                conn.execute("INSERT INTO citations VALUES(?,?,?,?,?)",
                             (post_slug, i, str(c["title"])[:300], str(c["url"])[:500], str(c.get("venue", ""))[:200]))
            for ref in refs:
                conn.execute("INSERT OR IGNORE INTO links VALUES(?,?,?,?,?)",
                             (f"post:{post_slug}", ref, "references", actor["name"], ts))
            conn.execute("INSERT INTO post_revisions VALUES(?,?,?,?,?)",
                         (post_slug, revision, json.dumps(data), actor["name"], ts))
            self._index(conn, f"post:{post_slug}", project, "post", title, body)
            self._event(conn, actor["name"], "post.put", f"post:{post_slug}", f"rev {revision}: {title}", project)
        return self.get_post(post_slug)

    def get_post(self, post_slug) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM posts WHERE slug=?", (post_slug,)).fetchone()
            if not row:
                raise NotFound(f"post {post_slug!r} does not exist")
            post = dict(row)
            post["citations"] = rows(conn.execute("SELECT title,url,venue FROM citations WHERE post=? ORDER BY idx",
                                                  (post_slug,)))
            post["refs"] = [r[0] for r in conn.execute("SELECT dst FROM links WHERE src=? AND relation='references'",
                                                       (f"post:{post_slug}",))]
            post["referenced_by"] = [r[0] for r in conn.execute("SELECT src FROM links WHERE dst=?", (f"post:{post_slug}",))]
            post["comments"] = self._comments_for(conn, [f"post:{post_slug}"])
            post["revisions"] = rows(conn.execute("SELECT revision, author, created FROM post_revisions WHERE slug=? "
                                                  "ORDER BY revision", (post_slug,)))
            return post

    def list_posts(self, project, topic=None, owner=None, kind=None, limit=50, offset=0) -> dict:
        where, args = ["p.project=?"], [project]
        for col, val in (("p.topic", topic), ("p.owner", owner), ("p.kind", kind)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM posts p WHERE {' AND '.join(where)}", args).fetchone()[0]
            out = rows(conn.execute(
                "SELECT p.slug,p.topic,p.owner,p.kind,p.basis,p.title,p.body,p.revision,p.created,p.updated,"
                "(SELECT COUNT(*) FROM comments c WHERE c.target='post:'||p.slug) AS comment_count "
                f"FROM posts p WHERE {' AND '.join(where)} ORDER BY p.updated DESC LIMIT ? OFFSET ?",
                args + [min(int(limit), 500), max(int(offset), 0)]))
            for p in out:
                p["refs"] = [r[0] for r in conn.execute("SELECT dst FROM links WHERE src=? AND relation='references'",
                                                        (f"post:{p['slug']}",))]
            return {"posts": out, "total": total}

    # ---------------------------------------------------------------- comments
    def _comments_for(self, conn, targets) -> list[dict]:
        if not targets:
            return []
        marks = ",".join("?" * len(targets))
        return rows(conn.execute(
            f"SELECT c.*, p.kind AS author_kind FROM comments c LEFT JOIN participants p ON p.name=c.author "
            f"WHERE c.target IN ({marks}) ORDER BY c.id", targets))

    def comment(self, actor, target, body, kind="note", anchor="", parent_id=None) -> dict:
        self._require_member(actor)
        choice(kind, COMMENT_KINDS, "comment kind")
        body = text({"b": body}, "b", limit=20000)
        with self.connect(write=True) as conn:
            owner = self._owner_of(conn, target)
            project = self._project_of(conn, target)
            if parent_id is not None and not conn.execute("SELECT 1 FROM comments WHERE id=? AND target=?",
                                                          (int(parent_id), target)).fetchone():
                raise NotFound(f"parent comment {parent_id} is not on {target}")
            ts = now()
            cur = conn.execute(
                "INSERT INTO comments(target,author,kind,anchor,body,status,parent_id,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (target, actor["name"], kind, (anchor or "")[:200], body, "open", parent_id, ts, ts))
            self._index(conn, f"comment:{cur.lastrowid}", project, "comment", f"{kind} on {target}", body)
            self._event(conn, actor["name"], "comment.create", target, f"{kind} to {owner}: {body}", project)
            return {"id": cur.lastrowid, "target": target, "owner": owner}

    def list_comments(self, project, status=None, from_kind=None, to=None, limit=50, offset=0) -> dict:
        """Top-level comments with replies. status: open|acknowledged|resolved|answered (not open).
        from_kind: human|agent. to: a participant name whose work the comments are on."""
        where, args = ["c.parent_id IS NULL"], []
        if status == "answered":
            where.append("c.status!='open'")
        elif status:
            where.append("c.status=?")
            args.append(status)
        if from_kind:
            where.append("p.kind=?")
            args.append(from_kind)
        with self.connect() as conn:
            all_rows = rows(conn.execute(
                f"SELECT c.*, p.kind AS author_kind FROM comments c LEFT JOIN participants p ON p.name=c.author "
                f"WHERE {' AND '.join(where)} ORDER BY c.id DESC", args))
            out = []
            for c in all_rows:
                try:
                    c["owner"] = self._owner_of(conn, c["target"])
                    c["project"] = self._project_of(conn, c["target"])
                except NotFound:
                    continue
                if c["project"] != project or (to and c["owner"] != to):
                    continue
                c["self_note"] = c["owner"] == c["author"]
                out.append(c)
            total = len(out)
            out = out[max(int(offset), 0):max(int(offset), 0) + min(int(limit), 500)]
            for c in out:
                c["replies"] = rows(conn.execute("SELECT * FROM comments WHERE parent_id=? ORDER BY id", (c["id"],)))
            return {"comments": out, "total": total}

    def set_comment_status(self, actor, comment_id, status, resolution_ref="") -> dict:
        self._require_member(actor)
        choice(status, COMMENT_STATUSES, "status")
        with self.connect(write=True) as conn:
            c = conn.execute("SELECT c.*, p.kind AS author_kind FROM comments c LEFT JOIN participants p ON p.name=c.author "
                             "WHERE c.id=?", (int(comment_id),)).fetchone()
            if not c:
                raise NotFound(f"comment {comment_id} does not exist")
            owner = self._owner_of(conn, c["target"])
            if actor["name"] not in (owner, c["author"]) and actor.get("kind") != "human":
                raise Forbidden("only the comment author, the target owner or a human changes its status")
            if (c["author_kind"] == "human" and actor.get("kind") != "human" and status == "resolved"
                    and not (resolution_ref and REF.fullmatch(resolution_ref))):
                raise HubError("resolving a human's comment needs resolution_ref: the comment, run or post that answers it")
            conn.execute("UPDATE comments SET status=?, resolution_ref=?, updated=? WHERE id=?",
                         (status, resolution_ref or "", now(), int(comment_id)))
            self._event(conn, actor["name"], "comment.status", c["target"], f"#{comment_id} {status}",
                        self._project_of(conn, c["target"]))
        return {"id": int(comment_id), "status": status}

    # ---------------------------------------------------------------- messages
    def add_channel(self, actor, project, channel, title=""):
        self._require_member(actor)
        slug(channel, "channel")
        with self.connect(write=True) as conn:
            self._project(conn, project)
            if conn.execute("SELECT 1 FROM channels WHERE project=? AND slug=?", (project, channel)).fetchone():
                raise Conflict(f"channel {channel!r} already exists")
            conn.execute("INSERT INTO channels VALUES(?,?,?,?,?)", (project, channel, title or "", actor["name"], now()))
        return {"slug": channel, "title": title or ""}

    def channels(self, project):
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT c.slug, c.title, (SELECT COUNT(*) FROM messages m WHERE m.project=c.project AND m.channel=c.slug)"
                " AS messages, (SELECT MAX(created) FROM messages m WHERE m.project=c.project AND m.channel=c.slug) AS last"
                " FROM channels c WHERE project=? ORDER BY slug", (project,)))

    def post_message(self, actor, project, channel, body, parent_id=None) -> dict:
        self._require_member(actor)
        body = text({"b": body}, "b", limit=20000)
        with self.connect(write=True) as conn:
            if not conn.execute("SELECT 1 FROM channels WHERE project=? AND slug=?", (project, channel)).fetchone():
                raise NotFound(f"channel {channel!r} does not exist in {project}")
            if parent_id is not None and not conn.execute(
                    "SELECT 1 FROM messages WHERE id=? AND project=? AND channel=?", (int(parent_id), project, channel)).fetchone():
                raise NotFound(f"message {parent_id} is not in #{channel}")
            cur = conn.execute("INSERT INTO messages(project,channel,parent_id,author,body,created) VALUES(?,?,?,?,?,?)",
                               (project, channel, parent_id, actor["name"], body, now()))
            names = {m for m in MENTION.findall(body)
                     if conn.execute("SELECT 1 FROM participants WHERE name=?", (m,)).fetchone()}
            for m in names:
                conn.execute("INSERT OR IGNORE INTO mentions VALUES(?,?)", (cur.lastrowid, m))
            self._index(conn, f"message:{cur.lastrowid}", project, "message", f"#{channel} {actor['name']}", body)
            self._event(conn, actor["name"], "message.create", f"message:{cur.lastrowid}", body, project)
            return {"id": cur.lastrowid, "mentions": sorted(names)}

    def messages(self, project, channel, since_id=0, limit=100, before_id=None) -> list[dict]:
        with self.connect() as conn:
            sql = ("SELECT m.*, p.kind AS author_kind FROM messages m LEFT JOIN participants p ON p.name=m.author "
                   "WHERE m.project=? AND m.channel=? AND m.id>?")
            args = [project, channel, int(since_id)]
            if before_id:
                sql += " AND m.id<?"
                args.append(int(before_id))
            out = rows(conn.execute(sql + " ORDER BY m.id DESC LIMIT ?", args + [min(int(limit), 500)]))
            return list(reversed(out))
