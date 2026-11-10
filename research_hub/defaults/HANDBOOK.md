# Handbook

This is the live rulebook for this project. Maintainers edit it on the dashboard; members propose changes with
`hub handbook --propose FILE`. Everyone re-reads it when `hub inbox` says it changed.

## 0. This project

(Maintainers: say what the project is for, where the code lives, which datasets matter, and the current priorities.)

## 1. Every session, in this order

1. `hub inbox` — open feedback on your work, replies, @mentions, handbook changes.
2. `hub handbook` — this document. Read it fully the first time and whenever the inbox says it changed.
3. `hub run list` and `hub run table --columns <keys>` — what has been tried and how it did.
4. Answer open feedback before starting new work.

## 2. Runs

A run is anything that trains or evaluates a model. Register it before it starts and close it when it ends.

- **From Python:** `run = hub.init(name=…, config={...}, dataset="name@version")`, then
  `run.log({...}, step=…, epoch=…)`, `run.summary({...})`, `run.finish(conclusion=…)`.
- **From the shell:** `hub run start <slug> --config <committed file> --dataset name@version`, then
  `hub run metric`, `hub run summary`, `hub run finish`.
- Datasets are written `name@version`, comma-separated when there are several.
- `conclusion` says what happened and what to do next. A run with a hypothesis also needs a verdict.
- Status notes go on the run's timeline (`hub run note`), not into comments.

## 3. What to log

- **Metrics** at every evaluation step, with the same keys as comparable runs (`val/…`, `train/…`) so tables and
  comparison charts line up. Pin the keys that matter with `--pinned`.
- **Summary values** at the end (`hub run summary key=value:max`); they fill the runs table.
- **Eval samples** at every evaluation checkpoint: one row per sample with `facts` (anything you want to filter
  by), `true` and `pred`. Classification uses `class`; regression uses `value`; segmentation sends `masks` and
  `heatmaps` as raw 0..1 maps (the dashboard draws them over one stored image); detection sends `boxes` as
  `[x, y, w, h, label, score]`; text tasks send `text`. Never upload overlays you blended yourself.
- **Images** for anything else, with `step`, `epoch`, a stable `sample` id and `role` tracked|failure.

## 4. Working together

- Comment on other people's runs and posts (`hub comment --on run:<slug> --kind question|objection|support`).
  An open objection blocks a supports/refutes verdict until it is answered.
- A person's comment is resolved only with a reference to the answer (`hub resolve <id> --ref run:<slug>`).
- Research posts (`hub post put post.json`) state their basis: literature (cited), observed (linked to runs) or
  hypothesis.
- Claim an idea before working on it for long (`hub claim <idea>`), and say what you start in `#general`.

## 5. Never

- Put credentials in configs, job files, the hub or git.
- Overwrite a dataset version, reuse a run slug, or edit someone else's run.
- Mark a run finished without a conclusion.
