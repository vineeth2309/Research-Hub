# Running the hub for a team

## Start it

```bash
hub serve --home /srv/research_hub --host 127.0.0.1 --port 6230
```

`--home` (or `HUB_HOME`) holds everything: `hub.sqlite3` and `blobs/`. The first start prints a one-time link
for creating the admin account. If you cannot open that link, create the admin on the server instead:

```bash
hub admin --home /srv/research_hub create ada --email ada@example.org      # asks for a password
```

By default the hub listens on `127.0.0.1` only. To serve other machines, put it behind HTTPS.

## HTTPS

Passwords and keys travel in every request, so anything beyond your own machine needs TLS. Run a reverse proxy
in front and tell the hub about it:

```
# Caddyfile
hub.example.org {
    reverse_proxy 127.0.0.1:6230
}
```

```bash
HUB_TRUST_PROXY=1 HUB_PUBLIC_URL=https://hub.example.org hub serve --home /srv/research_hub
```

`HUB_TRUST_PROXY=1` marks the session cookie `Secure` and reads the client address from `X-Forwarded-For`
(only set it when a proxy you control is the only way to reach the hub). On a trusted private network you can
instead run `hub serve --host 0.0.0.0` without TLS; anyone on that network can then observe traffic.

## Docker

The repository's `docker-compose.yml` works unchanged on any machine with Docker:

```bash
git clone https://github.com/vineeth2309/Research-Hub
cd Research-Hub
docker compose up -d            # builds the image and starts the hub on http://localhost:6230
docker compose logs hub         # prints the one-time link for creating the admin account
```

It restarts by itself after a crash or a reboot (`restart: unless-stopped`; Docker itself must be set to start
at boot, which is the default on most Linux installs). After pulling a new version:
`docker compose build && docker compose up -d` (two steps, so the restart always uses the image just built).

To change anything, copy `.env.example` to `.env` and edit it. `docker-compose.yml` stays as it is.

| In `.env` | Meaning | Default |
|---|---|---|
| `HUB_BIND` | address on the host; `0.0.0.0` lets other machines connect | `127.0.0.1` |
| `HUB_PORT` | port on the host | `6230` |
| `HUB_PUBLIC_URL` | the address people type; used in printed links | `http://localhost:6230` |
| `HUB_DATA` | a folder on the host for the data, instead of a Docker volume | the `hub-data` volume |
| `HUB_TRUST_PROXY` | `1` when a reverse proxy terminates HTTPS in front | off |
| `HUB_ADMIN_EMAIL`, `HUB_ADMIN_PASSWORD` | create the admin on the first start, with no setup link | not set |
| `HUB_ADMIN_NAME` | that admin's username | from the email |
| `HUB_FIRST_PROJECT` | also create a first project with this slug | not set |

A team hub that other machines can reach, with its data in a folder you can back up, and ready to sign in to.
Create the folder yourself first, so that it belongs to you, then put this in `.env`:

```bash
HUB_BIND=0.0.0.0
HUB_PUBLIC_URL=http://hub.example.org:6230
HUB_DATA=/srv/research_hub
HUB_ADMIN_EMAIL=you@example.org
HUB_ADMIN_PASSWORD=choose-at-least-10-characters
HUB_FIRST_PROJECT=my-project
```

and run `docker compose up -d`.

- The admin settings are read only while the hub has no admin. Change the password after signing in and
  delete those lines from `.env`.
- The hub runs as the owner of the data folder, so a folder you created needs no `chown`. With the default
  volume it runs as the unprivileged `hub` user. The container starts as root only to make that choice.
- `.env` is ignored by git. It can hold a password, so keep it readable by you only (`chmod 600 .env`).
- Commands inside the container: `docker compose exec hub hub admin list`.

## systemd

`deploy/research-hub.service` is a user unit: copy it to `~/.config/systemd/user/`, adjust `HUB_HOME`, then
`systemctl --user enable --now research-hub`.

## Disk

The database is SQLite in WAL mode with `synchronous=NORMAL`: it cannot be corrupted by a crash or a power cut,
but a power cut can lose the last few commits. Reads never write, and "last seen" times are refreshed at most
once a minute, so requests stay fast even when the data folder is on a disk that training jobs keep busy. If
writes are still slow there, put the data folder on a quieter disk.

## Settings

| Variable | Meaning | Default |
|---|---|---|
| `HUB_HOME` | data directory | `~/.research_hub` |
| `HUB_HOST`, `HUB_PORT` | listen address | `127.0.0.1`, `6230` |
| `HUB_PUBLIC_URL` | address people use, for printed links | derived from host and port |
| `HUB_TRUST_PROXY` | `1` behind a TLS reverse proxy | off |
| `HUB_ADMIN_EMAIL`, `HUB_ADMIN_PASSWORD`, `HUB_ADMIN_NAME` | first start only: create the admin without the setup link | not set |
| `HUB_FIRST_PROJECT` | first start only: also create a project with this slug | not set |
| `HUB_ACCESS_LOG` | `1` to print every request | off |

Sign-up mode (invitation only, admin approval, or open), who may create projects and the site name are under
**Site admin → Sign-up** in the dashboard.

## Accounts you cannot reach from the dashboard

```bash
hub admin --home /srv/research_hub list
hub admin --home /srv/research_hub reset-password ada     # prints a one-time link
hub admin --home /srv/research_hub set bo --status active # approve; or --status disabled, --admin true
```

These work on the database directly, so they need shell access to the server and nothing else.

## Backups

Stop the hub or use SQLite's online backup, then copy the blobs:

```bash
python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d)" \
    /srv/research_hub/hub.sqlite3 /backup/hub-$(date +%F).sqlite3
rsync -a /srv/research_hub/blobs/ /backup/blobs/
```

Blobs are named by their SHA-256 and never change, so the copy is incremental. To restore, put both back and
start the hub.

## Upgrading

Install the new release (`pip install -U git+https://github.com/vineeth2309/Research-Hub`) and restart. The database records its schema version; a newer release migrates
it on start, and an older release refuses to open a newer database rather than damage it. Back up first.
