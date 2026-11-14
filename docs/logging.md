# Logging runs

Everything here works the same for a person's training script and for an AI agent. Set three environment
variables (or run `hub login` once and set only the project):

```bash
export HUB_URL=http://localhost:6230 HUB_TOKEN=hub_… HUB_PROJECT=my-project
```

## Python

```python
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
```

Numbers can be Python floats, numpy scalars or 0-d tensors. If the hub is unreachable, metric and note calls
are saved to `~/.cache/research_hub/spool` and replayed on the next call, so an outage never stops training.

`run.log` is cheap to call on every step: points are sent in batches, at most every two seconds or 500 points,
and always before any other call on the run and when the program exits. `run.flush()` sends them at once. A
rejected batch (for example, logging to a run that has finished) raises at the send, not at `run.log`.

A job that should only be able to write to one run can use that run's **ingest token** instead of your key:

```python
run = hub.init(...)                       # where you launch the job
env = {"HUB_URL": run.hub.url, "HUB_RUN": run.slug, "HUB_TOKEN": run.ingest_token}
# inside the job:
run = hub.init(resume=True)
```

## Plots and tables

Build a chart with `research_hub.plots` and log it. The hub stores the data, not a picture, so the run's
**Plots** tab draws it in the dashboard's theme, shows values on hover, and puts the same chart from several
runs side by side on the compare page.

```python
from research_hub import plots

run.log_chart("eval/roc", plots.roc_curve(y_true, y_score))               # 1-D scores, or 2-D for one curve per class
run.log_chart("eval/confusion", plots.confusion_matrix(y_true, y_pred, normalize="true"))
run.log_chart("sweep", plots.scatter(df, x="lr", y="val_acc", color="optimizer"))   # a DataFrame and column names
run.log_chart("data/lengths", plots.histogram(value=lengths, bins=40))              # or arrays
run.log_table("eval/worst", df.nlargest(50, "loss"))                      # sortable table
run.log_histogram("weights/head", model.head.weight, step=step)           # logged per step: a slider and an over-time view
run.log_figure("custom", matplotlib_figure)                               # anything else, as a static picture
```

Every builder takes lists, NumPy arrays, pandas or polars columns, and torch or TensorFlow tensors. Data is a
DataFrame, a dict of columns or a list of dicts with channels given as column names; or leave it out and pass
arrays. NaN and infinities become gaps. A chart name works like a metric key: `eval/roc` is grouped under
`eval/`. Logging the same name at a new `step` adds a version; without a step it replaces the previous one.

| Kind | Builders |
|---|---|
| General | `line`, `area`, `scatter`, `bar` (grouped, stacked, horizontal, error bars), `pie`, `heatmap`, `table` |
| Distributions | `histogram` (overlaid groups, density, cumulative), `box`, `violin` |
| Classification | `confusion_matrix`, `roc_curve`, `pr_curve`, `calibration`, `threshold_sweep`, `cumulative_gain`, `class_distribution`, `per_class_metrics` |
| Regression | `predicted_vs_actual`, `residuals`, `error_histogram` |
| Models and data | `feature_importance`, `learning_curve`, `embedding` (PCA to two dimensions) |

The general builders need only the standard library; the rest need NumPy. Charts with axes accept `xlabel`,
`ylabel`, `xlog`, `ylog`, `xdomain`, `ydomain` and `refs` (reference lines). A chart holds at most 50,000 rows;
scatter and line charts are thinned to 20,000 points and say so, and histograms are binned before upload, so
the size of your data does not matter. `examples/07_plots_gallery.py` logs one of everything.

For a fitted scikit-learn style estimator (including XGBoost, LightGBM and pipelines), one call logs the lot:

```python
from research_hub.integrations.sklearn import log_classifier, log_regressor
log_classifier(run, model, X_test, y_test)   # confusion matrix, ROC, PR, calibration, per-class scores, importances
log_regressor(run, model, X_test, y_test)    # predicted vs actual, residuals, error distribution
```

## Model architecture

For a PyTorch model, one line logs an interactive diagram of the network to the run's **Model** tab:

```python
run.watch(model)        # once, before training
```

The first training step is recorded as it happens: every layer with its input and output shapes and parameter
count, how the layers connect (including skip connections and plain tensor operations such as `x + y` or
`torch.cat`), which blocks they belong to, where each loss comes from, and the gradient norm at every layer.
Nothing extra is run, no export or tracing is needed, and the hooks are removed after that step.

In the Model tab you can scroll and zoom, open and close blocks, click a layer to see what flows into and out of
it with the tensor shapes, click a loss to see everything that feeds it, and replay the forward and backward
pass. Switch the labels between shapes, gradient norms and activation statistics.

- The Ultralytics, Hugging Face and Lightning integrations call `run.watch` for you; pass `watch=False` to
  `attach(...)` or `HubCallback(...)` to turn it off.
- Loss terms are found automatically when they come from a standard loss or a loss module. To name the terms
  yourself, capture by hand:

  ```python
  from research_hub.modelgraph import Trace

  trace = Trace(model)
  logits, mask = model(trace.input("image", images))
  ce, bce = F.cross_entropy(logits, labels), F.binary_cross_entropy_with_logits(mask, masks)
  run.log_model_graph(trace.backward(ce + 0.5 * bce, {"class loss": ce, "mask loss": bce}))
  ```

- Large models are fine. Weights, activations and gradients are never copied: statistics come from a sample of
  at most 65,536 values per tensor. On a real-size 8-billion-parameter transformer the captured step took the
  same time and memory as an ordinary one (measured on CPU), and a graph with more than 4,000 nodes has its
  deepest blocks folded into single nodes so it still fits.
- Limits: PyTorch only. Code under `torch.no_grad()` shows its layers but not what connects them. Compiled or
  scripted models are not captured. When loss terms are written into one tensor in place, the diagram shows
  them as one "loss computation" block. If anything goes wrong during capture, training continues and a
  one-line warning is printed.

## System metrics

Off by default. Turn on background sampling of the machine with an argument or, without touching the script,
an environment variable:

```python
run = hub.init(..., system=True)                               # CPU, memory, GPU, CPU temperature every 15 s
run = hub.init(..., system=["gpu", "cpu"], system_interval=5)  # pick parts and the interval
```

```bash
HUB_SYSTEM=1 python train.py            # or HUB_SYSTEM=gpu,cpu  and  HUB_SYSTEM_INTERVAL=5
```

| Part | Metrics under `system/` |
|---|---|
| `cpu` | `cpu_percent` |
| `memory` | `memory_percent`, `process_memory_gb` |
| `gpu` | per GPU `gpu0/utilization_percent`, `memory_gb`, `memory_percent`, `temperature_c`, `power_w` |
| `temperature` | `cpu_temperature_c` |

They appear on the Metrics tab in their own groups, with seconds since the run started on the x axis. GPU
readings come from `nvidia-smi` and cover the GPUs in `CUDA_VISIBLE_DEVICES` (all of them when it is unset).
On Linux nothing extra is needed; on macOS and Windows CPU and memory need `psutil`. Parts a machine does not
expose are skipped. Sampling runs in a daemon thread, is never spooled, and stops at `run.finish()`.

## Per-sample results

One row per evaluated sample, at every checkpoint you evaluate. Send what your task produces; the hub derives
an outcome (correct, missed, false alarm, wrong class, mismatch) and the dashboard builds filters, a confusion
matrix and a per-sample timeline from it.

```python
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
```

- Send only the keys your task has. A classifier sends `class`; a detector sends `boxes`.
- `negatives` names the classes that mean "nothing here" (default: negative, background, normal, none, ok, good,
  healthy). Predicting one of them for a positive sample is a *miss*; the reverse is a *false alarm*.
- Boxes are `[x, y, width, height]` from the top-left corner, in pixels of the image you pass (or all four as
  fractions of it, 0 to 1). The image is stored smaller, so the client sends its real size along as `size` and the
  hub keeps the boxes as fractions of it; do not rescale them yourself. Send `true.boxes` and `pred.boxes` in the
  same row. If you post rows over the API with an image you uploaded yourself, send `"size": [width, height]`.
- Images are stored as WebP (longest side 512 px), prediction maps as 8-bit PNG (192 px), ground-truth masks as
  1-bit PNG. Uploads are content-addressed: an image sent again costs nothing.
- Logging the same sample at a later step adds a checkpoint to its timeline. Logging it again at the same step
  overwrites only the fields you send.
- To take something back, log the row again with a null (`None`) for that mask, heatmap or fact, and `[]` for
  `boxes`. Nothing is removed just because a later log leaves it out.
- Give every predicted box its confidence and log boxes well below your operating threshold. The viewer has a
  minimum score for all boxes and one per class, so a reader can move the cut-off. With low-confidence boxes in
  the row, send `outcome` yourself; the derived one counts every box.
- Do not draw masks, boxes or captions into the image yourself. Send them as data and the viewer overlays them.

From a file: `hub run eval <run> results.jsonl --set pets@2.0:val --step 1000` (one JSON row per line; paths
are relative to the file).

### One eval set across runs

When several runs log the same eval set with the same sample ids, **Datasets** in the sidebar shows the set
itself: one tile per sample with a cell for every chosen run, coloured by its outcome. Each run is read at its
last logged checkpoint.

- Presets find the samples most runs get wrong, the ones every run gets wrong, the ones that split the runs, and
  the ones only one run gets wrong or right. Filters are the true class and every fact of the set.
- A sample's page lists every run's predicted class, score and outcome, and draws the masks or boxes of the run
  you pick.
- Runs named `<arm>-s<seed>…` are shown together as seeds of one arm. A selection of runs can be saved under a
  name; it is kept in your browser.
- Samples without truth work too: the runs are compared by the class they predict, and you can filter on how
  many runs predict a class ("at most 3 runs say normal").
- The mean and spread shown per sample are of one number in `pred`; when the rows carry several, you choose.
- **A fact belongs to the sample and is shared by every run on the set; the first run to log it wins.** Put
  anything that differs from run to run in `pred`, `metrics` or `outcome`, not in `facts`.
- A finished run still takes rows logged with your own key, so a corrected outcome can be logged later with
  `hub run eval` or `research_hub.client.log_eval`.
- Each run shows when its results were last logged, in the run picker and the sample table; a correction on a
  closed run updates it. Adding a sample, or adding or removing a fact, makes the set's sample list rebuild on the
  next request (a few seconds on a large set), so keep facts stable and put per-run values in `pred` or `metrics`.

The same data over the API, for building hard-case sets:

```
GET /api/eval-sets                                   # every eval set and the runs that logged it
GET /api/eval-sets/samples?set=…&runs=a,b,c          # a page of samples with every run's call
    &preset=most_wrong|all_wrong|split|all_right|one_wrong|one_right  &run=<the one run>
    &class_true=…  &fact.<key>=v1,v2  &q=text  &pred_class=…&pred_min=…&pred_max=…
    &sort=wrong|disagree|value|spread|score|pred|sample  &value=<number in pred>  &limit=…&offset=…
    &compact=1                                       # aggregates only, up to 200,000 rows
GET /api/eval-sets/summary?set=…&runs=…&by=<fact>    # counts per preset and filter value, run × run agreement
```

A call is `[outcome, predicted class, number, score]`, in the order of `runs` in the reply.

## Command line

```bash
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
```

`hub --help` lists everything; `--project <slug>` overrides `HUB_PROJECT`; `--as <name>` picks one of several
saved identities.

## Framework integrations

```python
from research_hub.integrations.ultralytics import attach          # run = attach(model, title=…); model.train(…)
from research_hub.integrations.transformers import HubCallback    # Trainer(callbacks=[HubCallback(title=…)])
from research_hub.integrations.lightning import HubLogger         # Trainer(logger=HubLogger(title=…))
from research_hub.integrations.sklearn import log_classifier      # log_classifier(run, model, X_test, y_test)
```

The first three take the same arguments as `hub.init`, log metrics and the training configuration, and leave
`run.finish("…")` to you, because a conclusion is something only you can write.
