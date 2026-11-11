"""Designs: architecture boards of boxes, groups, text and arrows that a project works on together.

A design is stored as data (nodes and edges), not as a drawing, so an agent reads and writes it as JSON. Every
save is a revision. People save revisions; an agent starts a board or proposes a change, and a person accepts or
rejects the proposal. Nodes sent without a position are laid out here, from the connections alone."""

from __future__ import annotations

import json
import math
import re

from .core import Conflict, Forbidden, HubError, NotFound, choice, now, rank, rows, slug, text

KINDS = ("box", "group", "text")
COLORS = ("neutral", "blue", "green", "amber", "red", "violet")
NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
MAX_NODES, MAX_EDGES, MAX_DEPTH = 500, 2000, 8
GAP_X, GAP_Y, PAD, TITLE = 48, 64, 20, 44


def _number(value, what, low, high) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise HubError(f"{what} must be a number from {low} to {high}")
    return round(value)


def normalise_design(graph) -> dict:
    """Check a design sent by a client and return the stored form: known fields only, every node placed."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise HubError("a design is an object with nodes and edges")
    if len(graph["nodes"]) > MAX_NODES or len(graph["edges"]) > MAX_EDGES:
        raise HubError(f"a design holds at most {MAX_NODES} nodes and {MAX_EDGES} edges")
    nodes, by_id = [], {}
    for n in graph["nodes"]:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not NODE_ID.fullmatch(n["id"]) or n["id"] in by_id:
            raise HubError("every node needs a unique id of 1 to 80 letters, digits, _ . -")
        node = {"id": n["id"], "kind": choice(n.get("kind", "box"), KINDS, "node kind"),
                "label": text(n, "label", required=False, limit=400)}
        if n.get("detail"):
            node["detail"] = text(n, "detail", limit=4000)
        if n.get("color") not in (None, "", "neutral"):
            node["color"] = choice(n["color"], COLORS, "node color")
        if n.get("group"):
            node["group"] = n["group"]
        for pair, low, high in ((("x", "y"), -100000, 100000), (("w", "h"), 20, 4000)):
            given = [k for k in pair if n.get(k) is not None]
            if len(given) == 1:
                raise HubError(f"node {n['id']}: give both {pair[0]} and {pair[1]}, or neither")
            for k in given:
                node[k] = _number(n[k], f"node {k}", low, high)
        by_id[node["id"]] = node
        nodes.append(node)
    for node in nodes:
        seen, at = {node["id"]}, node
        while at.get("group"):
            parent = by_id.get(at["group"])
            if not parent or parent["kind"] != "group":
                raise HubError(f"node {at['id']}: group {at['group']!r} is not a group in this design")
            if parent["id"] in seen or len(seen) > MAX_DEPTH:
                raise HubError(f"node {node['id']}: groups nest at most {MAX_DEPTH} deep and never inside themselves")
            seen.add(parent["id"])
            at = parent
    edges, pairs = [], set()
    for e in graph["edges"]:
        if not isinstance(e, dict) or e.get("from") not in by_id or e.get("to") not in by_id or e["from"] == e["to"]:
            raise HubError("every edge runs between two different nodes of the design: {from, to}")
        if (e["from"], e["to"]) in pairs:
            raise HubError(f"there are two edges from {e['from']} to {e['to']}; keep one")
        pairs.add((e["from"], e["to"]))
        edge = {"from": e["from"], "to": e["to"]}
        if e.get("label"):
            edge["label"] = text(e, "label", limit=200)
        if e.get("dashed"):
            edge["dashed"] = True
        edges.append(edge)
    _place(nodes, by_id, edges)
    return {"nodes": nodes, "edges": edges}


# ------------------------------------------------------------------ layout
def _size(node) -> tuple[int, int]:
    if "w" in node:
        return node["w"], node["h"]
    lines = node["label"].split("\n")
    width = min(max(max(len(line) for line in lines) * 7.6 + 36, 150), 300)
    wrapped = sum(max(1, math.ceil(len(line) * 7.6 / (width - 28))) for line in lines)
    detail = min(3, math.ceil(len(node.get("detail", "")) * 6.4 / (width - 28)))
    return round(width), max(46, 22 + wrapped * 20 + detail * 16)


def _arrange(ids, pairs, size) -> tuple[dict, tuple[int, int]]:
    """Place ids in rows that follow the connections downwards: positions relative to the top-left, and the extent."""
    out = {i: [] for i in ids}
    for a, b in pairs:
        out[a].append(b)
    state, order, down = {}, [], {i: [] for i in ids}  # an edge that would close a loop is left out of `down`
    for root in ids:
        if root in state:
            continue
        state[root] = "open"
        stack = [(root, iter(out[root]))]
        while stack:
            node, rest = stack[-1]
            for nxt in rest:
                if nxt not in state:
                    state[nxt] = "open"
                    down[node].append(nxt)
                    stack.append((nxt, iter(out[nxt])))
                    break
                if state[nxt] == "done":
                    down[node].append(nxt)
            else:
                state[node] = "done"
                order.append(node)
                stack.pop()
    row_of, above = dict.fromkeys(ids, 0), {i: [] for i in ids}
    for node in reversed(order):
        for nxt in down[node]:
            row_of[nxt] = max(row_of[nxt], row_of[node] + 1)
            above[nxt].append(node)
    grid = [[i for i in ids if row_of[i] == r] for r in range(max(row_of.values(), default=-1) + 1)]
    index = {}
    for _ in range(2):  # order each row by where its inputs sit, so arrows cross less
        for row in grid:
            here = {i: k for k, i in enumerate(row)}
            row.sort(key=lambda i, here=here: sum(index[p] for p in above[i]) / len(above[i]) if above[i] else here[i])
            index.update({i: k for k, i in enumerate(row)})
    widths = [sum(size[i][0] for i in row) + GAP_X * (len(row) - 1) for row in grid]
    full, y, pos = max(widths, default=0), 0, {}
    for row, width in zip(grid, widths):
        x = (full - width) // 2
        for i in row:
            pos[i] = (x, y)
            x += size[i][0] + GAP_X
        y += max(size[i][1] for i in row) + GAP_Y
    return pos, (full, max(y - GAP_Y, 0))


def _layout(nodes, by_id, edges) -> None:
    """Place every node from the connections: each group is laid out inside, then treated as one box outside."""
    kids: dict = {}
    for n in nodes:
        kids.setdefault(n.get("group"), []).append(n["id"])
    size, rel = {}, {}

    def inside(node_id, holder, owner):
        owner[node_id] = holder
        for k in kids.get(node_id, []):
            inside(k, holder, owner)

    def measure(parent):
        owner = {}
        for k in kids.get(parent, []):
            if by_id[k]["kind"] == "group":
                measure(k)
            else:
                size[k] = _size(by_id[k])
            inside(k, k, owner)
        lifted = {(owner[e["from"]], owner[e["to"]]) for e in edges if e["from"] in owner and e["to"] in owner}
        pos, (w, h) = _arrange(kids.get(parent, []), sorted(p for p in lifted if p[0] != p[1]), size)
        rel.update(pos)
        size[parent] = (max(w, 200) + 2 * PAD, max(h, 60) + TITLE + PAD)

    def settle(parent, left, top):
        for k in kids.get(parent, []):
            n = by_id[k]
            n["x"], n["y"], (n["w"], n["h"]) = left + rel[k][0], top + rel[k][1], size[k]
            if n["kind"] == "group":
                settle(k, n["x"] + PAD, n["y"] + TITLE)

    measure(None)
    settle(None, 0, 0)


def _place(nodes, by_id, edges) -> None:
    """Fill in missing positions. A board with none is laid out whole. Otherwise what was drawn stays put: a new
    node goes below what it connects to, or to the right of the others in its group (which grows sideways, away
    from the rows underneath), and never on top of another node."""
    if not any("x" in n for n in nodes):
        return _layout(nodes, by_id, edges)
    placed = [n for n in nodes if "x" in n]
    bottom = max(n["y"] + n.get("h", 0) for n in placed)
    left = min(n["x"] for n in placed)
    depth = {}
    for n in nodes:
        at, d = n, 0
        while at.get("group"):
            at, d = by_id[at["group"]], d + 1
        depth[n["id"]] = d
    for n in nodes:
        if n["kind"] != "group" and "w" not in n:
            n["w"], n["h"] = _size(n)
    for n in nodes:
        if n["kind"] == "group" or "x" in n:
            continue
        near = [by_id[e["from"]] for e in edges if e["to"] == n["id"]] + [by_id[e["to"]] for e in edges if e["from"] == n["id"]]
        near = [m for m in near if "x" in m and m["kind"] != "group" and m.get("group") == n.get("group")]
        home = by_id.get(n.get("group"))
        if home:
            beside = [m for m in nodes if m.get("group") == home["id"] and "x" in m and "w" in m]
            if beside:
                n["x"], n["y"] = max(m["x"] + m["w"] for m in beside) + GAP_X, (near or beside)[0]["y"]
            elif "x" in home:
                n["x"], n["y"] = home["x"] + PAD, home["y"] + TITLE
            else:
                n["x"], n["y"] = left, bottom + GAP_Y + TITLE
        elif near:
            n["x"], n["y"] = near[0]["x"], near[0]["y"] + near[0]["h"] + GAP_Y
        else:
            n["x"], n["y"] = left, bottom + GAP_Y
        others = [m for m in nodes if m is not n and m["kind"] != "group" and "x" in m]
        while any(n["x"] < m["x"] + m["w"] + 8 and m["x"] < n["x"] + n["w"] + 8 and n["y"] < m["y"] + m["h"] + 8
                  and m["y"] < n["y"] + n["h"] + 8 for m in others):
            n["x"] += n["w"] + GAP_X
        bottom = max(bottom, n["y"] + n["h"])
    for g in sorted((n for n in nodes if n["kind"] == "group"), key=lambda n: -depth[n["id"]]):
        members = [m for m in nodes if m.get("group") == g["id"] and "x" in m and "w" in m]
        if "x" in g and "w" in g:  # an existing group grows to hold what was added to it
            right = max([g["x"] + g["w"]] + [m["x"] + m["w"] + PAD for m in members])
            low = max([g["y"] + g["h"]] + [m["y"] + m["h"] + PAD for m in members])
            g["w"], g["h"] = min(right - g["x"], 4000), min(low - g["y"], 4000)
        elif members:
            g["x"], g["y"] = min(m["x"] for m in members) - PAD, min(m["y"] for m in members) - TITLE
            g["w"] = min(max(m["x"] + m["w"] for m in members) + PAD - g["x"], 4000)
            g["h"] = min(max(m["y"] + m["h"] for m in members) + PAD - g["y"], 4000)
        else:
            g.setdefault("x", left)
            g.setdefault("y", bottom + GAP_Y)
            g.setdefault("w", 280)
            g.setdefault("h", 160)
            bottom = g["y"] + g["h"]


def _dump(graph) -> str:
    return json.dumps(graph, separators=(",", ":"), sort_keys=True)


def _words(graph) -> str:
    """The text of a design, for the search index."""
    return "\n".join(filter(None, [n.get("label", "") + " " + n.get("detail", "") for n in graph["nodes"]]
                            + [e.get("label", "") for e in graph["edges"]]))


class Designs:
    @staticmethod
    def _require_design_editor(actor):
        if not actor or actor.get("kind") != "human" or rank(actor.get("role")) < rank("member"):
            raise Forbidden("only a person who is a project member saves a design; agents propose changes "
                            "(`hub design propose`) and a person accepts them")

    def _design(self, conn, design_slug) -> dict:
        row = conn.execute("SELECT * FROM designs WHERE slug=?", (design_slug,)).fetchone()
        if not row:
            raise NotFound(f"design {design_slug!r} does not exist")
        return dict(row)

    @staticmethod
    def layout_design(graph) -> dict:
        """The same design with every position recomputed from its connections."""
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            raise HubError("a design is an object with nodes and edges")
        bare = [{k: v for k, v in n.items() if k not in ("x", "y") and (k not in ("w", "h") or n.get("kind") != "group")}
                if isinstance(n, dict) else n for n in graph["nodes"]]
        return normalise_design({**graph, "nodes": bare})

    def create_design(self, actor, project, data: dict) -> dict:
        """A new board, owned by whoever creates it. Agents may start one; it changes nobody else's board."""
        self._require_member(actor)
        design_slug = slug(data.get("slug"), "design slug")
        title = text(data, "title", limit=200)
        description = text(data, "description", required=False, limit=4000)
        note = text(data, "note", required=False, limit=300) or "First revision"
        graph = normalise_design(data.get("graph") or {"nodes": [], "edges": []})
        ts = now()
        with self.connect(write=True) as conn:
            self._project(conn, project)
            if conn.execute("SELECT 1 FROM designs WHERE slug=?", (design_slug,)).fetchone():
                raise Conflict(f"a design named {design_slug!r} already exists; choose another name")
            conn.execute("INSERT INTO designs VALUES(?,?,?,?,?,?,?,?)",
                         (design_slug, project, title, description, actor["name"], 1, ts, ts))
            conn.execute("INSERT INTO design_revisions VALUES(?,?,?,?,?,?,?)",
                         (design_slug, 1, _dump(graph), actor["name"], note, len(graph["nodes"]), ts))
            self._index(conn, f"design:{design_slug}", project, "design", title, f"{description}\n{_words(graph)}")
            self._event(conn, actor["name"], "design.create", f"design:{design_slug}", title, project)
        return {"slug": design_slug, "rev": 1, "nodes": len(graph["nodes"])}

    def designs(self, project) -> list[dict]:
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT d.slug, d.title, d.description, d.owner, d.rev, d.created, d.updated, r.author, r.note, r.n_nodes, "
                "(SELECT COUNT(*) FROM design_proposals p WHERE p.design=d.slug AND p.status='open') AS open_proposals, "
                "(SELECT COUNT(*) FROM comments c WHERE c.target='design:'||d.slug AND c.status='open' "
                " AND c.parent_id IS NULL) AS open_comments "
                "FROM designs d JOIN design_revisions r ON r.design=d.slug AND r.rev=d.rev WHERE d.project=? "
                "ORDER BY d.updated DESC", (project,)))

    def design(self, design_slug, rev=None) -> dict:
        """One design at a revision (default: the latest), with its history, proposals, comments and linked runs."""
        with self.connect() as conn:
            d = self._design(conn, design_slug)
            at = conn.execute("SELECT * FROM design_revisions WHERE design=? AND rev=?",
                              (design_slug, int(rev) if rev else d["rev"])).fetchone()
            if not at:
                raise NotFound(f"design {design_slug} has no revision {rev}")
            ref = f"design:{design_slug}"
            return {
                **d, "head": d["rev"], "rev": at["rev"], "author": at["author"], "note": at["note"],
                "saved": at["created"], "graph": json.loads(at["payload"]),
                "history": rows(conn.execute("SELECT rev, author, note, n_nodes, created FROM design_revisions "
                                             "WHERE design=? ORDER BY rev DESC LIMIT 100", (design_slug,))),
                "proposals": rows(conn.execute(
                    "SELECT id, base_rev, author, note, status, created, decided_by FROM design_proposals "
                    "WHERE design=? ORDER BY id DESC LIMIT 50", (design_slug,))),
                "comments": self._comments_for(conn, [ref]),
                "runs": rows(conn.execute(
                    "SELECT r.slug, r.title, r.owner, r.status, l.dst FROM links l JOIN runs r ON 'run:'||r.slug=l.src "
                    "WHERE l.dst=? OR substr(l.dst, 1, ?)=? ORDER BY r.created DESC",
                    (ref, len(ref) + 1, ref + "@"))),
            }

    def save_design(self, actor, design_slug, data: dict) -> dict:
        """A person saves a new revision, or accepts a proposal as one. Title and description can change too."""
        self._require_design_editor(actor)
        graph = normalise_design(data["graph"]) if data.get("graph") is not None else None
        note = text(data, "note", required=graph is not None, limit=300)
        ts = now()
        with self.connect(write=True) as conn:
            d = self._design(conn, design_slug)
            title = text(data, "title", limit=200) if data.get("title") is not None else d["title"]
            description = (text(data, "description", required=False, limit=4000) if data.get("description") is not None
                           else d["description"])
            rev = d["rev"]
            if graph is not None:
                if data.get("expected_rev") is not None and int(data["expected_rev"]) != rev:
                    raise Conflict(f"design {design_slug} is at rev {rev}, you edited rev {data['expected_rev']}; "
                                   "reload and re-apply your change")
                if data.get("proposal_id") is not None:
                    prop = conn.execute("SELECT base_rev, payload FROM design_proposals WHERE id=? AND design=? AND "
                                        "status='open'", (int(data["proposal_id"]), design_slug)).fetchone()
                    if not prop:
                        raise NotFound(f"design {design_slug} has no open proposal {data['proposal_id']}")
                    if prop["base_rev"] != rev and prop["payload"] == _dump(graph):
                        raise Conflict(f"proposal {data['proposal_id']} was drawn against rev {prop['base_rev']}, and the "
                                       f"design is now at rev {rev}; accepting it as is would undo the changes since. "
                                       "Merge it into the current board, or ask the author to propose again")
                    conn.execute("UPDATE design_proposals SET status='accepted', decided_by=?, decided=? WHERE id=?",
                                 (actor["name"], ts, int(data["proposal_id"])))
                rev += 1
                conn.execute("INSERT INTO design_revisions VALUES(?,?,?,?,?,?,?)",
                             (design_slug, rev, _dump(graph), actor["name"], note, len(graph["nodes"]), ts))
                self._event(conn, actor["name"], "design.update", f"design:{design_slug}", f"rev {rev}: {note}", d["project"])
            else:
                graph = json.loads(conn.execute("SELECT payload FROM design_revisions WHERE design=? AND rev=?",
                                                (design_slug, rev)).fetchone()[0])
            conn.execute("UPDATE designs SET title=?, description=?, rev=?, updated=? WHERE slug=?",
                         (title, description, rev, ts, design_slug))
            self._index(conn, f"design:{design_slug}", d["project"], "design", title, f"{description}\n{_words(graph)}")
        return {"slug": design_slug, "rev": rev}

    def propose_design(self, actor, design_slug, graph, note) -> dict:
        self._require_member(actor)
        payload = _dump(normalise_design(graph))
        note = text({"n": note}, "n", limit=300)
        with self.connect(write=True) as conn:
            d = self._design(conn, design_slug)
            if payload == conn.execute("SELECT payload FROM design_revisions WHERE design=? AND rev=?",
                                       (design_slug, d["rev"])).fetchone()[0]:
                raise HubError(f"this is the same as rev {d['rev']} of {design_slug}; nothing to propose")
            cur = conn.execute("INSERT INTO design_proposals(design,project,base_rev,payload,author,note,status,created) "
                               "VALUES(?,?,?,?,?,?,'open',?)",
                               (design_slug, d["project"], d["rev"], payload, actor["name"], note, now()))
            self._event(conn, actor["name"], "design.propose", f"design:{design_slug}",
                        f"proposal {cur.lastrowid}: {note}", d["project"])
            return {"id": cur.lastrowid, "design": design_slug, "base_rev": d["rev"]}

    def design_proposal(self, pid) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM design_proposals WHERE id=?", (int(pid),)).fetchone()
            if not row:
                raise NotFound(f"design proposal {pid} does not exist")
            out = dict(row)
            out["graph"] = json.loads(out.pop("payload"))
            return out

    def reject_design_proposal(self, actor, pid) -> dict:
        self._require_design_editor(actor)
        with self.connect(write=True) as conn:
            cur = conn.execute("UPDATE design_proposals SET status='rejected', decided_by=?, decided=? WHERE id=? AND "
                               "status='open'", (actor["name"], now(), int(pid)))
            if not cur.rowcount:
                raise NotFound(f"no open design proposal {pid}")
        return {"id": int(pid), "status": "rejected"}

    def _purge_design(self, conn, design_slug) -> None:
        ref = f"design:{design_slug}"
        conn.execute("DELETE FROM comments WHERE target=?", (ref,))
        conn.execute("DELETE FROM links WHERE dst=? OR substr(dst, 1, ?)=?", (ref, len(ref) + 1, ref + "@"))
        conn.execute("DELETE FROM search WHERE ref=?", (ref,))
        for table in ("design_revisions", "design_proposals"):
            conn.execute(f"DELETE FROM {table} WHERE design=?", (design_slug,))
        conn.execute("DELETE FROM designs WHERE slug=?", (design_slug,))

    def delete_design(self, actor, design_slug, confirm) -> dict:
        """Delete a design with its revisions, proposals and comments. Its owner or a maintainer; people only."""
        with self.connect(write=True) as conn:
            d = self._design(conn, design_slug)
            if actor.get("kind") != "human" or not (actor["name"] == d["owner"] or self._moderator(actor)):
                raise Forbidden("only the person who owns a design, or a project maintainer, can delete it")
            if confirm != design_slug:
                raise HubError(f"deleting a design cannot be undone; confirm by sending confirm={design_slug}")
            self._purge_design(conn, design_slug)
            self._audit(conn, actor, "design.delete", design_slug, f"{d['rev']} revisions")
        return {"deleted": design_slug, "revisions": d["rev"]}
