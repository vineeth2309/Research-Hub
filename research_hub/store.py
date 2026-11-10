"""The store: one object with every operation, plus rebuilding the search index."""

from __future__ import annotations

from .accounts import Accounts
from .charts import Charts
from .core import Core
from .evals import Evals
from .graphs import Graphs
from .runs import Runs
from .social import Social


class Store(Core, Accounts, Runs, Charts, Graphs, Evals, Social):
    def reindex(self) -> int:
        """Rebuild the full-text index from the tables."""
        n = 0
        with self.connect(write=True) as conn:
            conn.execute("DELETE FROM search")
            for slug, in conn.execute("SELECT slug FROM runs").fetchall():
                self._index_run(conn, slug)
                n += 1
            for p in conn.execute("SELECT slug, project, title, body FROM posts").fetchall():
                self._index(conn, f"post:{p['slug']}", p["project"], "post", p["title"], p["body"])
                n += 1
            for c in conn.execute("SELECT id, target, kind, body FROM comments").fetchall():
                self._index(conn, f"comment:{c['id']}", self._project_of(conn, c["target"]), "comment",
                            f"{c['kind']} on {c['target']}", c["body"])
                n += 1
            for m in conn.execute("SELECT id, project, channel, author, body FROM messages").fetchall():
                self._index(conn, f"message:{m['id']}", m["project"], "message", f"#{m['channel']} {m['author']}", m["body"])
                n += 1
            for table, kind in (("topics", "topic"), ("categories", "category")):
                for t in conn.execute(f"SELECT project, slug, title, description FROM {table}").fetchall():
                    self._index(conn, f"{kind}:{t['slug']}", t["project"], kind, t["title"], t["description"])
                    n += 1
            for h in conn.execute("SELECT project, text FROM handbook h WHERE rev=(SELECT MAX(rev) FROM handbook "
                                  "WHERE project=h.project)").fetchall():
                self._index(conn, f"handbook:{h['project']}", h["project"], "handbook", "Handbook", h["text"])
                n += 1
        return n
