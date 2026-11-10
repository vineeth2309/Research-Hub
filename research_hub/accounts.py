"""Accounts and access: people with passwords and browser sessions, agents as service accounts with API keys,
project roles, invites, password resets, site settings and the audit log."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from .core import (
    NAME,
    ROLES,
    Conflict,
    Forbidden,
    HubError,
    NotFound,
    Unauthorized,
    choice,
    hash_token,
    now,
    rank,
    rows,
    text,
)

SIGNUP_MODES = ("invite", "approval", "open")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}")
SESSION_DAYS = 30
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 3}  # OWASP-listed scrypt parameters; about 0.2 s per check
DEFAULT_SETTINGS = {"site_name": "Research Hub", "signup": "invite", "create_projects": "anyone"}


def _later(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=2 ** 27, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, maxmem=2 ** 27,
                             n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(got, base64.b64decode(digest))


# Checked when the account does not exist, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _password(value, name="", email="") -> str:
    if not isinstance(value, str) or not 10 <= len(value) <= 200:
        raise HubError("password must be 10 to 200 characters")
    if value.lower() in (name.lower(), email.lower()):
        raise HubError("password must differ from your name and email")
    return value


def _email(value) -> str:
    if not isinstance(value, str) or not EMAIL.fullmatch(value.strip()):
        raise HubError("a valid email address is required")
    return value.strip().lower()


def _name(value) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise HubError("name must be lowercase letters, digits, '_' or '-' (max 40), e.g. ada or ada-lovelace")
    return value


class Accounts:
    # ------------------------------------------------------------------- audit
    @staticmethod
    def _audit(conn, actor, action, target="", detail=""):
        who = actor if isinstance(actor, str) else actor.get("name", "")
        ip = "" if isinstance(actor, str) else actor.get("ip", "")
        conn.execute("INSERT INTO audit(ts,actor,action,target,detail,ip) VALUES(?,?,?,?,?,?)",
                     (now(), who, action, target, str(detail)[:500], ip))

    def audit_log(self, limit=100, offset=0) -> dict:
        with self.connect() as conn:
            return {"total": conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
                    "entries": rows(conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ? OFFSET ?",
                                                 (min(int(limit), 500), max(int(offset), 0))))}

    # ---------------------------------------------------------------- settings
    def site_settings(self) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='settings'").fetchone()
        return {**DEFAULT_SETTINGS, **(json.loads(row[0]) if row else {})}

    def set_site_settings(self, actor, data: dict) -> dict:
        current = self.site_settings()
        if "site_name" in data:
            current["site_name"] = text(data, "site_name", limit=60)
        if "signup" in data:
            current["signup"] = choice(data["signup"], SIGNUP_MODES, "signup")
        if "create_projects" in data:
            current["create_projects"] = choice(data["create_projects"], ("anyone", "admins"), "create_projects")
        with self.connect(write=True) as conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES('settings', ?)", (json.dumps(current),))
            self._audit(conn, actor, "settings.update", detail=json.dumps(current))
        return current

    def needs_setup(self) -> bool:
        with self.connect() as conn:
            return not conn.execute("SELECT 1 FROM participants WHERE admin=1 AND status='active'").fetchone()

    # ------------------------------------------------------------------ people
    def _insert_human(self, conn, name, email, password, display="", admin=False, status="active"):
        name, email = _name(name), _email(email)
        _password(password, name, email)
        if conn.execute("SELECT 1 FROM participants WHERE name=?", (name,)).fetchone():
            raise Conflict(f"the name {name!r} is taken")
        if conn.execute("SELECT 1 FROM participants WHERE email=?", (email,)).fetchone():
            raise Conflict("an account with this email already exists")
        conn.execute("INSERT INTO participants(name,kind,display,email,password_hash,admin,status,created) "
                     "VALUES(?,?,?,?,?,?,?,?)",
                     (name, "human", str(display or "")[:80], email, hash_password(password), int(admin), status, now()))
        return name

    def create_admin(self, name, email, password, display="") -> str:
        """First-run setup and `hub admin create`: an active site admin."""
        with self.connect(write=True) as conn:
            self._insert_human(conn, name, email, password, display, admin=True)
            self._audit(conn, name, "admin.create", f"participant:{name}")
        return name

    def signup(self, data: dict, ip="") -> dict:
        """Self-service sign-up. A valid invite always works; otherwise the site's signup mode decides."""
        mode = self.site_settings()["signup"]
        with self.connect(write=True) as conn:
            invite = None
            if data.get("invite"):
                invite = conn.execute("SELECT * FROM invites WHERE token_hash=? AND used_by='' AND expires>?",
                                      (hash_token(str(data["invite"])), now())).fetchone()
                if not invite:
                    raise Forbidden("this invite link is invalid, used or expired; ask for a new one")
                if invite["email"] and invite["email"] != _email(data.get("email")):
                    raise Forbidden("this invite was issued for a different email address")
            elif mode == "invite":
                raise Forbidden("sign-up is by invitation: ask an admin or a project maintainer for an invite link")
            status = "pending" if (mode == "approval" and not invite) else "active"
            name = self._insert_human(conn, data.get("name"), data.get("email"), data.get("password"),
                                      data.get("display"), status=status)
            if invite:
                conn.execute("UPDATE invites SET used_by=? WHERE id=?", (name, invite["id"]))
                if invite["project"]:
                    conn.execute("INSERT OR REPLACE INTO memberships VALUES(?,?,?,?,?)",
                                 (invite["project"], name, invite["role"], invite["created_by"], now()))
            self._audit(conn, {"name": name, "ip": ip}, "signup", f"participant:{name}", status)
        return {"name": name, "status": status}

    def login(self, identifier, password, ip="", client="") -> dict:
        """Check an email (or name) and password; returns a new session {token, csrf, name}."""
        ident = str(identifier or "").strip().lower()
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT name, password_hash, status FROM participants WHERE kind='human' AND "
                               "(email=? OR name=?)", (ident, ident)).fetchone()
            ok = check_password(str(password or ""), row["password_hash"] if row else _DUMMY_HASH)
            if not row or not ok:
                self._audit(conn, {"name": ident[:60], "ip": ip}, "login.failed")
                conn.commit()
                raise Unauthorized("wrong email or password")
            if row["status"] != "active":
                raise Forbidden("this account is waiting for an admin's approval" if row["status"] == "pending"
                                else "this account is disabled; contact an admin")
            session = self._new_session(conn, row["name"], ip, client)
            self._audit(conn, {"name": row["name"], "ip": ip}, "login")
        return {**session, "name": row["name"]}

    @staticmethod
    def _new_session(conn, name, ip, client) -> dict:
        token, csrf, ts = secrets.token_urlsafe(32), secrets.token_urlsafe(24), now()
        conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
                     (hash_token(token), name, csrf, ts, ts, _later(days=SESSION_DAYS), str(client)[:200], ip))
        conn.execute("DELETE FROM sessions WHERE expires<?", (ts,))
        return {"token": token, "csrf": csrf}

    def authenticate(self, token: str | None = None, session: str | None = None) -> dict | None:
        """Resolve an API key, a run's ingest token or a browser session to an actor; None when nothing was sent."""
        if not token and not session:
            return None
        ts = now()
        with self.connect(write=True) as conn:
            if token:
                h = hash_token(token)
                key = conn.execute("SELECT id, participant FROM api_keys WHERE key_hash=? AND revoked='' AND "
                                   "(expires='' OR expires>?)", (h, ts)).fetchone()
                if key:
                    conn.execute("UPDATE api_keys SET last_used=? WHERE id=?", (ts, key["id"]))
                    return self._actor(conn, key["participant"], "key", ts)
                run = conn.execute("SELECT slug, owner FROM runs WHERE ingest_token_hash=?", (h,)).fetchone()
                if run:
                    return {"name": run["owner"], "kind": "ingest", "run": run["slug"], "admin": False, "via": "ingest"}
                raise Unauthorized("unknown, revoked or expired API key")
            row = conn.execute("SELECT participant, csrf FROM sessions WHERE id_hash=? AND expires>?",
                               (hash_token(session), ts)).fetchone()
            if not row:
                raise Unauthorized("your session has ended; sign in again")
            conn.execute("UPDATE sessions SET last_seen=?, expires=? WHERE id_hash=?",
                         (ts, _later(days=SESSION_DAYS), hash_token(session)))
            return {**self._actor(conn, row["participant"], "session", ts), "csrf": row["csrf"]}

    @staticmethod
    def _actor(conn, name, via, ts) -> dict:
        p = conn.execute("SELECT name, kind, display, email, admin, status, model, focus, owner FROM participants "
                         "WHERE name=?", (name,)).fetchone()
        if not p or p["status"] != "active":
            raise Unauthorized("this account is not active")
        conn.execute("UPDATE participants SET last_seen=? WHERE name=?", (ts, name))
        return {**dict(p), "admin": bool(p["admin"]), "via": via}

    def logout(self, session: str) -> None:
        with self.connect(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE id_hash=?", (hash_token(session),))

    def sessions(self, actor) -> list[dict]:
        with self.connect() as conn:
            return rows(conn.execute("SELECT substr(id_hash,1,12) AS id, created, last_seen, client, ip FROM sessions "
                                     "WHERE participant=? AND expires>? ORDER BY last_seen DESC", (actor["name"], now())))

    def revoke_session(self, actor, session_id) -> None:
        with self.connect(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE participant=? AND substr(id_hash,1,12)=?",
                         (actor["name"], str(session_id)))

    def update_profile(self, actor, data: dict) -> dict:
        with self.connect(write=True) as conn:
            if "display" in data:
                conn.execute("UPDATE participants SET display=? WHERE name=?",
                             (text(data, "display", False, 80), actor["name"]))
            if "password" in data:
                me = conn.execute("SELECT password_hash, email FROM participants WHERE name=?", (actor["name"],)).fetchone()
                if not check_password(str(data.get("current_password") or ""), me["password_hash"]):
                    raise Forbidden("current password is wrong")
                self._set_password(conn, actor["name"], _password(data["password"], actor["name"], me["email"] or ""))
                self._audit(conn, actor, "password.change")
        return {"ok": True}

    @staticmethod
    def _set_password(conn, name, password):
        """A new password signs the account out everywhere."""
        conn.execute("UPDATE participants SET password_hash=? WHERE name=?", (hash_password(password), name))
        conn.execute("DELETE FROM sessions WHERE participant=?", (name,))

    def create_reset(self, actor, name, hours=24) -> dict:
        """Admin: a one-time link that lets ``name`` choose a new password."""
        token = secrets.token_urlsafe(32)
        with self.connect(write=True) as conn:
            if not conn.execute("SELECT 1 FROM participants WHERE name=? AND kind='human'", (name,)).fetchone():
                raise NotFound(f"no person named {name!r}")
            conn.execute("INSERT INTO password_resets VALUES(?,?,?,?,0)",
                         (hash_token(token), name, actor["name"], _later(hours=float(hours))))
            self._audit(conn, actor, "password.reset_link", f"participant:{name}")
        return {"name": name, "token": token}

    def use_reset(self, token, password, ip="") -> dict:
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT participant FROM password_resets WHERE token_hash=? AND used=0 AND expires>?",
                               (hash_token(str(token or "")), now())).fetchone()
            if not row:
                raise Forbidden("this reset link is invalid, used or expired")
            me = conn.execute("SELECT email FROM participants WHERE name=?", (row["participant"],)).fetchone()
            self._set_password(conn, row["participant"], _password(password, row["participant"], me["email"] or ""))
            conn.execute("UPDATE password_resets SET used=1 WHERE token_hash=?", (hash_token(str(token)),))
            self._audit(conn, {"name": row["participant"], "ip": ip}, "password.reset")
        return {"name": row["participant"]}

    def users(self) -> list[dict]:
        """Admin view of every account."""
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT p.name, p.kind, p.display, p.email, p.admin, p.status, p.owner, p.model, p.created, p.last_seen, "
                "(SELECT COUNT(*) FROM memberships m WHERE m.participant=p.name) AS projects FROM participants p "
                "ORDER BY p.kind DESC, p.name"))

    def update_user(self, actor, name, data: dict) -> dict:
        """Admin: approve, disable or re-enable an account, or grant/revoke site admin."""
        with self.connect(write=True) as conn:
            user = conn.execute("SELECT kind, admin, status FROM participants WHERE name=?", (name,)).fetchone()
            if not user:
                raise NotFound(f"no account named {name!r}")
            status = choice(data.get("status", user["status"]), ("active", "pending", "disabled"), "status")
            admin = bool(data.get("admin", user["admin"]))
            if admin and user["kind"] != "human":
                raise HubError("only a person can be a site admin")
            if user["admin"] and (not admin or status != "active") and conn.execute(
                    "SELECT COUNT(*) FROM participants WHERE admin=1 AND status='active'").fetchone()[0] <= 1:
                raise Conflict("this is the last active admin; make someone else an admin first")
            conn.execute("UPDATE participants SET status=?, admin=? WHERE name=?", (status, int(admin), name))
            if status != "active":
                conn.execute("DELETE FROM sessions WHERE participant=?", (name,))
            self._audit(conn, actor, "user.update", f"participant:{name}", f"status={status} admin={int(admin)}")
        return {"name": name, "status": status, "admin": admin}

    # ------------------------------------------------------------------ agents
    def create_agent(self, actor, name, model="", focus="", projects=()) -> dict:
        """A service account owned by the person creating it, added as a member to the given projects."""
        self._require_person(actor)
        name = _name(name)
        with self.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM participants WHERE name=?", (name,)).fetchone():
                raise Conflict(f"the name {name!r} is taken")
            ts = now()
            conn.execute("INSERT INTO participants(name,kind,owner,model,focus,created) VALUES(?,?,?,?,?,?)",
                         (name, "agent", actor["name"], str(model or "")[:120], str(focus or "")[:500], ts))
            for project in projects or ():
                if rank(self._role(conn, actor, project)) < rank("maintainer"):
                    raise Forbidden(f"you need to be a maintainer of {project!r} to add an agent to it")
                conn.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (project, name, "member", actor["name"], ts))
            self._audit(conn, actor, "agent.create", f"participant:{name}", ",".join(projects or ()))
            key = self._new_key(conn, actor, name, "initial key", None)
        return {"name": name, **key}

    def update_agent(self, actor, name, data: dict) -> dict:
        with self.connect(write=True) as conn:
            self._manages(conn, actor, name, agents_only=True)
            for field, limit in (("model", 120), ("focus", 500)):
                if field in data:
                    conn.execute(f"UPDATE participants SET {field}=? WHERE name=?", (str(data[field] or "")[:limit], name))
            if "status" in data:
                conn.execute("UPDATE participants SET status=? WHERE name=?",
                             (choice(data["status"], ("active", "disabled"), "status"), name))
                self._audit(conn, actor, "agent.update", f"participant:{name}", f"status={data['status']}")
        return {"name": name}

    def my_agents(self, actor) -> list[dict]:
        with self.connect() as conn:
            where = "" if actor.get("admin") else "AND owner=?"
            args = () if actor.get("admin") else (actor["name"],)
            out = rows(conn.execute("SELECT name, model, focus, owner, status, created, last_seen FROM participants "
                                    f"WHERE kind='agent' {where} ORDER BY name", args))
            for a in out:
                a["projects"] = [r[0] for r in conn.execute("SELECT project FROM memberships WHERE participant=?", (a["name"],))]
            return out

    @staticmethod
    def _require_person(actor):
        if not actor or actor.get("kind") != "human":
            raise Forbidden("only a signed-in person can do this")

    def _manages(self, conn, actor, name, agents_only=False) -> dict:
        """The account ``name`` if the actor may manage its keys: themselves, their agent, or anything for an admin."""
        self._require_person(actor)
        target = conn.execute("SELECT name, kind, owner FROM participants WHERE name=?", (name,)).fetchone()
        allowed = target and (actor.get("admin") or target["owner"] == actor["name"]
                              or (target["name"] == actor["name"] and not agents_only))
        if not allowed or (agents_only and target["kind"] != "agent"):
            raise NotFound(f"no {'agent' if agents_only else 'account'} named {name!r} that you manage")
        return dict(target)

    # ---------------------------------------------------------------- API keys
    @staticmethod
    def _new_key(conn, actor, participant, label, days) -> dict:
        secret = "hub_" + secrets.token_urlsafe(32)
        expires = _later(days=float(days)) if days else ""
        cur = conn.execute("INSERT INTO api_keys(participant,label,prefix,key_hash,created_by,created,expires) "
                           "VALUES(?,?,?,?,?,?,?)",
                           (participant, label, secret[:10], hash_token(secret), actor["name"], now(), expires))
        return {"id": cur.lastrowid, "key": secret, "prefix": secret[:10], "expires": expires}

    def create_key(self, actor, participant, label, days=None) -> dict:
        """A new API key for yourself or an agent you own. The secret is returned once and never stored."""
        label = text({"l": label}, "l", limit=80)
        with self.connect(write=True) as conn:
            self._manages(conn, actor, participant)
            key = self._new_key(conn, actor, participant, label, days)
            self._audit(conn, actor, "key.create", f"participant:{participant}", f"{label} ({key['prefix']}…)")
        return key

    def keys(self, actor, participant) -> list[dict]:
        with self.connect() as conn:
            self._manages(conn, actor, participant)
            return rows(conn.execute("SELECT id, label, prefix, created_by, created, last_used, expires, revoked "
                                     "FROM api_keys WHERE participant=? ORDER BY id DESC", (participant,)))

    def revoke_key(self, actor, key_id) -> dict:
        with self.connect(write=True) as conn:
            key = conn.execute("SELECT participant, prefix FROM api_keys WHERE id=?", (int(key_id),)).fetchone()
            if not key:
                raise NotFound("no such key")
            self._manages(conn, actor, key["participant"])
            conn.execute("UPDATE api_keys SET revoked=? WHERE id=? AND revoked=''", (now(), int(key_id)))
            self._audit(conn, actor, "key.revoke", f"participant:{key['participant']}", key["prefix"] + "…")
        return {"id": int(key_id), "revoked": True}

    # ------------------------------------------------------------- memberships
    @staticmethod
    def _role(conn, actor, project) -> str | None:
        """The actor's role in a project. Site admins are owners everywhere; signed-in people can view internal projects."""
        proj = conn.execute("SELECT visibility FROM projects WHERE slug=?", (project,)).fetchone()
        if not proj or not actor:
            return None
        if actor.get("admin"):
            return "owner"
        row = conn.execute("SELECT role FROM memberships WHERE project=? AND participant=?",
                           (project, actor["name"])).fetchone()
        if row:
            return row["role"]
        return "viewer" if proj["visibility"] == "internal" and actor.get("kind") == "human" else None

    def role(self, actor, project) -> str | None:
        with self.connect() as conn:
            return self._role(conn, actor, project)

    def members(self, project) -> list[dict]:
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT p.name, p.kind, p.display, p.model, p.focus, p.owner, p.status, p.last_seen, m.role, "
                "(SELECT COUNT(*) FROM runs r WHERE r.project=m.project AND r.owner=p.name AND r.status='running') AS running "
                "FROM memberships m JOIN participants p ON p.name=m.participant WHERE m.project=? "
                "ORDER BY p.kind DESC, p.name", (project,)))

    def set_member(self, actor, project, name, role) -> dict:
        """Add someone to a project or change their role. You cannot grant a role above your own."""
        choice(role, ROLES, "role")
        with self.connect(write=True) as conn:
            mine = self._role(conn, actor, project)
            target = conn.execute("SELECT kind, status FROM participants WHERE name=?", (name,)).fetchone()
            if not target:
                raise NotFound(f"no account named {name!r}")
            if rank(role) > rank(mine):
                raise Forbidden(f"a {mine} cannot grant the {role} role")
            if target["kind"] == "agent" and rank(role) > rank("member"):
                raise HubError("an agent can be a viewer or a member; maintainers and owners are people")
            current = conn.execute("SELECT role FROM memberships WHERE project=? AND participant=?", (project, name)).fetchone()
            if current and rank(current["role"]) > rank(mine):
                raise Forbidden(f"a {mine} cannot change a {current['role']}")
            self._keep_an_owner(conn, project, name, current, role)
            conn.execute("INSERT OR REPLACE INTO memberships VALUES(?,?,?,?,?)", (project, name, role, actor["name"], now()))
            self._audit(conn, actor, "member.set", f"project:{project}", f"{name}={role}")
        return {"project": project, "name": name, "role": role}

    def remove_member(self, actor, project, name) -> None:
        with self.connect(write=True) as conn:
            mine = self._role(conn, actor, project)
            current = conn.execute("SELECT role FROM memberships WHERE project=? AND participant=?", (project, name)).fetchone()
            if not current:
                raise NotFound(f"{name!r} is not a member of {project}")
            if name != actor["name"] and (rank(mine) < rank("maintainer") or rank(current["role"]) > rank(mine)):
                raise Forbidden(f"a {mine} cannot remove a {current['role']}; you can only leave the project yourself")
            self._keep_an_owner(conn, project, name, current, None)
            conn.execute("DELETE FROM memberships WHERE project=? AND participant=?", (project, name))
            self._audit(conn, actor, "member.remove", f"project:{project}", name)

    @staticmethod
    def _keep_an_owner(conn, project, name, current, new_role):
        if current and current["role"] == "owner" and new_role != "owner" and conn.execute(
                "SELECT COUNT(*) FROM memberships WHERE project=? AND role='owner'", (project,)).fetchone()[0] <= 1:
            raise Conflict(f"{name} is the only owner of {project}; make someone else an owner first")

    # ----------------------------------------------------------------- invites
    def create_invite(self, actor, email="", project="", role="member", days=7) -> dict:
        """A sign-up link, optionally tied to an email and to a project role. Admins can invite without a project."""
        self._require_person(actor)
        choice(role, ROLES, "role")
        token = secrets.token_urlsafe(24)
        with self.connect(write=True) as conn:
            if project:
                mine = self._role(conn, actor, project)
                if rank(mine) < rank("maintainer") or rank(role) > rank(mine):
                    raise Forbidden("you need to be a maintainer of the project, and cannot invite above your own role")
            elif not actor.get("admin"):
                raise Forbidden("only an admin can invite someone without a project")
            cur = conn.execute("INSERT INTO invites(token_hash,email,project,role,created_by,created,expires) "
                               "VALUES(?,?,?,?,?,?,?)", (hash_token(token), _email(email) if email else "", project or "",
                                                         role, actor["name"], now(), _later(days=float(days))))
            self._audit(conn, actor, "invite.create", f"project:{project}" if project else "", email or "")
        return {"id": cur.lastrowid, "token": token, "project": project or "", "role": role}

    def invites(self, actor, project="") -> list[dict]:
        with self.connect() as conn:
            return rows(conn.execute(
                "SELECT id, email, project, role, created_by, created, expires, used_by FROM invites "
                "WHERE project=? OR ?='' ORDER BY id DESC LIMIT 200", (project, project)))

    def revoke_invite(self, actor, invite_id, project="") -> None:
        with self.connect(write=True) as conn:
            cur = conn.execute("DELETE FROM invites WHERE id=? AND used_by='' AND (project=? OR ?='')",
                               (int(invite_id), project, project))
            if not cur.rowcount:
                raise NotFound("no unused invite with that id")
            self._audit(conn, actor, "invite.revoke", detail=str(invite_id))

    def invite_info(self, token) -> dict:
        """What a sign-up page may show for an invite link."""
        with self.connect() as conn:
            row = conn.execute("SELECT email, project, role FROM invites WHERE token_hash=? AND used_by='' AND expires>?",
                               (hash_token(str(token or "")), now())).fetchone()
        if not row:
            raise NotFound("this invite link is invalid, used or expired")
        return dict(row)
