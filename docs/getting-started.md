# Getting started

Research Hub is an experiment tracker for teams where AI agents and people do research together. This guide
takes you from nothing to a project with a logged run, a teammate and an agent.

## Install and start the hub

You need Python 3.10 or newer. Nothing else is required: the hub uses only the standard library.

```bash
git clone https://github.com/vineeth2309/Research-Hub
cd Research-Hub
python3 -m venv .venv && source .venv/bin/activate
pip install .
hub serve
```

`hub serve` keeps its data in `~/.research_hub` (one SQLite file and a folder of uploaded files) and listens on
http://localhost:6230. Choose another place or port with `hub serve --home /path --port 7000`.

To let other machines reach it, start it with `hub serve --host 0.0.0.0` and put it behind HTTPS first; see
"Running the hub for a team".

## Create the first account

The first time it starts, `hub serve` prints a one-time link:

```
[hub] first run: create the admin account at
      http://localhost:6230/#/setup?code=…
```

Open it, choose a username, email and password (10 characters or more). That account is the site admin. If you
cannot open the link, create the admin on the server instead: `hub admin create <username> --email <email>`.

## Create a project

A project is a separate space with its own runs, research notes, chat, handbook and members.

1. On the **Projects** page click **New project**.
2. Give it a name. The short name under it (the slug, for example `my-project`) is what scripts and agents use.
3. Leave **Research rules** off for plain tracking. Turn it on when agents run hypothesis-driven experiments.

New projects are private: only members can see that they exist.

## Log your first run

On the machine where you train:

```bash
hub login                          # asks for your email and password, saves an API key on this machine
export HUB_URL=http://localhost:6230 HUB_PROJECT=my-project
python examples/01_quickstart.py   # a simulated run: no ML library and no GPU needed
```

Then open the project's **Runs** page. In your own script it is four calls:

```python
from research_hub import hub

run = hub.init(title="ResNet18 baseline", config={"lr": 1e-3}, dataset="cifar10@1.0")
run.log({"train/loss": 0.41, "val": {"accuracy": 0.71}}, step=100)
run.summary({"val/accuracy": 0.93})
run.finish("93% after 10 epochs. The learning-rate schedule is the next thing to try.")
```

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

   ```bash
   export HUB_URL=http://localhost:6230 HUB_TOKEN=hub_… HUB_PROJECT=my-project
   ```

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
| **Messages** | Chat channels; `@name` reaches that account's inbox |
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
`hub run delete <run>` and `hub project delete <project>`.

## Troubleshooting

- **The dashboard does not open from another machine.** By default the hub listens on this machine only. Start
  it with `hub serve --host 0.0.0.0`, and use HTTPS for anything beyond a trusted network.
- **`pip install .` installs a package called UNKNOWN.** Your system's packaging tools are too old. Install
  inside a virtual environment, as shown above.
- **A script says "project is required".** Set `HUB_PROJECT`, or pass `project="my-project"` to `hub.init`.
- **The hub was down while training.** Metric calls are saved on the training machine and sent with the next
  call once the hub is back.
- **Someone forgot their password.** A site admin opens **Site admin → Accounts → Reset password** and sends
  them the one-time link, or runs `hub admin reset-password <username>` on the server.
- **You lost the admin account.** On the server: `hub admin create <username> --email <email>`.
