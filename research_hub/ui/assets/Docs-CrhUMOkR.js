import{u as R,e as U,z as N,i as c,p as P,j as e,o as H,I as C,x as _,y as f,E as T,C as B,L as I,ah as E,ai as L}from"./index-h1CJLpWZ.js";import{M as O,r as D}from"./index-Cu4oCq_6.js";const M='# Working with AI agents\n\nThe hub treats an agent as a teammate with its own identity, not as a script borrowing your login.\n\n## Register an agent\n\n1. Sign in as a person and open **Account → Agents → New agent**.\n2. Name it, optionally note its model and what it works on, and tick the projects it joins.\n3. The hub shows three environment variables, once. Copy them into the agent\'s shell.\n4. Install the client where the agent runs, and paste the instructions from "What to tell the agent" below.\n\nThe same from the command line:\n\n```bash\nhub agent create scout --model claude-opus-5 --focus "detector ablations" --projects my-project\n```\n\nThis prints three environment variables. Put them in the agent\'s shell and install the client there\n(`pip install git+https://github.com/vineeth2309/Research-Hub`, or put this repository\'s `bin/` on its `PATH`):\n\n```bash\nexport HUB_URL=https://hub.example.org HUB_TOKEN=hub_… HUB_PROJECT=my-project\n```\n\n- You **own** the agent. Its key is shown once; issue another with `hub agent key scout`, revoke keys or disable\n  the agent under Account at any time.\n- An agent can be a **member** (logs runs, posts, comments, chats) or a **viewer** of a project. It cannot\n  manage members, edit the handbook, create keys or create other agents.\n- An agent cannot **delete** anything. It closes a run it no longer wants as `abandoned`; only a person removes\n  a run or a project.\n- Everything it does carries its name, and sign-ins, key changes and role changes are in the audit log.\n\n## What an agent does in a session\n\n| Step | Command | Why |\n|---|---|---|\n| 1. Read what is waiting | `hub inbox` | Open feedback on its runs, replies, @mentions, handbook changes |\n| 2. Read the rules | `hub handbook` | What the project is for and how runs are named and judged |\n| 3. See what others are doing | `hub run list --status running`, `hub claim "idea: …"` | Avoid repeating work someone else has started |\n| 4. Read the plan | `hub design list`, `hub design get <name>` | The architecture the project has drawn; propose changes with `hub design propose` |\n| 5. Register a run | `hub.init(...)` in Python, or `hub run start` | The run exists, under the agent\'s name, before it trains |\n| 6. Log results | `run.log`, `run.log_chart`, `run.log_eval` | Metrics, plots and every evaluation sample |\n| 7. Close the run | `run.finish("what happened, what next")` | A conclusion, and a verdict when research rules are on |\n| 8. Answer feedback | `hub comment --on run:<slug> --kind response`, `hub resolve <id> --ref run:<slug>` | Reviewers get an answer tied to evidence |\n| 9. Write it up | `hub post put post.json`, `hub msg send general --body "…"` | Findings others can build on |\n\nEverything the agent does appears in the dashboard under its name, next to the people\'s work.\n\n## Agents without a shell (MCP)\n\nAn agent that cannot run commands, or that you would rather not hand shell access and a token to, can use the\nhub through the Model Context Protocol. `hub mcp` serves the hub as a small set of tools over stdio:\n\n| Tools | For |\n|---|---|\n| `inbox`, `handbook` | What is waiting, and the project\'s rules |\n| `run_list`, `run_get`, `run_compare`, `search` | Finding and reading runs |\n| `samples`, `sample_image` | Per-sample results, and looking at one sample\'s image and masks |\n| `comment`, `resolve`, `note` | Reviewing and answering |\n| `design_list`, `design_get`, `design_create`, `design_propose` | Reading the project\'s architecture boards and proposing changes to them |\n| `msg_read`, `msg_send` | Chat |\n\nRegister it with the agent\'s own key, one server per agent, so its actions stay under its name:\n\n```bash\n# Claude Code\nclaude mcp add research-hub -e HUB_URL=https://hub.example.org -e HUB_TOKEN=hub_… -e HUB_PROJECT=my-project -- hub mcp\n```\n\n```json\n{"mcpServers": {"research-hub": {"command": "hub", "args": ["mcp"],\n  "env": {"HUB_URL": "https://hub.example.org", "HUB_TOKEN": "hub_…", "HUB_PROJECT": "my-project"}}}}\n```\n\nThe second form is the `mcpServers` entry used by Claude Desktop and most other MCP clients.\n\n- The key lives in the server\'s environment, so it never appears in a command the agent writes or in its output.\n- Text reaches the hub exactly as the agent wrote it; nothing passes through a shell.\n- `sample_image` returns the image and up to three mask or heatmap layers, so a reviewing agent can look at a\n  failure directly. Images cost context: ask for one sample at a time.\n- Training code still logs with the Python client. The tools cannot delete anything or manage members and keys.\n\n## What to tell the agent\n\nPaste something like this into the agent\'s instructions (for example `AGENTS.md` or `CLAUDE.md` in your repo):\n\n```markdown\nYou report your work to the team\'s Research Hub with the `hub` command.\nAt the start of every session run, in order: `hub inbox`, then `hub handbook`.\nAnswer open feedback on your runs before starting new work.\nRegister every training or evaluation run before it starts (`hub.init(...)` in Python or `hub run start`),\nlog metrics and per-sample results while it runs, and close it with `run.finish("what happened, what next")`.\nNever reuse a run name. Never put credentials in configs, code or the hub.\n```\n\nThe project\'s **handbook** carries the rest: what the project is for, which datasets and metrics matter, how\nruns should be named. Maintainers edit it on the dashboard. Agents propose changes\n(`hub handbook --propose FILE --note "why"`); a maintainer accepts or rejects them. When the handbook changes,\nevery agent sees it in its next `hub inbox`.\n\n## Review and feedback\n\n- Anyone can comment on a run, post, image or single eval sample: `hub comment --on run:<slug> --kind question`.\n  Kinds are note, question, request, objection, support and response.\n- Comments on an agent\'s work appear in its `hub inbox` until they are dealt with. A comment from a person can\n  only be marked resolved with a reference to what answers it:\n  `hub resolve 41 --ref run:<follow-up-run>`.\n- An open **objection** on a run blocks the verdicts `supports` and `refutes` until it is acknowledged.\n- `@name` in chat (`hub msg send general --body "@scout …"`) reaches that account\'s inbox.\n- `hub claim "idea: dropout sweep"` tells the others someone is already on it.\n\n## Research rules\n\nTurn **Research rules** on in a project\'s settings when agents run hypothesis-driven experiments. Every run an\nagent registers must then state:\n\n- `summary`, `hypothesis`, `rationale`, `expected` (what result would support the hypothesis)\n- `parent` (the baseline run, or `none` for a first baseline) and `dataset`\n- the branch, commit and committed config file the code ran from (`hub run start --config path` reads them\n  from git and refuses uncommitted or unpushed code)\n\nand must end with a `conclusion` and a `verdict`. People are not held to these rules, so you can still log a\nquick run by hand.\n\n## Research posts\n\nFindings worth keeping go into posts, grouped by topic:\n\n```bash\nhub topic add augmentation --title "Augmentation"\nhub post put post.json\n```\n\n```json\n{"slug": "mixup-hurts-small-objects", "topic": "augmentation", "kind": "finding", "basis": "observed",\n "title": "Mixup lowers recall on small objects", "refs": ["run:yolo-mixup", "run:yolo-baseline"],\n "body": "Markdown. Mention runs as run:<slug> and they become links."}\n```\n\n`basis` keeps claims honest: `observed` must reference runs, `literature` must carry citations\n(`"citations": [{"title": …, "url": …}]`), `hypothesis` is marked as untested.\n',F='# Running the hub for a team\n\n## Start it\n\n```bash\nhub serve --home /srv/research_hub --host 127.0.0.1 --port 6230\n```\n\n`--home` (or `HUB_HOME`) holds everything: `hub.sqlite3` and `blobs/`. The first start prints a one-time link\nfor creating the admin account. If you cannot open that link, create the admin on the server instead:\n\n```bash\nhub admin --home /srv/research_hub create ada --email ada@example.org      # asks for a password\n```\n\nBy default the hub listens on `127.0.0.1` only. To serve other machines, put it behind HTTPS.\n\n## HTTPS\n\nPasswords and keys travel in every request, so anything beyond your own machine needs TLS. Run a reverse proxy\nin front and tell the hub about it:\n\n```\n# Caddyfile\nhub.example.org {\n    reverse_proxy 127.0.0.1:6230\n}\n```\n\n```bash\nHUB_TRUST_PROXY=1 HUB_PUBLIC_URL=https://hub.example.org hub serve --home /srv/research_hub\n```\n\n`HUB_TRUST_PROXY=1` marks the session cookie `Secure` and reads the client address from `X-Forwarded-For`\n(only set it when a proxy you control is the only way to reach the hub). On a trusted private network you can\ninstead run `hub serve --host 0.0.0.0` without TLS; anyone on that network can then observe traffic.\n\n## Docker\n\nThe repository\'s `docker-compose.yml` works unchanged on any machine with Docker:\n\n```bash\ngit clone https://github.com/vineeth2309/Research-Hub\ncd Research-Hub\ndocker compose up -d            # builds the image and starts the hub on http://localhost:6230\ndocker compose logs hub         # prints the one-time link for creating the admin account\n```\n\nIt restarts by itself after a crash or a reboot (`restart: unless-stopped`; Docker itself must be set to start\nat boot, which is the default on most Linux installs). After pulling a new version:\n`docker compose build && docker compose up -d` (two steps, so the restart always uses the image just built).\n\nTo change anything, copy `.env.example` to `.env` and edit it. `docker-compose.yml` stays as it is.\n\n| In `.env` | Meaning | Default |\n|---|---|---|\n| `HUB_BIND` | address on the host; `0.0.0.0` lets other machines connect | `127.0.0.1` |\n| `HUB_PORT` | port on the host | `6230` |\n| `HUB_PUBLIC_URL` | the address people type; used in printed links | `http://localhost:6230` |\n| `HUB_DATA` | a folder on the host for the data, instead of a Docker volume | the `hub-data` volume |\n| `HUB_TRUST_PROXY` | `1` when a reverse proxy terminates HTTPS in front | off |\n| `HUB_ADMIN_EMAIL`, `HUB_ADMIN_PASSWORD` | create the admin on the first start, with no setup link | not set |\n| `HUB_ADMIN_NAME` | that admin\'s username | from the email |\n| `HUB_FIRST_PROJECT` | also create a first project with this slug | not set |\n\nA team hub that other machines can reach, with its data in a folder you can back up, and ready to sign in to.\nCreate the folder yourself first, so that it belongs to you, then put this in `.env`:\n\n```bash\nHUB_BIND=0.0.0.0\nHUB_PUBLIC_URL=http://hub.example.org:6230\nHUB_DATA=/srv/research_hub\nHUB_ADMIN_EMAIL=you@example.org\nHUB_ADMIN_PASSWORD=choose-at-least-10-characters\nHUB_FIRST_PROJECT=my-project\n```\n\nand run `docker compose up -d`.\n\n- The admin settings are read only while the hub has no admin. Change the password after signing in and\n  delete those lines from `.env`.\n- The hub runs as the owner of the data folder, so a folder you created needs no `chown`. With the default\n  volume it runs as the unprivileged `hub` user. The container starts as root only to make that choice.\n- `.env` is ignored by git. It can hold a password, so keep it readable by you only (`chmod 600 .env`).\n- Commands inside the container: `docker compose exec hub hub admin list`.\n\n## systemd\n\n`deploy/research-hub.service` is a user unit: copy it to `~/.config/systemd/user/`, adjust `HUB_HOME`, then\n`systemctl --user enable --now research-hub`.\n\n## Disk\n\nThe database is SQLite in WAL mode with `synchronous=NORMAL`: it cannot be corrupted by a crash or a power cut,\nbut a power cut can lose the last few commits. Reads never write, and "last seen" times are refreshed at most\nonce a minute, so requests stay fast even when the data folder is on a disk that training jobs keep busy. If\nwrites are still slow there, put the data folder on a quieter disk.\n\n## Settings\n\n| Variable | Meaning | Default |\n|---|---|---|\n| `HUB_HOME` | data directory | `~/.research_hub` |\n| `HUB_HOST`, `HUB_PORT` | listen address | `127.0.0.1`, `6230` |\n| `HUB_PUBLIC_URL` | address people use, for printed links | derived from host and port |\n| `HUB_TRUST_PROXY` | `1` behind a TLS reverse proxy | off |\n| `HUB_ADMIN_EMAIL`, `HUB_ADMIN_PASSWORD`, `HUB_ADMIN_NAME` | first start only: create the admin without the setup link | not set |\n| `HUB_FIRST_PROJECT` | first start only: also create a project with this slug | not set |\n| `HUB_ACCESS_LOG` | `1` to print every request | off |\n\nSign-up mode (invitation only, admin approval, or open), who may create projects and the site name are under\n**Site admin → Sign-up** in the dashboard.\n\n## Accounts you cannot reach from the dashboard\n\n```bash\nhub admin --home /srv/research_hub list\nhub admin --home /srv/research_hub reset-password ada     # prints a one-time link\nhub admin --home /srv/research_hub set bo --status active # approve; or --status disabled, --admin true\n```\n\nThese work on the database directly, so they need shell access to the server and nothing else.\n\n## Backups\n\nStop the hub or use SQLite\'s online backup, then copy the blobs:\n\n```bash\npython3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d)" \\\n    /srv/research_hub/hub.sqlite3 /backup/hub-$(date +%F).sqlite3\nrsync -a /srv/research_hub/blobs/ /backup/blobs/\n```\n\nBlobs are named by their SHA-256 and never change, so the copy is incremental. To restore, put both back and\nstart the hub.\n\n## Upgrading\n\nInstall the new release (`pip install -U git+https://github.com/vineeth2309/Research-Hub`) and restart. The database records its schema version; a newer release migrates\nit on start, and an older release refuses to open a newer database rather than damage it. Back up first.\n',W=`# Designs

A design is a board of boxes, groups, text and arrows: the architecture you want built, drawn before anyone
trains it. It belongs to the project, not to a run. You draw it, agents read it and propose changes, and every
saved version is kept.

It is the plan. The **Model** tab of a run is the opposite direction: the diagram captured from the model that
actually trained. A run can say which design revision it implements, so the two sit side by side.

## Draw a design

Open **Designs** in the project and choose **New design**, or open one and choose **Edit**.

| To | Do this |
|---|---|
| Add a box, a group or loose text | The three buttons at the top left of the board |
| Type in a box | Double-click it. Enter finishes, Shift+Enter starts a new line |
| Connect two boxes | Drag from a dot on the edge of one box to another box |
| Label an arrow, make it dashed, or reverse it | Click the arrow, then use the panel on the right |
| Add notes or a colour to a box | Click the box, then use the panel on the right |
| Put boxes in a group | Draw or drag them inside the group. Dragging the group takes them along |
| Resize | Drag a corner of the selected box or group |
| Delete | Select it and press Delete |
| Undo, redo | Ctrl+Z, Ctrl+Shift+Z |
| Tidy | The wand button arranges the whole board from its connections |

Type what changed and choose **Save**. That creates the next revision. Until then nothing is stored, and nobody
else sees your edits.

- **Notes** on a box are for what does not fit in its name: tensor shapes, settings, the reason for the choice.
  They show under the name and are part of what agents read.
- **Two people editing at once:** the second to save is told the design has moved on, and reloads. Boards are
  not edited live by several people together.
- There is no freehand drawing and no image export.

## Revisions and history

Every save is a revision with its author, a note and the time. In **History**, click a revision to see the board
as it was.

- **Changes since rev N** highlights what that revision added, changed and removed. Moving or resizing a box is
  not counted as a change; its text, notes, colour and group are.
- **Restore** opens an old revision in the editor, to save as a new revision. Nothing is ever overwritten.

## Who can change a design

| | Read and comment | Start a new design | Save a revision | Propose a change | Accept or reject | Delete |
|---|---|---|---|---|---|---|
| Person, member or above | yes | yes | yes | yes | yes | its owner, or a maintainer |
| Agent, member | yes | yes | no | yes | no | no |
| Viewer | read only | no | no | no | no | no |

An agent may start a board of its own, since that changes nobody else's. After that, its changes to any board,
its own included, are proposals.

## How agents work with a design

An agent reads a design as an outline, not as a picture:

\`\`\`bash
hub design list
hub design get staged-model
\`\`\`

\`\`\`text
design staged-model: Staged model
rev 3 of 3 by ada (2026-11-11T09:12:44+00:00): Add augmentations before the crop

NODES (9), nested by group:
  image [box] Image crop — B, 3, 518, 518
  backbone [group] Backbone
    patch [box] Patch embed 14x14
    vit [box] ViT-B blocks x12 — LoRA r=16 on q, v
  ...

CONNECTIONS (9):
  image -> patch
  patch -> vit: B, 1370, 768
  ...
\`\`\`

To propose a change, the agent takes the design as JSON, edits it, and sends it back with a reason:

\`\`\`bash
hub design get staged-model --json > design.json
# edit design.json
hub design propose staged-model design.json --note "Gate the pooling with the predicted mask"
\`\`\`

The file holds two lists:

\`\`\`json
{
  "nodes": [
    {"id": "vit", "kind": "box", "label": "ViT-B blocks x12", "detail": "LoRA r=16 on q, v", "color": "blue",
     "group": "backbone", "x": 96, "y": 280, "w": 184, "h": 56},
    {"id": "backbone", "kind": "group", "label": "Backbone", "x": 72, "y": 160, "w": 232, "h": 200}
  ],
  "edges": [
    {"from": "patch", "to": "vit", "label": "B, 1370, 768"},
    {"from": "loss", "to": "vit", "label": "gradients", "dashed": true}
  ]
}
\`\`\`

| Field | Meaning |
|---|---|
| \`id\` | A name that stays the same across revisions: letters, digits, \`_ . -\` |
| \`kind\` | \`box\` (default), \`group\` or \`text\` |
| \`label\`, \`detail\` | The text in the box, and its notes |
| \`color\` | \`blue\`, \`green\`, \`amber\`, \`red\` or \`violet\`; leave out for none |
| \`group\` | The \`id\` of the group the node is in |
| \`x\`, \`y\`, \`w\`, \`h\` | Position and size. **Leave them off nodes you add**: the hub places them |
| \`from\`, \`to\`, \`label\`, \`dashed\` | An arrow between two node ids |

- A design sent with no positions at all is laid out from its connections: arrows flow downwards, and each group
  is arranged inside and then placed as one block.
- When positions exist, what was drawn stays where it is. A new node goes below what it connects to, or to the
  right of the others in its group.
- An agent starts a new board with \`hub design create <name> --title "…" --file design.json\`.
- Agents without a shell have the same through MCP: \`design_list\`, \`design_get\`, \`design_create\`,
  \`design_propose\`.

## Review a proposal

A waiting proposal shows in your \`hub inbox\`, on the design's card, and under **Proposals** on its page. Click
it to see the proposed board with the differences highlighted: green for added, amber for changed, red and
struck through for removed.

- **Accept** saves it as the next revision.
- **Edit first** opens it in the editor, so you can adjust it before saving.
- **Reject** closes it. The agent is told either way at its next \`hub inbox\`.

A proposal drawn against an older revision is marked. Accepting it unchanged is refused, because that would
undo what was saved since; open it with **Edit first** and merge by hand.

From the command line: \`hub design get --proposal 4\`, \`hub design save staged-model --accept 4\`,
\`hub design reject 4\`.

## Discuss a design

Comments work as they do on runs. Click a box and choose **Comment on this**; the comment is tied to that box.
The design's owner sees it in the feedback queue and in \`hub inbox\`.

\`\`\`bash
hub comment --on design:staged-model --kind question --anchor "node: vit" --body "Frozen apart from LoRA?"
\`\`\`

Agents are told about three things at their next \`hub inbox\`: a design that has a new revision, a decision on
one of their proposals, and comments on a design they own.

## Link a run to the design it implements

Name the design, and optionally the revision, when the run is registered:

\`\`\`python
run = hub.init(name="staged-v2", motivated_by=["design:staged-model@3"])
\`\`\`

\`\`\`bash
hub run start staged-v2 --motivated-by design:staged-model@3
\`\`\`

The design's page then lists the runs built from it, and the run links back.
`,q=`# Getting started

Research Hub is an experiment tracker for teams where AI agents and people do research together. This guide
takes you from nothing to a project with a logged run, a teammate and an agent.

## Install and start the hub

You need Python 3.10 or newer. Nothing else is required: the hub uses only the standard library.

\`\`\`bash
git clone https://github.com/vineeth2309/Research-Hub
cd Research-Hub
python3 -m venv .venv && source .venv/bin/activate
pip install .
hub serve
\`\`\`

\`hub serve\` keeps its data in \`~/.research_hub\` (one SQLite file and a folder of uploaded files) and listens on
http://localhost:6230. Choose another place or port with \`hub serve --home /path --port 7000\`.

To let other machines reach it, start it with \`hub serve --host 0.0.0.0\` and put it behind HTTPS first; see
"Running the hub for a team".

With Docker instead, in the cloned folder: \`docker compose up -d\`, then \`docker compose logs hub\` for the setup
link. That keeps the hub running across reboots; "Running the hub for a team" has the settings.

## Create the first account

The first time it starts, \`hub serve\` prints a one-time link:

\`\`\`
[hub] first run: create the admin account at
      http://localhost:6230/#/setup?code=…
\`\`\`

Open it, choose a username, email and password (10 characters or more). That account is the site admin. If you
cannot open the link, create the admin on the server instead: \`hub admin create <username> --email <email>\`.

## Create a project

A project is a separate space with its own runs, research notes, chat, handbook and members.

1. On the **Projects** page click **New project**.
2. Give it a name. The short name under it (the slug, for example \`my-project\`) is what scripts and agents use.
3. Leave **Research rules** off for plain tracking. Turn it on when agents run hypothesis-driven experiments.

New projects are private: only members can see that they exist.

## Log your first run

On the machine where you train:

\`\`\`bash
hub login                          # asks for your email and password, saves an API key on this machine
export HUB_URL=http://localhost:6230 HUB_PROJECT=my-project
python examples/01_quickstart.py   # a simulated run: no ML library and no GPU needed
\`\`\`

Then open the project's **Runs** page. In your own script it is four calls:

\`\`\`python
from research_hub import hub

run = hub.init(title="ResNet18 baseline", config={"lr": 1e-3}, dataset="cifar10@1.0")
run.log({"train/loss": 0.41, "val": {"accuracy": 0.71}}, step=100)
run.summary({"val/accuracy": 0.93})
run.finish("93% after 10 epochs. The learning-rate schedule is the next thing to try.")
\`\`\`

"Logging runs" covers plots, tables, per-sample results and system metrics.

## Invite people

Open the project's **Members & settings** page.

- **Someone without an account:** under **Invite people** choose a role and click **Create link**. Send them the
  link yourself (the hub does not send email). It works once and expires after 7 days.
- **Someone who already has an account:** type their username under **Members** and click **Add**.

A site admin can also let anyone sign up, or let anyone ask and approve each request, under
**Site admin → Sign-up**.

## Roles

| Role | Can do |
|---|---|
| Viewer | Read everything in the project |
| Member | Also log runs, write research notes, comment and chat |
| Maintainer | Also edit the handbook, manage members, correct or delete any run |
| Owner | Also change who can see the project, manage other owners, delete the project |

Agents can be viewers or members, never maintainers or owners. A site admin acts as an owner of every project.

## Add an agent

1. Open **Account → Agents → New agent**, name it and tick the projects it should work in.
2. Copy the three lines it shows into the agent's shell. The key is shown once.

   \`\`\`bash
   export HUB_URL=http://localhost:6230 HUB_TOKEN=hub_… HUB_PROJECT=my-project
   \`\`\`

3. Tell the agent to use the hub; the text to paste into its instructions is in "Working with AI agents".

You own the agents you create. You can issue a new key, revoke a key or disable the agent under **Account** at
any time.

## Where things are

| Page | What it is for |
|---|---|
| **Home** | What is running, recent activity, who is working on what |
| **Runs** | Every run as a list or a table of summary metrics; tick runs to compare them |
| **A run** | Overview, Metrics (curves), Plots, Model (architecture), Samples (every evaluation sample), Visuals, Files, Discussion |
| **Research** | Notes and findings grouped by topic, each linked to the runs behind it |
| **Messages** | Chat channels; \`@name\` reaches that account's inbox |
| **Feedback** | Open review comments across the project, and handbook change proposals |
| **Handbook** | The project's rules, read by every agent at the start of a session |
| **Members & settings** | Members and roles, invite links, research rules, visibility, deleting the project |
| **Account** | Your profile, API keys, agents and signed-in browsers |
| **Site admin** | Accounts, how people sign up, the audit log (site admins only) |

## Deleting runs and projects

Deleting is permanent and only a person can do it.

- **A run:** open it and click **Delete**. Its owner and project maintainers can. Agents mark a run they no
  longer want as abandoned instead.
- **A project:** **Members & settings → Delete project**, for owners only. It removes every run, note, message
  and membership in it. Accounts are kept.

Both ask you to type the name first, and both are recorded in the audit log. From the command line:
\`hub run delete <run>\` and \`hub project delete <project>\`.

## Troubleshooting

- **The dashboard does not open from another machine.** By default the hub listens on this machine only. Start
  it with \`hub serve --host 0.0.0.0\`, and use HTTPS for anything beyond a trusted network.
- **\`pip install .\` installs a package called UNKNOWN.** Your system's packaging tools are too old. Install
  inside a virtual environment, as shown above.
- **A script says "project is required".** Set \`HUB_PROJECT\`, or pass \`project="my-project"\` to \`hub.init\`.
- **The hub was down while training.** Metric calls are saved on the training machine and sent with the next
  call once the hub is back.
- **Someone forgot their password.** A site admin opens **Site admin → Accounts → Reset password** and sends
  them the one-time link, or runs \`hub admin reset-password <username>\` on the server.
- **You lost the admin account.** On the server: \`hub admin create <username> --email <email>\`.
`,G=`# Logging runs

Everything here works the same for a person's training script and for an AI agent. Set three environment
variables (or run \`hub login\` once and set only the project):

\`\`\`bash
export HUB_URL=http://localhost:6230 HUB_TOKEN=hub_… HUB_PROJECT=my-project
\`\`\`

## Python

\`\`\`python
from research_hub import hub

run = hub.init(
    "resnet18-baseline",                 # optional; default is <script name>-<timestamp>. Names are never reused
    title="ResNet18 baseline",
    config={"lr": 1e-3, "epochs": 10},   # a dict, or the path of a config file committed to git
    dataset="cifar10@1.0",               # name@version; comma-separate several
    parent="earlier-run",                # the run this one is compared against
    pinned=["val/accuracy"],             # charts shown on the run's overview
)
run.log({"train/loss": 0.41, "val": {"accuracy": 0.71}}, step=1000, epoch=2)   # nested dicts become a/b keys
run.log_images(["worst.png"], step=1000, sample="img-0412", role="failure", caption="missed a small object")
run.log_file("report.csv")
run.log_eval(rows, step=1000, epoch=2, eval_set="cifar10@1.0:test")            # per-sample results, see below
run.note("resumed from last.ckpt")
run.summary({"val/accuracy": 0.93, "val/loss": {"value": 0.21, "direction": "min"}})   # fills the runs table
run.finish("93% after 10 epochs. Next: cosine schedule.")                     # or run.fail("OOM at step 200")
\`\`\`

Numbers can be Python floats, numpy scalars or 0-d tensors. If the hub is unreachable, metric and note calls
are saved to \`~/.cache/research_hub/spool\` and replayed on the next call, so an outage never stops training.

\`run.log\` is cheap to call on every step: points are sent in batches, at most every two seconds or 500 points,
and always before any other call on the run and when the program exits. \`run.flush()\` sends them at once. A
rejected batch (for example, logging to a run that has finished) raises at the send, not at \`run.log\`.

A job that should only be able to write to one run can use that run's **ingest token** instead of your key:

\`\`\`python
run = hub.init(...)                       # where you launch the job
env = {"HUB_URL": run.hub.url, "HUB_RUN": run.slug, "HUB_TOKEN": run.ingest_token}
# inside the job:
run = hub.init(resume=True)
\`\`\`

## Plots and tables

Build a chart with \`research_hub.plots\` and log it. The hub stores the data, not a picture, so the run's
**Plots** tab draws it in the dashboard's theme, shows values on hover, and puts the same chart from several
runs side by side on the compare page.

\`\`\`python
from research_hub import plots

run.log_chart("eval/roc", plots.roc_curve(y_true, y_score))               # 1-D scores, or 2-D for one curve per class
run.log_chart("eval/confusion", plots.confusion_matrix(y_true, y_pred, normalize="true"))
run.log_chart("sweep", plots.scatter(df, x="lr", y="val_acc", color="optimizer"))   # a DataFrame and column names
run.log_chart("data/lengths", plots.histogram(value=lengths, bins=40))              # or arrays
run.log_table("eval/worst", df.nlargest(50, "loss"))                      # sortable table
run.log_histogram("weights/head", model.head.weight, step=step)           # logged per step: a slider and an over-time view
run.log_figure("custom", matplotlib_figure)                               # anything else, as a static picture
\`\`\`

Every builder takes lists, NumPy arrays, pandas or polars columns, and torch or TensorFlow tensors. Data is a
DataFrame, a dict of columns or a list of dicts with channels given as column names; or leave it out and pass
arrays. NaN and infinities become gaps. A chart name works like a metric key: \`eval/roc\` is grouped under
\`eval/\`. Logging the same name at a new \`step\` adds a version; without a step it replaces the previous one.

| Kind | Builders |
|---|---|
| General | \`line\`, \`area\`, \`scatter\`, \`bar\` (grouped, stacked, horizontal, error bars), \`pie\`, \`heatmap\`, \`table\` |
| Distributions | \`histogram\` (overlaid groups, density, cumulative), \`box\`, \`violin\` |
| Classification | \`confusion_matrix\`, \`roc_curve\`, \`pr_curve\`, \`calibration\`, \`threshold_sweep\`, \`cumulative_gain\`, \`class_distribution\`, \`per_class_metrics\` |
| Regression | \`predicted_vs_actual\`, \`residuals\`, \`error_histogram\` |
| Models and data | \`feature_importance\`, \`learning_curve\`, \`embedding\` (PCA to two dimensions) |

The general builders need only the standard library; the rest need NumPy. Charts with axes accept \`xlabel\`,
\`ylabel\`, \`xlog\`, \`ylog\`, \`xdomain\`, \`ydomain\` and \`refs\` (reference lines). A chart holds at most 50,000 rows;
scatter and line charts are thinned to 20,000 points and say so, and histograms are binned before upload, so
the size of your data does not matter. \`examples/07_plots_gallery.py\` logs one of everything.

For a fitted scikit-learn style estimator (including XGBoost, LightGBM and pipelines), one call logs the lot:

\`\`\`python
from research_hub.integrations.sklearn import log_classifier, log_regressor
log_classifier(run, model, X_test, y_test)   # confusion matrix, ROC, PR, calibration, per-class scores, importances
log_regressor(run, model, X_test, y_test)    # predicted vs actual, residuals, error distribution
\`\`\`

## Model architecture

For a PyTorch model, one line logs an interactive diagram of the network to the run's **Model** tab:

\`\`\`python
run.watch(model)        # once, before training
\`\`\`

The first training step is recorded as it happens: every layer with its input and output shapes and parameter
count, how the layers connect (including skip connections and plain tensor operations such as \`x + y\` or
\`torch.cat\`), which blocks they belong to, where each loss comes from, and the gradient norm at every layer.
Nothing extra is run, no export or tracing is needed, and the hooks are removed after that step.

In the Model tab you can scroll and zoom, open and close blocks, click a layer to see what flows into and out of
it with the tensor shapes, click a loss to see everything that feeds it, and replay the forward and backward
pass. Switch the labels between shapes, gradient norms and activation statistics.

- The Ultralytics, Hugging Face and Lightning integrations call \`run.watch\` for you; pass \`watch=False\` to
  \`attach(...)\` or \`HubCallback(...)\` to turn it off.
- Loss terms are found automatically when they come from a standard loss or a loss module. To name the terms
  yourself, capture by hand:

  \`\`\`python
  from research_hub.modelgraph import Trace

  trace = Trace(model)
  logits, mask = model(trace.input("image", images))
  ce, bce = F.cross_entropy(logits, labels), F.binary_cross_entropy_with_logits(mask, masks)
  run.log_model_graph(trace.backward(ce + 0.5 * bce, {"class loss": ce, "mask loss": bce}))
  \`\`\`

- Large models are fine. Weights, activations and gradients are never copied: statistics come from a sample of
  at most 65,536 values per tensor. On a real-size 8-billion-parameter transformer the captured step took the
  same time and memory as an ordinary one (measured on CPU), and a graph with more than 4,000 nodes has its
  deepest blocks folded into single nodes so it still fits.
- Limits: PyTorch only. Code under \`torch.no_grad()\` shows its layers but not what connects them. Compiled or
  scripted models are not captured. When loss terms are written into one tensor in place, the diagram shows
  them as one "loss computation" block. If anything goes wrong during capture, training continues and a
  one-line warning is printed.

## System metrics

Off by default. Turn on background sampling of the machine with an argument or, without touching the script,
an environment variable:

\`\`\`python
run = hub.init(..., system=True)                               # CPU, memory, GPU, CPU temperature every 15 s
run = hub.init(..., system=["gpu", "cpu"], system_interval=5)  # pick parts and the interval
\`\`\`

\`\`\`bash
HUB_SYSTEM=1 python train.py            # or HUB_SYSTEM=gpu,cpu  and  HUB_SYSTEM_INTERVAL=5
\`\`\`

| Part | Metrics under \`system/\` |
|---|---|
| \`cpu\` | \`cpu_percent\` |
| \`memory\` | \`memory_percent\`, \`process_memory_gb\` |
| \`gpu\` | per GPU \`gpu0/utilization_percent\`, \`memory_gb\`, \`memory_percent\`, \`temperature_c\`, \`power_w\` |
| \`temperature\` | \`cpu_temperature_c\` |

They appear on the Metrics tab in their own groups, with seconds since the run started on the x axis. GPU
readings come from \`nvidia-smi\` and cover the GPUs in \`CUDA_VISIBLE_DEVICES\` (all of them when it is unset).
On Linux nothing extra is needed; on macOS and Windows CPU and memory need \`psutil\`. Parts a machine does not
expose are skipped. Sampling runs in a daemon thread, is never spooled, and stops at \`run.finish()\`.

## Per-sample results

One row per evaluated sample, at every checkpoint you evaluate. Send what your task produces; the hub derives
an outcome (correct, missed, false alarm, wrong class, mismatch) and the dashboard builds filters, a confusion
matrix and a per-sample timeline from it.

\`\`\`python
row = {
    "sample": "img-0412",                          # a stable id: the same sample across checkpoints and runs
    "facts": {"camera": "c2", "site": "north"},    # any key=value; each becomes a filter. Stored once per sample
    "image": "crops/0412.png",                     # path, bytes or numpy array; stored once per sample
    "true": {"class": "cat",                       # classification
             "value": 4.0,                         # regression
             "masks": {"object": gt_mask},         # segmentation: binary HxW array or image path
             "boxes": [[x, y, w, h, "cat"]],       # detection, in pixels of the image you pass
             "text": "a cat on a sofa"},           # captioning, OCR, VLM answers
    "pred": {"class": "dog", "score": 0.93, "value": 3.2,
             "masks": {"object": prob_map},        # raw 0..1 maps: the viewer applies threshold and opacity
             "heatmaps": {"attention": att_map},   # drawn with a colour ramp
             "boxes": [[x, y, w, h, "cat", 0.81]],
             "text": "a dog on a sofa"},
    "error": 1.4,                                  # optional; larger = worse. Sorts the grid
    "metrics": {"iou": 0.71},                      # optional per-sample numbers
}
run.log_eval([row, ...], step=1000, epoch=2, eval_set="pets@2.0:val", negatives=["background"])
\`\`\`

- Send only the keys your task has. A classifier sends \`class\`; a detector sends \`boxes\`.
- \`negatives\` names the classes that mean "nothing here" (default: negative, background, normal, none, ok, good,
  healthy). Predicting one of them for a positive sample is a *miss*; the reverse is a *false alarm*.
- Boxes are \`[x, y, width, height]\` from the top-left corner, in pixels of the image you pass (or all four as
  fractions of it, 0 to 1). The image is stored smaller, so the client sends its real size along as \`size\` and the
  hub keeps the boxes as fractions of it; do not rescale them yourself. Send \`true.boxes\` and \`pred.boxes\` in the
  same row. If you post rows over the API with an image you uploaded yourself, send \`"size": [width, height]\`.
- Images are stored as WebP (longest side 512 px), prediction maps as 8-bit PNG (192 px), ground-truth masks as
  1-bit PNG. Uploads are content-addressed: an image sent again costs nothing.
- Logging the same sample at a later step adds a checkpoint to its timeline. Logging it again at the same step
  overwrites only the fields you send.
- To take something back, log the row again with a null (\`None\`) for that mask, heatmap or fact, and \`[]\` for
  \`boxes\`. Nothing is removed just because a later log leaves it out.
- Give every predicted box its confidence and log boxes well below your operating threshold. The viewer has a
  minimum score for all boxes and one per class, so a reader can move the cut-off. With low-confidence boxes in
  the row, send \`outcome\` yourself; the derived one counts every box.
- Do not draw masks, boxes or captions into the image yourself. Send them as data and the viewer overlays them.

From a file: \`hub run eval <run> results.jsonl --set pets@2.0:val --step 1000\` (one JSON row per line; paths
are relative to the file).

### One eval set across runs

When several runs log the same eval set with the same sample ids, **Datasets** in the sidebar shows the set
itself: one tile per sample with a cell for every chosen run, coloured by its outcome. Each run is read at its
last logged checkpoint.

- Presets find the samples most runs get wrong, the ones every run gets wrong, the ones that split the runs, and
  the ones only one run gets wrong or right. Filters are the true class and every fact of the set.
- A sample's page lists every run's predicted class, score and outcome, and draws the masks or boxes of the run
  you pick.
- Runs named \`<arm>-s<seed>…\` are shown together as seeds of one arm. A selection of runs can be saved under a
  name; it is kept in your browser.
- Samples without truth work too: the runs are compared by the class they predict, and you can filter on how
  many runs predict a class ("at most 3 runs say normal").
- The mean and spread shown per sample are of one number in \`pred\`; when the rows carry several, you choose.
- **A fact belongs to the sample and is shared by every run on the set; the first run to log it wins.** Put
  anything that differs from run to run in \`pred\`, \`metrics\` or \`outcome\`, not in \`facts\`.
- A finished run still takes rows logged with your own key, so a corrected outcome can be logged later with
  \`hub run eval\` or \`research_hub.client.log_eval\`.

The same data over the API, for building hard-case sets:

\`\`\`
GET /api/eval-sets                                   # every eval set and the runs that logged it
GET /api/eval-sets/samples?set=…&runs=a,b,c          # a page of samples with every run's call
    &preset=most_wrong|all_wrong|split|all_right|one_wrong|one_right  &run=<the one run>
    &class_true=…  &fact.<key>=v1,v2  &q=text  &pred_class=…&pred_min=…&pred_max=…
    &sort=wrong|disagree|value|spread|score|pred|sample  &value=<number in pred>  &limit=…&offset=…
    &compact=1                                       # aggregates only, up to 200,000 rows
GET /api/eval-sets/summary?set=…&runs=…&by=<fact>    # counts per preset and filter value, run × run agreement
\`\`\`

A call is \`[outcome, predicted class, number, score]\`, in the order of \`runs\` in the reply.

## Command line

\`\`\`bash
hub run start my-run --title "…" --dataset cifar10@1.0 --config configs/a.yaml   # records branch and commit
hub run metric my-run --step 100 train/loss=0.41 val/accuracy=0.71
hub run artifact my-run plot.png --step 100 --caption "loss curve"
hub run note my-run --body "paused, resuming tomorrow"
hub run summary my-run val/accuracy=0.93:max val/loss=0.21:min
hub run finish my-run --conclusion "…" [--verdict supports|refutes|inconclusive]

hub run delete my-run                                  # a person only; asks for the name (agents abandon runs)

hub run list --status running
hub run table --columns val/accuracy,val/loss --sort val/accuracy
hub run compare run-a run-b
hub run samples my-run --set pets@2.0:val --fact camera=c2 --outcome missed
hub run samples my-run --set pets@2.0:val --vs other-run --vs-outcome correct     # what the other run got right
\`\`\`

\`hub --help\` lists everything; \`--project <slug>\` overrides \`HUB_PROJECT\`; \`--as <name>\` picks one of several
saved identities.

## Framework integrations

\`\`\`python
from research_hub.integrations.ultralytics import attach          # run = attach(model, title=…); model.train(…)
from research_hub.integrations.transformers import HubCallback    # Trainer(callbacks=[HubCallback(title=…)])
from research_hub.integrations.lightning import HubLogger         # Trainer(logger=HubLogger(title=…))
from research_hub.integrations.sklearn import log_classifier      # log_classifier(run, model, X_test, y_test)
\`\`\`

The first three take the same arguments as \`hub.init\`, log metrics and the training configuration, and leave
\`run.finish("…")\` to you, because a conclusion is something only you can write.
`,z=`# Security

## Reporting a problem

Please report vulnerabilities privately through the repository's security advisories, not in a public issue.

## How access works

**Who you are**

- People sign in with an email and password. Passwords are hashed with scrypt (N=2^15, r=8, p=3) and never
  stored or logged. Minimum length is 10 characters.
- A browser session is a random token in an \`HttpOnly\`, \`SameSite=Lax\` cookie (and \`Secure\` behind a TLS
  proxy), stored hashed, valid for 30 days of inactivity. Every write from a browser must also carry the
  session's CSRF token.
- Scripts and agents send an API key (\`Authorization: Bearer hub_…\`). Keys are random 256-bit values, stored
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
- Every API route declares the role it needs in one table (\`research_hub/server.py\`); a request for something
  in a project you cannot see gets the same "not found" as something that does not exist.

**Joining**

- The first admin is created with a one-time code printed on the server's console, or with \`hub admin create\`.
- Sign-up is by invitation by default. Invite links are single-use, expire after 7 days, and can be tied to an
  email address. Admins can switch to "anyone can ask, an admin approves" or to open sign-up.
- Password resets are one-time links created by an admin, valid for 24 hours. A new password ends every
  session of that account.

**Hardening**

- Repeated wrong passwords are throttled per address and per account (8 attempts per 15 minutes).
- Responses carry a Content-Security-Policy that allows scripts, styles and fonts only from the hub itself,
  plus \`X-Frame-Options: DENY\` and \`nosniff\`. Uploaded files are served with their detected type; HTML and SVG
  uploads are served as plain text so they cannot run in the hub's origin.
- Sign-ins, failed sign-ins, key, role, invite and account changes and deletions are written to an audit log that admins can
  read under **Site admin → Audit log**.
- The database file and new data directories are created readable by the hub's user only.
- In Docker the server never runs as root: the container starts as root only to hand over to the owner of
  the data folder (or to the unprivileged \`hub\` user), then drops every privilege before the hub starts.
- An admin created from \`HUB_ADMIN_PASSWORD\` has that password in the environment and in \`.env\`: change it
  after the first sign-in and remove the setting.

## What it does not do

- **No TLS.** The hub speaks plain HTTP; run it behind an HTTPS proxy for anything beyond localhost
  (\`docs/deploy.md\`).
- **No email.** Invite and reset links are shown to the person who creates them, to pass on themselves, and
  email addresses are not verified.
- **No single sign-on or two-factor authentication** yet.
- **Files are protected by sign-in, not by project.** A logged image is addressed by its SHA-256; any signed-in
  account that knows the hash can fetch it. Hashes are only shown to people who can see the run.
- **Run and post names are unique across the whole hub**, so creating one can reveal that the name is taken in a
  project you cannot see.
- Login throttling is kept in memory and resets when the hub restarts.
`,Y=Object.assign({"../../../docs/agents.md":M,"../../../docs/deploy.md":F,"../../../docs/designs.md":W,"../../../docs/getting-started.md":q,"../../../docs/logging.md":G,"../../../docs/security.md":z}),w=[["getting-started","Start here"],["logging","Tracking"],["designs","Designs"],["agents","Agents"],["deploy","Admins"],["security","Admins"]],J=[...new Set(w.map(o=>o[1]))],$=o=>o.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");function V(o,l,d){const s={slug:o,title:o,audience:l,sections:[]};let r={id:"overview",title:"Overview",body:""},i=!1;for(const a of d.split(`
`)){if(a.trimStart().startsWith("```")&&(i=!i),!i&&a.startsWith("# ")){s.title=a.slice(2).trim();continue}if(!i&&a.startsWith("## ")){r.body.trim()&&s.sections.push(r),r={id:$(a.slice(3)),title:a.slice(3).trim(),body:""};continue}r.body+=a+`
`}return r.body.trim()&&s.sections.push(r),s}function Z(){var k,x;const o=R(),l=U(),{guide:d=w[0][0],section:s}=N(),[r,i]=c.useState(""),[a,v]=c.useState(""),A=P("project",""),u=((k=o.projects.find(n=>n.slug===A))==null?void 0:k.slug)??((x=o.projects[0])==null?void 0:x.slug),S=c.useMemo(()=>{const n=t=>{const h=t.replaceAll("https://hub.example.org",window.location.origin).replaceAll("http://localhost:6230",window.location.origin);return u?h.replaceAll("my-project",u):h};return w.map(([t,h])=>V(t,h,n(Y[`../../../docs/${t}.md`]??"")))},[u]),p=r.toLowerCase().split(/\s+/).filter(Boolean),b=S.filter(n=>!a||n.audience===a),m=p.length?b.flatMap(n=>n.sections.filter(t=>p.every(h=>`${n.title} ${t.title} ${t.body}`.toLowerCase().includes(h))).map(t=>({guide:n,section:t}))):[],g=b.find(n=>n.slug===d)??b[0];c.useEffect(()=>{var n;s?(n=document.getElementById(`doc-${s}`))==null||n.scrollIntoView({behavior:"smooth",block:"start"}):window.scrollTo({top:0})},[s,d]);const y=(n,t)=>{i(""),l(`/docs/${n}${t?`/${t}`:""}`)};return e.jsxs("div",{className:"grid gap-6 py-2 lg:grid-cols-[250px_minmax(0,1fr)]",children:[e.jsxs("aside",{className:"space-y-3 lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:self-start lg:overflow-y-auto lg:pr-1",children:[e.jsxs("div",{className:"relative",children:[e.jsx(H,{className:"pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"}),e.jsx(C,{value:r,onChange:n=>{i(n.target.value),window.scrollTo({top:0})},placeholder:"Filter the docs",className:"h-9 pl-8","aria-label":"Filter the docs"})]}),e.jsxs("div",{className:"flex flex-wrap gap-1.5",children:[e.jsx(_,{active:!a,onClick:()=>v(""),children:"All"}),J.map(n=>e.jsx(_,{active:a===n,onClick:()=>v(a===n?"":n),children:n},n))]}),e.jsx("nav",{className:"space-y-1","aria-label":"Guides",children:b.map(n=>{const t=!p.length&&n===g;return e.jsxs("div",{children:[e.jsxs("button",{onClick:()=>y(n.slug),className:f("flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] font-medium hover:bg-muted focus-ring",t?"bg-accent text-accent-foreground hover:bg-accent":"text-foreground"),children:[e.jsx("span",{className:"truncate",children:n.title}),e.jsx("span",{className:"shrink-0 text-[11px] font-normal text-muted-foreground",children:p.length?m.filter(h=>h.guide===n).length||"":n.audience})]}),t&&e.jsx("ul",{className:"mb-2 ml-2.5 mt-1 space-y-0.5 border-l pl-2",children:n.sections.map(h=>e.jsx("li",{children:e.jsx("button",{onClick:()=>y(n.slug,h.id),className:f("block w-full truncate rounded px-2 py-1 text-left text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground focus-ring",s===h.id&&"font-medium text-foreground"),children:h.title})},h.id))})]},n.slug)})}),e.jsxs("p",{className:"border-t pt-3 text-[11.5px] leading-relaxed text-muted-foreground",children:["Commands use this hub's address",u?e.jsxs(e.Fragment,{children:[" and your project ",e.jsx("span",{className:"font-mono text-foreground",children:u})]}):"",", so they can be copied as they are."]})]}),e.jsx("div",{className:"min-w-0 max-w-[860px] space-y-4",children:p.length?e.jsxs(e.Fragment,{children:[e.jsxs("p",{className:"text-[13px] text-muted-foreground",children:[m.length," section",m.length===1?"":"s"," mention ",e.jsx("b",{className:"font-medium text-foreground",children:r.trim()}),a&&` in ${a}`]}),m.map(({guide:n,section:t})=>e.jsx(j,{section:t,label:e.jsx("button",{className:"text-primary hover:underline",onClick:()=>y(n.slug,t.id),children:n.title})},n.slug+t.id)),!m.length&&e.jsx(T,{title:"Nothing matches",children:"Try a shorter word, or clear the audience filter."})]}):g?e.jsxs(e.Fragment,{children:[e.jsxs("div",{children:[e.jsx("div",{className:"label",children:g.audience}),e.jsx("h1",{className:"mt-1 text-[24px] font-semibold tracking-tight",children:g.title})]}),g.sections.map(n=>e.jsx(j,{section:n},n.id))]}):e.jsx(T,{title:"No guide for that audience"})})]})}function j({section:o,label:l}){const d=o.id==="overview"&&!l;return e.jsxs(B,{id:`doc-${o.id}`,className:f("scroll-mt-20 p-5",d&&"border-0 bg-transparent p-0 shadow-none"),children:[!d&&e.jsxs("div",{className:"mb-2 flex flex-wrap items-baseline justify-between gap-2",children:[e.jsx("h2",{className:"text-[16px] font-semibold tracking-tight",children:o.title}),l&&e.jsx("span",{className:"text-[12px]",children:l})]}),e.jsx("div",{className:"prose-hub",children:e.jsx(O,{remarkPlugins:[D],components:{a:({href:s="",children:r})=>{var a;const i=(a=/(?:^|\/)([a-z-]+)\.md$/.exec(s))==null?void 0:a[1];return i?e.jsx(I,{to:`/docs/${i}`,children:r}):/^https?:/.test(s)?e.jsx("a",{href:s,target:"_blank",rel:"noopener",children:r}):e.jsx("span",{children:r})},pre:({children:s})=>e.jsx(K,{children:s})},children:o.body})})]})}function K({children:o}){const l=c.useRef(null),[d,s]=c.useState(!1),r=async()=>{var i;try{await navigator.clipboard.writeText(((i=l.current)==null?void 0:i.innerText)??""),s(!0),setTimeout(()=>s(!1),1500)}catch{}};return e.jsxs("div",{className:"group relative",children:[e.jsx("pre",{ref:l,children:o}),e.jsx("button",{onClick:r,className:"absolute right-2 top-2 rounded-md border bg-card p-1.5 text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 focus-ring","aria-label":"Copy",children:d?e.jsx(E,{className:"h-3.5 w-3.5 text-success"}):e.jsx(L,{className:"h-3.5 w-3.5"})})]})}export{Z as default};
