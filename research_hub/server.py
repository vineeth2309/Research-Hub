"""HTTP API and dashboard. Standard library only; the server is the single writer to the database.

Access is decided here, in one place. Every route names a *scope* (how to find the project the call is about) and
the minimum project role it needs; a route without a matching rule cannot be reached. Browsers authenticate with
a session cookie plus a CSRF header, scripts and agents with an API key, training jobs with a run's ingest token.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .accounts import SESSION_DAYS
from .core import Forbidden, HubError, NotFound, Unauthorized, now, rank
from .db import sniff_mime
from .store import Store

UI_DIR = Path(__file__).resolve().parent / "ui"
DEFAULT_HANDBOOK = Path(__file__).resolve().parent / "defaults" / "HANDBOOK.md"
MAX_BODY = 40 * 1024 * 1024
COOKIE = "hub_session"
STATIC = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2",
          ".png": "image/png", ".ico": "image/x-icon"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
                               "style-src 'self' 'unsafe-inline'; font-src 'self'; object-src 'none'; "
                               "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


class TooManyRequests(HubError):
    status = 429


class Limiter:
    """Sliding-window counter per key, in memory: slows password guessing and sign-up floods."""

    def __init__(self, limit: int, seconds: int):
        self.limit, self.seconds = limit, seconds
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        with self.lock:
            q, cutoff = self.hits[key], time.monotonic() - self.seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                raise TooManyRequests(f"too many attempts; try again in {int(q[0] - cutoff) + 1} seconds")

    def hit(self, key: str) -> None:
        with self.lock:
            self.hits[key].append(time.monotonic())


def _qs(query: str) -> dict:
    return {k: v[-1] for k, v in urllib.parse.parse_qs(query).items()}


def _csv(value) -> list[str]:
    return [x for x in str(value or "").split(",") if x]


class Call:
    """One request's context. ``project`` resolves lazily so project-free routes never require one."""

    def __init__(self, api, actor, m, q, body, headers, ip, session):
        self.api, self.actor, self.m, self.q, self.body, self.headers = api, actor, m, q, body, headers
        self.ip, self.session = ip, session
        self.cookies: list[str] = []  # Set-Cookie values for the response

    @property
    def project(self) -> str:
        wanted = self.q.get("project") or self.body.get("project") or self.headers.get("X-Hub-Project")
        if not wanted:
            mine = self.api.store.projects(self.actor)
            if len(mine) != 1:
                raise HubError("project is required: pass ?project=<slug>, X-Hub-Project, or set HUB_PROJECT")
            wanted = mine[0]["slug"]
        return wanted


class Api:
    """Routes requests to the store. Separate from the HTTP handler so tests can call it directly."""

    def __init__(self, store: Store, secure_cookies: bool = False):
        self.store = store
        self.secure_cookies = secure_cookies
        self.setup_code = secrets.token_urlsafe(18) if store.needs_setup() else None
        self.login_limit = Limiter(8, 15 * 60)
        self.signup_limit = Limiter(10, 60 * 60)
        s = store
        R = self._route
        self.routes = [
            # ---- no sign-in needed
            R("GET", "/api/health", lambda c: {"ok": True, "time": now(), "version": __version__}, "public"),
            R("GET", "/api/auth/state", self._state, "public"),
            R("POST", "/api/auth/setup", self._setup, "public"),
            R("POST", "/api/auth/login", self._login, "public"),
            R("POST", "/api/auth/signup", self._signup, "public"),
            R("GET", "/api/auth/invite", lambda c: s.invite_info(c.q.get("token")), "public"),
            R("POST", "/api/auth/reset", self._use_reset, "public"),
            # ---- any signed-in account
            R("GET", "/api/whoami", lambda c: c.actor, "any"),
            R("POST", "/api/auth/logout", self._logout, "user"),
            R("GET", "/api/projects", lambda c: s.projects(c.actor), "user"),
            R("GET", "/api/inbox", lambda c: s.inbox(c.actor, c.q.get("project")), "user"),
            R("POST", "/api/inbox/ack", lambda c: s.ack_inbox(c.actor) or {"ok": True}, "user"),
            R("POST", "/api/blobs", lambda c: {"shas": s.put_blobs(c.body.get("files"))}, "any"),
            R("POST", "/api/blobs/missing", lambda c: {"missing": s.missing_blobs(c.body.get("shas"))}, "any"),
            # ---- a signed-in person: their own account, keys and agents
            R("POST", "/api/projects", lambda c: s.create_project(
                c.actor, c.body.get("slug"), c.body.get("title"), c.body.get("description", ""), c.body.get("settings"),
                c.body.get("visibility", "private"), c.body.get("handbook") or DEFAULT_HANDBOOK.read_text()), "person"),
            R("PATCH", "/api/account", lambda c: s.update_profile(c.actor, c.body), "person"),
            R("GET", "/api/account/sessions", lambda c: s.sessions(c.actor), "person"),
            R("DELETE", "/api/account/sessions/([0-9a-f]+)", lambda c: s.revoke_session(c.actor, c.m[0]) or {"ok": True},
              "person"),
            R("GET", "/api/agents", lambda c: s.my_agents(c.actor), "person"),
            R("POST", "/api/agents", lambda c: s.create_agent(
                c.actor, c.body.get("name"), c.body.get("model", ""), c.body.get("focus", ""),
                c.body.get("projects") or []), "person"),
            R("PATCH", "/api/agents/([a-z0-9_-]+)", lambda c: s.update_agent(c.actor, c.m[0], c.body), "person"),
            R("GET", "/api/keys", lambda c: s.keys(c.actor, c.q.get("participant") or c.actor["name"]), "person"),
            R("POST", "/api/keys", lambda c: s.create_key(
                c.actor, c.body.get("participant") or c.actor["name"], c.body.get("label"), c.body.get("days")), "person"),
            R("DELETE", "/api/keys/(\\d+)", lambda c: s.revoke_key(c.actor, c.m[0]), "person"),
            R("POST", "/api/invites", lambda c: s.create_invite(
                c.actor, c.body.get("email", ""), c.body.get("project", ""), c.body.get("role", "member"),
                c.body.get("days", 7)), "person"),
            # ---- site admins
            R("GET", "/api/admin/users", lambda c: s.users(), "admin"),
            R("PATCH", "/api/admin/users/([a-z0-9_-]+)", lambda c: s.update_user(c.actor, c.m[0], c.body), "admin"),
            R("POST", "/api/admin/users/([a-z0-9_-]+)/reset", lambda c: s.create_reset(c.actor, c.m[0]), "admin"),
            R("GET", "/api/admin/settings", lambda c: s.site_settings(), "admin"),
            R("PATCH", "/api/admin/settings", lambda c: s.set_site_settings(c.actor, c.body), "admin"),
            R("GET", "/api/admin/invites", lambda c: s.invites(c.actor), "admin"),
            R("DELETE", "/api/admin/invites/(\\d+)", lambda c: s.revoke_invite(c.actor, c.m[0]) or {"ok": True}, "admin"),
            R("GET", "/api/admin/audit", lambda c: s.audit_log(c.q.get("limit", 100), c.q.get("offset", 0)), "admin"),
            # ---- one project
            R("GET", "/api/projects/([^/]+)", lambda c: {**s.get_project(c.m[0]), "role": c.actor["role"]},
              "project:m", "viewer"),
            R("PATCH", "/api/projects/([^/]+)", lambda c: s.update_project(c.actor, c.m[0], c.body),
              "project:m", "maintainer"),
            R("DELETE", "/api/projects/([^/]+)", lambda c: s.delete_project(c.actor, c.m[0], c.q.get("confirm")),
              "project:m", "owner"),
            R("GET", "/api/members", lambda c: s.members(c.project), "project", "viewer"),
            R("PUT", "/api/members/([a-z0-9_-]+)", lambda c: s.set_member(
                c.actor, c.project, c.m[0], c.body.get("role")), "project", "maintainer"),
            R("DELETE", "/api/members/([a-z0-9_-]+)", lambda c: s.remove_member(c.actor, c.project, c.m[0]) or {"ok": True},
              "project", "viewer"),
            R("GET", "/api/invites", lambda c: s.invites(c.actor, c.project), "project", "maintainer"),
            R("DELETE", "/api/invites/(\\d+)", lambda c: s.revoke_invite(c.actor, c.m[0], c.project) or {"ok": True},
              "project", "maintainer"),
            R("GET", "/api/categories", lambda c: s.categories(c.project), "project", "viewer"),
            R("POST", "/api/categories", lambda c: s.add_category(
                c.actor, c.project, c.body.get("slug"), c.body.get("title"), c.body.get("description", "")),
              "project", "maintainer"),
            R("GET", "/api/topics", lambda c: s.topics(c.project), "project", "viewer"),
            R("POST", "/api/topics", lambda c: s.add_topic(
                c.actor, c.project, c.body.get("slug"), c.body.get("title"), c.body.get("description", "")),
              "project", "member"),
            R("GET", "/api/runs", lambda c: s.list_runs(
                c.project, c.q, int(c.q.get("limit", 50)), int(c.q.get("offset", 0))), "project", "viewer"),
            R("GET", "/api/runs/table", lambda c: s.run_table(
                c.project, c.q, _csv(c.q.get("columns")), c.q.get("sort"), c.q.get("desc", "1") != "0",
                int(c.q.get("limit", 50)), int(c.q.get("offset", 0))), "project", "viewer"),
            R("POST", "/api/runs", lambda c: s.create_run(c.actor, c.project, c.body), "project", "member"),
            R("GET", "/api/posts", lambda c: s.list_posts(
                c.project, c.q.get("topic"), c.q.get("owner"), c.q.get("kind"), int(c.q.get("limit", 50)),
                int(c.q.get("offset", 0))), "project", "viewer"),
            R("PUT", "/api/posts", lambda c: s.put_post(
                c.actor, c.project, c.body.get("post") or {}, int(c.body.get("expected_revision", 0))),
              "project", "member"),
            R("GET", "/api/comments", lambda c: s.list_comments(
                c.project, c.q.get("status"), c.q.get("from"), c.q.get("to"), int(c.q.get("limit", 50)),
                int(c.q.get("offset", 0))), "project", "viewer"),
            R("GET", "/api/channels", lambda c: s.channels(c.project), "project", "viewer"),
            R("POST", "/api/channels", lambda c: s.add_channel(
                c.actor, c.project, c.body.get("slug"), c.body.get("title", "")), "project", "member"),
            R("GET", "/api/channels/([^/]+)/messages", lambda c: s.messages(
                c.project, c.m[0], int(c.q.get("since", 0)), int(c.q.get("limit", 100)), c.q.get("before")),
              "project", "viewer"),
            R("POST", "/api/channels/([^/]+)/messages", lambda c: s.post_message(
                c.actor, c.project, c.m[0], c.body.get("body"), c.body.get("parent_id")), "project", "member"),
            R("GET", "/api/handbook", lambda c: s.handbook(c.project, c.actor, c.q.get("rev")), "project", "viewer"),
            R("PUT", "/api/handbook", lambda c: s.set_handbook(
                c.actor, c.project, c.body.get("text"), c.body.get("note"), c.body.get("expected_rev"),
                c.body.get("proposal_id")), "project", "maintainer"),
            R("POST", "/api/handbook/proposals", lambda c: s.propose_handbook(
                c.actor, c.project, c.body.get("text"), c.body.get("note")), "project", "member"),
            R("GET", "/api/designs", lambda c: s.designs(c.project), "project", "viewer"),
            R("POST", "/api/designs", lambda c: s.create_design(c.actor, c.project, c.body), "project", "member"),
            R("POST", "/api/designs/layout", lambda c: s.layout_design(c.body.get("graph")), "user"),
            R("GET", "/api/claims", lambda c: s.claims(c.project), "project", "viewer"),
            R("POST", "/api/claims", lambda c: s.claim(
                c.actor, c.project, c.body.get("resource"), c.body.get("note", ""), c.body.get("hours", 24)),
              "project", "member"),
            R("GET", "/api/search", lambda c: s.search(c.project, c.q.get("q", "")), "project", "viewer"),
            R("GET", "/api/events", lambda c: s.events(c.project, int(c.q.get("since", 0)), int(c.q.get("limit", 100))),
              "project", "viewer"),
            # ---- things found by their own id; the project is looked up from them
            R("GET", "/api/runs/([^/]+)", lambda c: s.get_run(c.m[0]), "run", "viewer", ingest=True),
            R("PATCH", "/api/runs/([^/]+)", lambda c: s.update_run(c.actor, c.m[0], c.body), "run", "member", ingest=True),
            R("DELETE", "/api/runs/([^/]+)", lambda c: s.delete_run(c.actor, c.m[0], c.q.get("confirm")), "run", "member"),
            R("POST", "/api/runs/([^/]+)/ingest-token", lambda c: {
                "ingest_token": s.issue_ingest_token(c.actor, c.m[0])}, "run", "member"),
            R("GET", "/api/runs/([^/]+)/metrics", lambda c: s.metrics(c.m[0], _csv(c.q.get("keys")) or None),
              "run", "viewer"),
            R("POST", "/api/runs/([^/]+)/metrics", lambda c: {
                "logged": s.log_metrics(c.actor, c.m[0], c.body.get("points"))}, "run", "member", ingest=True),
            R("POST", "/api/runs/([^/]+)/summary", lambda c: s.set_summary(c.actor, c.m[0], c.body),
              "run", "member", ingest=True),
            R("POST", "/api/runs/([^/]+)/artifacts", lambda c: s.add_artifact(
                c.actor, c.m[0], c.body.get("name"), c.body.get("data"), c.body.get("kind", "image"), c.body.get("step"),
                c.body.get("caption", ""), c.body.get("mime"), c.body.get("epoch"), c.body.get("sample", ""),
                c.body.get("role", "")), "run", "member", ingest=True),
            R("POST", "/api/runs/([^/]+)/notes", lambda c: s.add_note(c.actor, c.m[0], c.body.get("body")),
              "run", "member", ingest=True),
            R("POST", "/api/runs/([^/]+)/charts", lambda c: s.log_chart(
                c.actor, c.m[0], c.body.get("name"), c.body.get("chart"), c.body.get("step")), "run", "member", ingest=True),
            R("GET", "/api/runs/([^/]+)/charts", lambda c: s.charts(c.m[0]), "run", "viewer"),
            R("GET", "/api/runs/([^/]+)/chart", lambda c: s.chart(
                c.m[0], c.q.get("name"), c.q.get("step"), c.q.get("history") == "1"), "run", "viewer"),
            R("POST", "/api/runs/([^/]+)/model-graph", lambda c: s.log_model_graph(
                c.actor, c.m[0], c.body.get("name"), c.body.get("graph")), "run", "member", ingest=True),
            R("GET", "/api/runs/([^/]+)/model-graph", lambda c: s.model_graph(c.m[0], c.q.get("name")), "run", "viewer"),
            R("GET", "/api/runs/([^/]+)/config", lambda c: {"text": s.config_text(c.m[0])}, "run", "viewer"),
            R("POST", "/api/runs/([^/]+)/eval", lambda c: s.log_eval(
                c.actor, c.m[0], c.body.get("set"), c.body.get("step"), c.body.get("rows"), c.body.get("epoch"),
                c.body.get("negatives")), "run", "member", ingest=True),
            R("GET", "/api/runs/([^/]+)/eval/samples", lambda c: s.eval_query(
                c.m[0], c.q.get("set"), c.q.get("step"), c.q, c.q.get("sort", "error"), int(c.q.get("limit", 24)),
                int(c.q.get("offset", 0))), "run", "viewer"),
            R("GET", "/api/runs/([^/]+)/eval/facets", lambda c: s.eval_facets(c.m[0], c.q.get("set"), c.q.get("step")),
              "run", "viewer"),
            R("GET", "/api/runs/([^/]+)/eval/sample", lambda c: s.eval_sample(
                c.m[0], c.q.get("set"), c.q.get("sample", "")), "run", "viewer"),
            R("GET", "/api/eval-sets", lambda c: s.eval_sets(c.project), "project", "viewer"),
            R("GET", "/api/eval-sets/samples", lambda c: s.dataset_samples(
                c.project, c.q.get("set"), _csv(c.q.get("runs")), c.q, c.q.get("sort", "wrong"), c.q.get("desc", "1") != "0",
                int(c.q.get("limit", 48)), int(c.q.get("offset", 0)), c.q.get("value"), c.q.get("compact") == "1"),
              "project", "viewer"),
            R("GET", "/api/eval-sets/summary", lambda c: s.dataset_summary(
                c.project, c.q.get("set"), _csv(c.q.get("runs")), c.q, c.q.get("by"), c.q.get("value")), "project", "viewer"),
            R("GET", "/api/eval-sets/reviews", lambda c: s.reviews_list(
                c.project, c.q.get("set"), c.q.get("since"), c.q.get("history") == "1", int(c.q.get("limit", 100_000)),
                c.q.get("sample")),
              "project", "viewer"),
            R("POST", "/api/eval-sets/review", lambda c: s.review_sample(
                c.actor, c.project, c.body.get("set"), c.body.get("sample"), c.body), "project", "member"),
            R("GET", "/api/compare", lambda c: s.compare(_csv(c.q.get("runs"))), "runs", "viewer"),
            R("GET", "/api/compare/charts", lambda c: s.compare_charts(_csv(c.q.get("runs"))), "runs", "viewer"),
            R("GET", "/api/posts/([^/]+)", lambda c: s.get_post(c.m[0]), "post", "viewer"),
            R("POST", "/api/comments", lambda c: s.comment(
                c.actor, c.body.get("target"), c.body.get("body"), c.body.get("kind", "note"), c.body.get("anchor", ""),
                c.body.get("parent_id")), "target", "member"),
            R("PATCH", "/api/comments/(\\d+)", lambda c: s.set_comment_status(
                c.actor, int(c.m[0]), c.body.get("status"), c.body.get("resolution_ref", "")), "comment", "member"),
            R("GET", "/api/handbook/proposals/(\\d+)", lambda c: s.handbook_proposal(c.m[0]), "proposal", "viewer"),
            R("POST", "/api/handbook/proposals/(\\d+)/reject", lambda c: s.reject_proposal(c.actor, c.m[0]),
              "proposal", "maintainer"),
            R("GET", "/api/designs/([^/]+)", lambda c: s.design(c.m[0], c.q.get("rev")), "design", "viewer"),
            R("PUT", "/api/designs/([^/]+)", lambda c: s.save_design(c.actor, c.m[0], c.body), "design", "member"),
            R("DELETE", "/api/designs/([^/]+)", lambda c: s.delete_design(c.actor, c.m[0], c.q.get("confirm")),
              "design", "member"),
            R("POST", "/api/designs/([^/]+)/proposals", lambda c: s.propose_design(
                c.actor, c.m[0], c.body.get("graph"), c.body.get("note")), "design", "member"),
            R("GET", "/api/design-proposals/(\\d+)", lambda c: s.design_proposal(c.m[0]), "design_proposal", "viewer"),
            R("POST", "/api/design-proposals/(\\d+)/reject", lambda c: s.reject_design_proposal(c.actor, c.m[0]),
              "design_proposal", "member"),
            R("DELETE", "/api/claims/(.+)", lambda c: s.release(c.actor, c.m[0]) or {"ok": True}, "claim", "member"),
        ]

    @staticmethod
    def _route(method, pattern, fn, scope, role=None, ingest=False):
        return method, re.compile(pattern + "/?$"), fn, scope, role, ingest

    # -------------------------------------------------------------- sign-in
    def _state(self, c):
        settings = self.store.site_settings()
        return {"setup": self.store.needs_setup(), "signup": settings["signup"], "site_name": settings["site_name"],
                "version": __version__}

    def _setup(self, c):
        """First run only: whoever holds the code printed by `hub serve` creates the first admin."""
        if not self.store.needs_setup():
            raise Forbidden("this hub is already set up; sign in instead")
        self.login_limit.check(f"setup:{c.ip}")
        if not self.setup_code or not secrets.compare_digest(str(c.body.get("code") or ""), self.setup_code):
            self.login_limit.hit(f"setup:{c.ip}")
            raise Forbidden("wrong setup code; it is printed in the terminal where `hub serve` runs")
        self.store.create_admin(c.body.get("name"), c.body.get("email"), c.body.get("password"), c.body.get("display"))
        self.setup_code = None
        return self._login(c, identifier=c.body.get("email"))

    def _login(self, c, identifier=None):
        ident = str(identifier or c.body.get("email") or "").strip().lower()
        keys = (f"ip:{c.ip}", f"id:{ident}")
        for key in keys:
            self.login_limit.check(key)
        try:
            session = self.store.login(ident, c.body.get("password"), c.ip, c.headers.get("User-Agent", ""))
        except Unauthorized:
            for key in keys:
                self.login_limit.hit(key)
            raise
        c.cookies.append(self._cookie(session["token"], SESSION_DAYS * 86400))
        return {"name": session["name"], "csrf": session["csrf"]}

    def _signup(self, c):
        self.signup_limit.check(c.ip)
        self.signup_limit.hit(c.ip)
        created = self.store.signup(c.body, c.ip)
        return {**created, **(self._login(c) if created["status"] == "active" else {})}

    def _use_reset(self, c):
        self.login_limit.check(f"reset:{c.ip}")
        self.login_limit.hit(f"reset:{c.ip}")
        return self.store.use_reset(c.body.get("token"), c.body.get("password"), c.ip)

    def _logout(self, c):
        if c.session:
            self.store.logout(c.session)
        c.cookies.append(self._cookie("", 0))
        return {"ok": True}

    def _cookie(self, value: str, max_age: int) -> str:
        return (f"{COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
                + ("; Secure" if self.secure_cookies else ""))

    # ---------------------------------------------------------------- access
    def identify(self, headers, ip) -> tuple[dict | None, str | None]:
        """(actor, session token) for a request. A bearer API key wins over the browser cookie."""
        token = (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        jar = SimpleCookie(headers.get("Cookie") or "")
        session = jar[COOKIE].value if COOKIE in jar and not token else None
        actor = self.store.authenticate(token or None, session)
        if actor:
            actor["ip"] = ip
        return actor, session

    def _scope_projects(self, scope, c) -> list[str | None]:
        """The project(s) a call is about, from the route's scope."""
        s = self.store
        if scope == "project":
            return [c.project]
        if scope == "project:m":
            return [c.m[0]]
        if scope == "runs":
            return [s.project_of("run", slug) for slug in _csv(c.q.get("runs"))] or [None]
        if scope == "target":
            return [s.project_of("ref", c.body.get("target"))]
        return [s.project_of(scope, c.m[0])]

    def authorize(self, c, scope, role, ingest_ok) -> None:
        actor = c.actor
        if scope == "public":
            return
        if actor is None:
            raise Unauthorized("sign in, or send an API key: set HUB_TOKEN (see `hub login`)")
        if actor["kind"] == "ingest":
            own_run = scope == "run" and c.m[0] == actor["run"]
            if not (ingest_ok and own_run) and scope != "any":
                raise Forbidden("a run's ingest token can only log to that run")
            actor["role"] = "member"
            return
        if scope in ("any", "user"):
            return
        if scope == "person":
            if actor["kind"] != "human":
                raise Forbidden("only a signed-in person can do this")
            return
        if scope == "admin":
            if not actor.get("admin"):
                raise Forbidden("only a site admin can do this")
            return
        roles = [self.store.role(actor, p) if p else None for p in self._scope_projects(scope, c)]
        if None in roles:  # not a member, or the thing does not exist: indistinguishable on purpose
            raise NotFound("not found, or you do not have access to it")
        actor["role"] = min(roles, key=rank)
        if rank(actor["role"]) < rank(role):
            raise Forbidden(f"this needs the {role} role in the project; you are a {actor['role']}")

    def dispatch(self, method, path, query, body, headers, ip="") -> tuple[object, list[str]]:
        """Run one API call. Returns (JSON payload, Set-Cookie values)."""
        for meth, pattern, fn, scope, role, ingest_ok in self.routes:
            if meth != method:
                continue
            match = pattern.fullmatch(path)
            if not match:
                continue
            actor, session = self.identify(headers, ip) if scope != "public" else (None, None)
            if actor and actor["via"] == "session" and method != "GET" and not secrets.compare_digest(
                    str(headers.get("X-Hub-CSRF") or ""), actor["csrf"]):
                raise Forbidden("missing or wrong X-Hub-CSRF header; reload the page")
            c = Call(self, actor, [urllib.parse.unquote(g) for g in match.groups()], query, body, headers, ip, session)
            self.authorize(c, scope, role, ingest_ok)
            return fn(c), c.cookies
        raise NotFound(f"no route for {method} {path}")


def make_handler(api: Api, trust_proxy: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "research-hub"
        sys_version = ""

        def log_message(self, fmt, *args):
            if os.environ.get("HUB_ACCESS_LOG"):
                super().log_message(fmt, *args)

        def _ip(self) -> str:
            forwarded = self.headers.get("X-Forwarded-For") if trust_proxy else None
            return forwarded.split(",")[0].strip() if forwarded else self.client_address[0]

        def _send(self, status, payload=None, raw: bytes | None = None, ctype="application/json", cache=None,
                  cookies=()):
            data = raw if raw is not None else json.dumps(payload, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache or "no-store")
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method):
            url = urllib.parse.urlsplit(self.path)
            try:
                if method == "GET" and not url.path.startswith("/api/"):
                    return self._static(url.path)
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise HubError("request body too large")
                if length and "json" not in (self.headers.get("Content-Type") or ""):
                    raise HubError("send JSON with Content-Type: application/json")
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if not isinstance(body, dict):
                    raise HubError("request body must be a JSON object")
                payload, cookies = api.dispatch(method, url.path, _qs(url.query), body, self.headers, self._ip())
                self._send(HTTPStatus.OK, payload, cookies=cookies)
            except HubError as e:
                self._send(e.status, {"error": str(e), "kind": type(e).__name__})
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "body is not valid JSON"})
            except Exception as e:
                print(f"[hub] {method} {url.path} failed: {e!r}", file=sys.stderr)
                self._send(500, {"error": "internal error; see the server log"})

        def _static(self, path):
            if path.startswith("/blobs/"):
                return self._blob(path.split("/", 2)[2])
            # Any other path without a file extension is a page of the single-page app.
            name = path.lstrip("/") if "." in path.rsplit("/", 1)[-1] else "index.html"
            file = (UI_DIR / name).resolve()
            if not file.is_relative_to(UI_DIR) or not file.is_file() or file.suffix not in STATIC:
                raise NotFound(path)
            cache = "public, max-age=31536000, immutable" if "/assets/" in path else "no-cache"
            return self._send(200, raw=file.read_bytes(), ctype=STATIC[file.suffix], cache=cache)

        def _blob(self, sha):
            """Logged images, masks and files. Any signed-in account may fetch one by its sha-256 id."""
            actor, _ = api.identify(self.headers, self._ip())
            if actor is None:
                raise Unauthorized("sign in to view this file")
            blob = api.store.db.blob_path(sha)
            if not blob:
                raise NotFound("blob not found")
            data = blob.read_bytes()
            mime = sniff_mime(data[:16])
            if mime is None:
                with api.store.connect() as conn:
                    row = conn.execute("SELECT mime FROM artifacts WHERE blob_sha=? LIMIT 1", (blob.name,)).fetchone()
                mime = row[0] if row else "text/plain; charset=utf-8"
            if mime in ("image/svg+xml", "text/html"):  # never let an upload run script on the hub's origin
                mime = "text/plain; charset=utf-8"
            return self._send(200, raw=data, ctype=mime, cache="private, max-age=31536000, immutable")

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_PATCH(self):
            self._handle("PATCH")

        def do_DELETE(self):
            self._handle("DELETE")

    return Handler


def bootstrap(store: Store) -> None:
    """First start only: create the admin, and optionally a first project, from the environment, so a container
    comes up ready without anyone opening the setup link. Does nothing once an admin exists."""
    email, password = os.environ.get("HUB_ADMIN_EMAIL"), os.environ.get("HUB_ADMIN_PASSWORD")
    if not (email and password and store.needs_setup()):
        return
    name = os.environ.get("HUB_ADMIN_NAME") or re.sub(r"[^a-z0-9_-]+", "-", email.split("@")[0].lower()).strip("-") or "admin"
    store.create_admin(name, email, password)
    print(f"[hub] created the admin account {name} ({email}) from HUB_ADMIN_EMAIL and HUB_ADMIN_PASSWORD", flush=True)
    project = os.environ.get("HUB_FIRST_PROJECT")
    if project:
        store.create_project({"name": name, "kind": "human", "admin": True}, project, project.replace("-", " ").capitalize(),
                             handbook=DEFAULT_HANDBOOK.read_text())
        print(f"[hub] created the project {project}", flush=True)


def _index_eval_results(store):
    """After an upgrade, pack earlier eval results for the Datasets page; no-op once it is done."""
    try:
        store.eval_backfill()
    except Exception as e:  # a background job must not take the hub down; it resumes at the next start
        print(f"[hub] indexing eval results failed: {e!r}", flush=True)


def serve(home, host="127.0.0.1", port=6230, public_url=None):
    """Run the hub. Behind a TLS proxy set HUB_TRUST_PROXY=1 so cookies are marked Secure and client IPs are read
    from X-Forwarded-For."""
    store = Store(home)
    bootstrap(store)
    behind_proxy = os.environ.get("HUB_TRUST_PROXY", "") not in ("", "0")
    api = Api(store, secure_cookies=behind_proxy)
    httpd = ThreadingHTTPServer((host, port), make_handler(api, trust_proxy=behind_proxy))
    base = (public_url or f"http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}").rstrip("/")
    print(f"[hub] serving {store.db.home} on {host}:{port}", flush=True)
    threading.Thread(target=_index_eval_results, args=(store,), daemon=True).start()
    if api.setup_code:
        print(f"[hub] first run: create the admin account at\n      {base}/#/setup?code={api.setup_code}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return httpd
