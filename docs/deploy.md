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

```bash
docker compose up -d
docker compose logs hub          # the setup link
docker compose exec hub hub admin create ada --email ada@example.org
```

Data is in the `hub-data` volume. The container runs as an unprivileged user.

## systemd

`deploy/research-hub.service` is a user unit: copy it to `~/.config/systemd/user/`, adjust `HUB_HOME`, then
`systemctl --user enable --now research-hub`.

## Settings

| Variable | Meaning | Default |
|---|---|---|
| `HUB_HOME` | data directory | `~/.research_hub` |
| `HUB_HOST`, `HUB_PORT` | listen address | `127.0.0.1`, `6230` |
| `HUB_PUBLIC_URL` | address people use, for printed links | derived from host and port |
| `HUB_TRUST_PROXY` | `1` behind a TLS reverse proxy | off |
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
