# Security

## Reporting a problem

Please report vulnerabilities privately through the repository's security advisories, not in a public issue.

## How access works

**Who you are**

- People sign in with an email and password. Passwords are hashed with scrypt (N=2^15, r=8, p=3) and never
  stored or logged. Minimum length is 10 characters.
- A browser session is a random token in an `HttpOnly`, `SameSite=Lax` cookie (and `Secure` behind a TLS
  proxy), stored hashed, valid for 30 days of inactivity. Every write from a browser must also carry the
  session's CSRF token.
- Scripts and agents send an API key (`Authorization: Bearer hub_…`). Keys are random 256-bit values, stored
  hashed, shown once, optionally expiring, and revocable. Each key belongs to one account.
- A run has an **ingest token** that can log to that run and do nothing else. Use it for training jobs.

**What you may do**

- Projects are private unless an owner makes them visible to every signed-in person (read-only).
- Roles per project: viewer (read), member (log runs, post, comment, chat), maintainer (handbook, members,
  correct any run), owner (visibility, other owners). You cannot grant a role above your own, and a project
  always keeps one owner.
- Agents are service accounts owned by a person. They can be viewers or members, never maintainers, and they
  cannot create keys, agents or invites.
- Deleting is for people only, and always asks for the name to be typed back. A run can be deleted by its
  owner or a project maintainer; a project only by one of its owners. Both are recorded in the audit log.
- Site admins manage accounts and sign-up settings and can open every project.
- Every API route declares the role it needs in one table (`research_hub/server.py`); a request for something
  in a project you cannot see gets the same "not found" as something that does not exist.

**Joining**

- The first admin is created with a one-time code printed on the server's console, or with `hub admin create`.
- Sign-up is by invitation by default. Invite links are single-use, expire after 7 days, and can be tied to an
  email address. Admins can switch to "anyone can ask, an admin approves" or to open sign-up.
- Password resets are one-time links created by an admin, valid for 24 hours. A new password ends every
  session of that account.

**Hardening**

- Repeated wrong passwords are throttled per address and per account (8 attempts per 15 minutes).
- Responses carry a Content-Security-Policy that allows scripts, styles and fonts only from the hub itself,
  plus `X-Frame-Options: DENY` and `nosniff`. Uploaded files are served with their detected type; HTML and SVG
  uploads are served as plain text so they cannot run in the hub's origin.
- Sign-ins, failed sign-ins, key, role, invite and account changes and deletions are written to an audit log that admins can
  read under **Site admin → Audit log**.
- The database file and new data directories are created readable by the hub's user only.
- In Docker the server never runs as root: the container starts as root only to hand over to the owner of
  the data folder (or to the unprivileged `hub` user), then drops every privilege before the hub starts.
- An admin created from `HUB_ADMIN_PASSWORD` has that password in the environment and in `.env`: change it
  after the first sign-in and remove the setting.

## What it does not do

- **No TLS.** The hub speaks plain HTTP; run it behind an HTTPS proxy for anything beyond localhost
  (`docs/deploy.md`).
- **No email.** Invite and reset links are shown to the person who creates them, to pass on themselves, and
  email addresses are not verified.
- **No single sign-on or two-factor authentication** yet.
- **Files are protected by sign-in, not by project.** A logged image is addressed by its SHA-256; any signed-in
  account that knows the hash can fetch it. Hashes are only shown to people who can see the run.
- **Run and post names are unique across the whole hub**, so creating one can reveal that the name is taken in a
  project you cannot see.
- Login throttling is kept in memory and resets when the hub restarts.
