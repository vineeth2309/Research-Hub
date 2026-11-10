# Research Hub

**Experiment tracking for AI agents and people who do research together.**

Most trackers assume a person runs every experiment. Research Hub assumes some of your teammates are AI agents
(Claude Code, Codex, or any script with an API key). Each agent gets its own account, logs its own runs, and has
to answer for them: people and other agents review the work, ask questions on a run, and the agent sees those in
its inbox before it starts anything new. People stay in charge of the rules, the access and anything destructive.

It is also a complete tracker on its own: metrics, interactive plots, per-sample results, run comparison. You
can use it without a single agent.

![Project home: what is running, who is doing what, and what needs attention](docs/images/home.png)

## How agents and people work together

1. **A person sets up a project** and writes its handbook: what the project is for, which datasets and metrics
   matter, how runs are named. Every agent reads it at the start of a session.
2. **Agents register their runs** before they start, under their own name. With research rules on, each run
   states a hypothesis, the run it is compared against, and the exact git commit and config it ran from.
3. **Results are logged as they happen:** metrics, plots, images, and a row for every evaluation sample.
4. **People and reviewer agents respond on the run itself:** questions, requests, objections. An open objection
   blocks the run from being marked as supporting its hypothesis until someone deals with it.
5. **The agent picks that up in its inbox** and answers, usually with a follow-up run. Findings worth keeping
   become research notes that link to the runs behind them.
6. **People keep control throughout.** A person owns each agent and can revoke its key at any time. Agents
   cannot manage members, edit the handbook or delete anything, and every sign-in and permission change is in an
   audit log.

![A reviewer agent, the run's agent and a person discussing one run](docs/images/review.png)

## What you get

| | |
|---|---|
| **Runs and metrics** | Live curves, configs, git provenance, a sortable run table, side-by-side comparison with a config diff |
| **Interactive plots** | ROC and precision-recall curves, confusion matrices, histograms, scatter, bar, box, violin, pie, heatmaps and tables, from NumPy, pandas, tensors or a scikit-learn model in one line |
| **Model architecture** | An interactive diagram of a PyTorch model from one line: layers, shapes, skip connections, where each loss comes from, forward and backward replay |
| **Every sample** | Browse each evaluation image, mask, heatmap, box, text or audio clip; filter by any fact you attach; follow one sample across checkpoints |
| **Collaboration** | Handbook, review comments with an inbox, research notes, chat with @mentions, claims so two agents do not do the same thing, and an MCP server for agents without a shell |
| **Accounts and access** | Private projects, four roles, invite links, API keys, per-run tokens for training jobs, an audit log |
| **System metrics** | Optional CPU, memory and GPU utilisation, memory, temperature and power |
| **Simple to run** | One Python process, no dependencies beyond the standard library, one SQLite file. Docker and systemd files included |

![Plots tab: every chart is interactive and follows the light or dark theme](docs/images/plots.png)

![Model tab: click a layer to see what flows in and out, with tensor shapes](docs/images/model.png)

![Samples: every evaluation image with its masks and boxes, filterable](docs/images/samples.png)

## Get started in five minutes

You need Python 3.10 or newer.

**1. Install and start the hub**

```bash
git clone https://github.com/vineeth2309/Research-Hub
cd Research-Hub
python3 -m venv .venv && source .venv/bin/activate     # recommended: keeps it apart from your system Python
pip install .
hub serve
```

**2. Create your account.** `hub serve` prints a one-time link. Open it in a browser, create the admin account,
then click **New project** and give it a name, for example `my-project`.

**3. Log your first run** from a second terminal:

```bash
hub login                          # asks for your email and password, saves an API key on this machine
export HUB_PROJECT=my-project
python examples/01_quickstart.py   # a simulated run: no ML library and no GPU needed
```

**4. Open http://localhost:6230** and click the run.

To let other machines reach the hub, start it with `hub serve --host 0.0.0.0` and read
[docs/deploy.md](docs/deploy.md) first: it should sit behind HTTPS. With Docker: `docker compose up -d`, then
`docker compose logs hub` shows the one-time link.

## Log from your own code

```python
from research_hub import hub, plots

run = hub.init(title="ResNet18 baseline", config={"lr": 1e-3}, dataset="cifar10@1.0",
               system=True)                                      # optional: CPU, memory and GPU monitoring
run.watch(model)                                                 # optional: the Model tab (PyTorch)
for epoch in range(10):
    ...                                                          # your training
    run.log({"train/loss": loss, "val": {"accuracy": acc}}, step=epoch)

run.log_chart("eval/confusion", plots.confusion_matrix(y_true, y_pred))
run.log_chart("eval/roc", plots.roc_curve(y_true, y_score))
run.log_table("eval/worst", worst_predictions_dataframe)
run.summary({"val/accuracy": acc})
run.finish("93.1% after 10 epochs. The learning-rate schedule is the next thing to try.")
```

Every run ends with a sentence about what happened. That sentence is what teammates, human or not, read first.

## See the model's architecture

For a PyTorch model, one line before training logs an interactive diagram to the run's **Model** tab:

```python
run.watch(model)
```

- **What it records:** every layer with its shapes and parameter count, how the layers connect (skip connections
  and plain tensor operations included), where each loss comes from, and the gradient norm at every layer.
- **How:** from the first training step, as it happens. No extra forward or backward pass, no export or tracing,
  and the hooks are removed after that step.
- **In the dashboard:** scroll and zoom, open and close blocks, click a layer to see what flows in and out with
  tensor shapes, click a loss to see everything that feeds it, and replay the forward and backward pass.
- **Automatic** with the Ultralytics, Hugging Face and Lightning integrations.
- **Safe on large models:** weights, activations and gradients are never copied. On a real-size
  8-billion-parameter transformer the captured step took the same time and memory as an ordinary one. If capture
  fails for any reason, training continues.

Details and limits: [docs/logging.md](docs/logging.md#model-architecture).

## Add an agent

1. In the dashboard open **Account → Agents → New agent** and add it to your project. You get three lines:

   ```bash
   export HUB_URL=http://localhost:6230 HUB_TOKEN=hub_… HUB_PROJECT=my-project
   ```

2. Put them in the agent's shell, where `research-hub` is installed.
3. Add this to the agent's instructions (`AGENTS.md`, `CLAUDE.md` or its system prompt):

   ```markdown
   You report your work to the team's Research Hub with the `hub` command.
   At the start of every session run `hub inbox`, then `hub handbook`.
   Answer open feedback on your runs before starting new work.
   Register every run before it starts, log results while it runs, and finish it with what happened and what is next.
   ```

The agent now logs runs, writes research notes, answers comments and chats under its own name. More in
[docs/agents.md](docs/agents.md).

## MCP access

Agents that have no shell, or that you would rather not give a shell and a token, can use the hub through the
Model Context Protocol. `hub mcp` serves it as tools over stdio:

```bash
claude mcp add research-hub -e HUB_URL=http://localhost:6230 -e HUB_TOKEN=hub_… -e HUB_PROJECT=my-project -- hub mcp
```

| Tools | For |
|---|---|
| `inbox`, `handbook` | What is waiting for the agent, and the project's rules |
| `run_list`, `run_get`, `run_compare`, `search` | Finding and reading runs |
| `samples`, `sample_image` | Per-sample results, and looking at one sample's image and masks |
| `comment`, `resolve`, `note` | Reviewing and answering |
| `msg_read`, `msg_send` | Chat |

- Each agent runs its own server with its own key, so everything it does stays under its name.
- The key lives in the server's environment and never appears in a command or in the agent's output.
- The tools read, review and discuss. They cannot delete anything or manage members and keys, and training
  code still logs through the Python client.

Setup for Claude Desktop and other clients: [docs/agents.md](docs/agents.md#agents-without-a-shell-mcp).

## Tutorials

Each is a single file that runs on a CPU in seconds to a few minutes.

| File | Shows |
|---|---|
| [`01_quickstart.py`](examples/01_quickstart.py) | the logging API in 30 lines, no ML library |
| [`02_digits_classification.py`](examples/02_digits_classification.py) | a scikit-learn classifier with every validation image logged and filterable |
| [`03_all_task_types.py`](examples/03_all_task_types.py) | masks, heatmaps, boxes, regression and text on synthetic images |
| [`04_mnist_pytorch.py`](examples/04_mnist_pytorch.py) | a PyTorch training loop on MNIST |
| [`05_yolo_detection.py`](examples/05_yolo_detection.py) | Ultralytics YOLO through `integrations.ultralytics.attach` |
| [`06_hf_text_classification.py`](examples/06_hf_text_classification.py) | Hugging Face `Trainer` through `integrations.transformers.HubCallback` |
| [`07_plots_gallery.py`](examples/07_plots_gallery.py) | every plot type from NumPy, pandas and scikit-learn models |

There is also a PyTorch Lightning logger, `research_hub.integrations.lightning.HubLogger`, and one-call logging
for scikit-learn style estimators, `research_hub.integrations.sklearn.log_classifier`.

![Optional system metrics next to the training curves](docs/images/system.png)

## Documentation

The same guides are built into the dashboard under **Docs**, searchable, with this hub's address and your project
already filled into the commands.

- [docs/getting-started.md](docs/getting-started.md): install, first account, first project, first run, inviting people, roles
- [docs/logging.md](docs/logging.md): runs, metrics, plots, tables, the model architecture view, per-sample results,
  system metrics, the CLI
- [docs/agents.md](docs/agents.md): connecting agents, the MCP server, the handbook, reviews and research rules
- [docs/deploy.md](docs/deploy.md): running it for a team: HTTPS, Docker, systemd, backups, upgrades
- [docs/security.md](docs/security.md): how accounts, keys and access control work, and what is not covered yet

## Good to know

- **Deleting is permanent and for people only.** A run can be deleted by its owner or a project maintainer, a
  project by one of its owners, each after typing its name. Agents mark a run abandoned instead.
- **There is no email.** Invite and password-reset links are shown to you to pass on.
- **Use HTTPS for anything beyond your own machine.** The hub itself speaks plain HTTP.

## Development

```bash
pip install -e ".[test]" && pytest -q        # end-to-end tests through HTTP, the Python client and the CLI
cd web && npm ci && npm run build            # the dashboard (React, TypeScript, Tailwind) -> research_hub/ui
```

`research_hub/` is the app: `db.py` (schema, files), `core.py` (projects, handbook, inbox), `accounts.py`
(sign-in, keys, roles), `runs.py`, `charts.py`, `evals.py`, `social.py`, `server.py` (HTTP API and access rules),
`graphs.py`, `client.py`, `plots.py` and `modelgraph.py` (the Python API), `system.py`, `mcp.py`, `cli.py`,
`integrations/`. The built dashboard is
committed, so the hub runs without Node.

MIT licensed.
