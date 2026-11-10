"""SQLite schema and the content-addressed blob store. One database file plus ``blobs/`` under the hub home."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(slug TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}', visibility TEXT NOT NULL DEFAULT 'private', created_by TEXT NOT NULL,
    created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS participants(name TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('agent','human')),
    display TEXT NOT NULL DEFAULT '', email TEXT UNIQUE, password_hash TEXT NOT NULL DEFAULT '',
    admin INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active', owner TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '', focus TEXT NOT NULL DEFAULT '', created TEXT NOT NULL,
    last_seen TEXT NOT NULL DEFAULT '', inbox_seen_at TEXT NOT NULL DEFAULT '', handbook_seen TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS memberships(project TEXT NOT NULL, participant TEXT NOT NULL, role TEXT NOT NULL,
    added_by TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project, participant)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS memberships_participant ON memberships(participant);
CREATE TABLE IF NOT EXISTS api_keys(id INTEGER PRIMARY KEY, participant TEXT NOT NULL, label TEXT NOT NULL,
    prefix TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL, created TEXT NOT NULL,
    last_used TEXT NOT NULL DEFAULT '', expires TEXT NOT NULL DEFAULT '', revoked TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sessions(id_hash TEXT PRIMARY KEY, participant TEXT NOT NULL, csrf TEXT NOT NULL,
    created TEXT NOT NULL, last_seen TEXT NOT NULL, expires TEXT NOT NULL, client TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS invites(id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, email TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'member', created_by TEXT NOT NULL,
    created TEXT NOT NULL, expires TEXT NOT NULL, used_by TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS password_resets(token_hash TEXT PRIMARY KEY, participant TEXT NOT NULL,
    created_by TEXT NOT NULL, expires TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS categories(project TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project, slug));
CREATE TABLE IF NOT EXISTS topics(project TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project, slug));
CREATE TABLE IF NOT EXISTS channels(project TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project, slug));
CREATE TABLE IF NOT EXISTS runs(slug TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL, owner TEXT NOT NULL,
    category TEXT NOT NULL, app TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
    summary TEXT NOT NULL, hypothesis TEXT NOT NULL, rationale TEXT NOT NULL, expected TEXT NOT NULL,
    conclusion TEXT NOT NULL DEFAULT '', verdict TEXT,
    repo TEXT NOT NULL DEFAULT '', branch TEXT NOT NULL DEFAULT '', commit_sha TEXT NOT NULL DEFAULT '',
    config_path TEXT NOT NULL DEFAULT '', config_sha TEXT NOT NULL DEFAULT '', command TEXT NOT NULL DEFAULT '',
    parent TEXT, dataset TEXT NOT NULL DEFAULT '', output_dataset TEXT NOT NULL DEFAULT '',
    pinned TEXT NOT NULL DEFAULT '[]', ingest_token_hash TEXT NOT NULL,
    created TEXT NOT NULL, started TEXT NOT NULL DEFAULT '', ended TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project, status, updated);
CREATE TABLE IF NOT EXISTS run_topics(run TEXT NOT NULL, topic TEXT NOT NULL, PRIMARY KEY(run, topic));
CREATE TABLE IF NOT EXISTS run_notes(id INTEGER PRIMARY KEY, run TEXT NOT NULL, author TEXT NOT NULL,
    body TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metrics(run TEXT NOT NULL, key TEXT NOT NULL, step INTEGER NOT NULL, value REAL NOT NULL,
    ts TEXT NOT NULL, PRIMARY KEY(run, key, step)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS run_summary(run TEXT NOT NULL, key TEXT NOT NULL, value REAL NOT NULL,
    direction TEXT NOT NULL, PRIMARY KEY(run, key)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS artifacts(id INTEGER PRIMARY KEY, run TEXT NOT NULL, step INTEGER, epoch INTEGER,
    sample TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, name TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '', blob_sha TEXT NOT NULL, mime TEXT NOT NULL, author TEXT NOT NULL,
    created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run, step);
CREATE TABLE IF NOT EXISTS charts(run TEXT NOT NULL, name TEXT NOT NULL, step INTEGER NOT NULL, kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '', blob_sha TEXT NOT NULL, n_rows INTEGER NOT NULL, created TEXT NOT NULL,
    PRIMARY KEY(run, name, step)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS model_graphs(run TEXT NOT NULL, name TEXT NOT NULL, blob_sha TEXT NOT NULL,
    n_nodes INTEGER NOT NULL, params INTEGER NOT NULL, created TEXT NOT NULL, PRIMARY KEY(run, name)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS posts(slug TEXT PRIMARY KEY, project TEXT NOT NULL, topic TEXT NOT NULL, owner TEXT NOT NULL,
    kind TEXT NOT NULL, basis TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, revision INTEGER NOT NULL,
    created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_revisions(slug TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
    author TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(slug, revision));
CREATE TABLE IF NOT EXISTS citations(post TEXT NOT NULL, idx INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
    venue TEXT NOT NULL DEFAULT '', PRIMARY KEY(post, idx));
CREATE TABLE IF NOT EXISTS links(src TEXT NOT NULL, dst TEXT NOT NULL, relation TEXT NOT NULL,
    created_by TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(src, dst, relation));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, project TEXT NOT NULL, channel TEXT NOT NULL,
    parent_id INTEGER, author TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_channel ON messages(project, channel, id);
CREATE TABLE IF NOT EXISTS mentions(message_id INTEGER NOT NULL, participant TEXT NOT NULL,
    PRIMARY KEY(message_id, participant));
CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, target TEXT NOT NULL, author TEXT NOT NULL,
    kind TEXT NOT NULL, anchor TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, status TEXT NOT NULL,
    resolution_ref TEXT NOT NULL DEFAULT '', parent_id INTEGER, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS comments_target ON comments(target, status);
CREATE TABLE IF NOT EXISTS claims(resource TEXT PRIMARY KEY, project TEXT NOT NULL, owner TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handbook(project TEXT NOT NULL, rev INTEGER NOT NULL, text TEXT NOT NULL,
    author TEXT NOT NULL, note TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project, rev));
CREATE TABLE IF NOT EXISTS handbook_proposals(id INTEGER PRIMARY KEY, project TEXT NOT NULL, base_rev INTEGER NOT NULL,
    text TEXT NOT NULL, author TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
    decided_by TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, project TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, summary TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(ref UNINDEXED, project UNINDEXED, kind UNINDEXED, title, body);
CREATE TABLE IF NOT EXISTS eval_sets(id INTEGER PRIMARY KEY, project TEXT NOT NULL, name TEXT NOT NULL,
    created TEXT NOT NULL, UNIQUE(project, name));
CREATE TABLE IF NOT EXISTS eval_items(id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL, sample TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}', UNIQUE(set_id, sample));
CREATE TABLE IF NOT EXISTS eval_facts(item INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY(item, key)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS eval_facts_value ON eval_facts(key, value, item);
CREATE TABLE IF NOT EXISTS eval_results(run TEXT NOT NULL, set_id INTEGER NOT NULL, step INTEGER NOT NULL,
    item INTEGER NOT NULL, epoch INTEGER, truth TEXT NOT NULL DEFAULT '{}', pred TEXT NOT NULL DEFAULT '{}',
    class_true TEXT NOT NULL DEFAULT '', class_pred TEXT NOT NULL DEFAULT '', value_true REAL, value_pred REAL,
    score REAL, error REAL, outcome TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(run, set_id, step, item)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS eval_results_rank ON eval_results(run, set_id, step, outcome, error);
CREATE INDEX IF NOT EXISTS eval_results_item ON eval_results(run, item, step);
CREATE INDEX IF NOT EXISTS eval_results_class ON eval_results(run, set_id, step, class_true, class_pred);
CREATE TABLE IF NOT EXISTS eval_layers(run TEXT NOT NULL, set_id INTEGER NOT NULL, step INTEGER NOT NULL,
    item INTEGER NOT NULL, layer TEXT NOT NULL, blob_sha TEXT NOT NULL, kind TEXT NOT NULL,
    PRIMARY KEY(run, set_id, item, step, layer)) WITHOUT ROWID;
"""

# Schema changes after a release go here as (version, sql), oldest first; a new database starts at the latest.
MIGRATIONS: list[tuple[int, str]] = []
SCHEMA_VERSION = 1

MAX_BLOB = 25 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}")


class Database:
    def __init__(self, home: str | Path):
        self.home = Path(home).expanduser().resolve()
        self.blobs = self.home / "blobs"
        for folder in (self.home, self.blobs):  # a new home is private to the hub's user
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.home / "hub.sqlite3"
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            fresh = not conn.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone()
            conn.executescript(f"BEGIN;{SCHEMA}COMMIT;")  # one transaction: one disk sync, not one per table
            if fresh:
                conn.execute("INSERT INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            self._migrate(conn)
        self.path.chmod(0o600)

    @staticmethod
    def _migrate(conn):
        current = int(conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"database is at schema {current}, newer than this release ({SCHEMA_VERSION}); upgrade the hub")
        for version, sql in MIGRATIONS:
            if version > current:
                conn.executescript(sql)
                conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(version),))

    @contextmanager
    def connect(self, write: bool = False):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def put_blob(self, data: bytes) -> str:
        if len(data) > MAX_BLOB:
            raise ValueError(f"file is larger than {MAX_BLOB // (1024 * 1024)} MB")
        sha = hashlib.sha256(data).hexdigest()
        path = self.blobs / sha[:2] / sha
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return sha

    def has_blob(self, sha: str) -> bool:
        return bool(SHA.fullmatch(str(sha))) and (self.blobs / sha[:2] / sha).exists()

    def blob_path(self, sha: str) -> Path | None:
        return (self.blobs / sha[:2] / sha) if self.has_blob(sha) else None


def sniff_mime(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head.startswith(b"ID3") or head[:2] == b"\xff\xfb":
        return "audio/mpeg"
    return None
