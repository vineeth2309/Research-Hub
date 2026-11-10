"""Chart builders. Each returns a chart for ``run.log_chart(name, chart, step=None)``.

    from research_hub import hub, plots
    run.log_chart("eval/roc", plots.roc_curve(y_true, y_score))
    run.log_chart("eval/confusion", plots.confusion_matrix(y_true, y_pred))
    run.log_chart("data/lengths", plots.histogram(value=lengths, bins=40))
    run.log_chart("sweep", plots.scatter(df, x="lr", y="val_acc", color="optimizer"))

Data is a pandas or polars DataFrame, a dict of columns, or a list of dicts, with channels given as column
names; or leave ``data`` out and pass arrays (lists, numpy, pandas Series, torch or TensorFlow tensors) directly.
The general charts need only the standard library; the statistical ones (histogram, box, violin and everything
under "Machine learning") need numpy.

Options shared by the charts with axes, all optional: ``xlabel``, ``ylabel``, ``xlog``, ``ylog``, ``xdomain``,
``ydomain`` ([low, high]) and ``refs``, a list of reference lines: {"x": 0.5}, {"y": 0} or {"diagonal": True}.
"""

from __future__ import annotations

import math
import random

MAX_POINTS = 20_000   # scatter and line charts are thinned to this many rows
CURVE_POINTS = 300    # points kept per ROC / precision-recall curve


# ----------------------------------------------------------------- any array -> columns
def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        raise RuntimeError("this chart needs numpy (pip install numpy)") from None


def _cell(v):
    if v is None or isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (list, tuple, dict)):
        raise TypeError("a chart column must be one-dimensional")
    if hasattr(v, "item"):  # numpy scalars, 0-d tensors
        return _cell(v.item())
    if type(v).__name__ in ("NAType", "NaTType"):
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def column(values) -> list:
    """Any one-dimensional array-like as a list of JSON values; NaN and infinities become null."""
    if hasattr(values, "detach"):  # torch
        values = values.detach().cpu()
    if hasattr(values, "to_numpy"):  # pandas, polars
        values = values.to_numpy()
    elif hasattr(values, "numpy"):  # tensors
        values = values.numpy()
    if getattr(getattr(values, "dtype", None), "kind", None) in ("M", "m"):  # numpy dates and durations
        values = values.astype(str)
    if hasattr(values, "tolist"):
        values = values.tolist()
    return [_cell(v) for v in values]


def frame(data, columns=None) -> dict:
    """A table as {column: list}, from a DataFrame, a dict of arrays, a list of dicts or a 2-D array."""
    if isinstance(data, dict):
        out = {str(k): column(v) for k, v in data.items()}
    elif hasattr(data, "columns"):  # pandas, polars
        out = {str(c): column(data[c]) for c in data.columns}
    elif len(data) and isinstance(data[0], dict):
        keys = list(dict.fromkeys(k for row in data for k in row))
        out = {str(k): column([row.get(k) for row in data]) for k in keys}
    else:
        table = [column(row) for row in data]
        names = columns or [str(i) for i in range(len(table[0]) if table else 0)]
        return {str(name): [row[i] for row in table] for i, name in enumerate(names)}
    return {c: out[c] for c in columns} if columns else out


def _pick(data, value):
    """A channel given as a column name of ``data`` or as an array: (values, name or None)."""
    if not isinstance(value, str):
        return column(value), None
    if data is None:
        raise KeyError(f"{value!r} names a column, but no data was given; pass an array or data=")
    if isinstance(data, dict) or hasattr(data, "columns"):
        if value not in data:
            raise KeyError(f"{value!r} is not a column of the data")
        return column(data[value]), value
    if not any(value in row for row in data):
        raise KeyError(f"{value!r} is not a key of the rows")
    return column([row.get(value) for row in data]), value


def _thin(columns: dict, how: str) -> int | None:
    """Cut the columns to MAX_POINTS rows in place; returns the original row count if rows were dropped."""
    n = len(next(iter(columns.values()), []))
    if n <= MAX_POINTS:
        return None
    keep = (sorted(random.Random(0).sample(range(n), MAX_POINTS)) if how == "random"
            else [i * n // MAX_POINTS for i in range(MAX_POINTS)])
    for name, values in columns.items():
        columns[name] = [values[i] for i in keep]
    return n


def _chart(kind, data, channels: dict, title, options: dict, thin=None) -> dict:
    columns, encoding = {}, {}
    for channel, value in channels.items():
        if value is None:
            continue
        values, name = _pick(data, value)
        columns[name or channel] = values
        encoding[channel] = name or channel
    if len({len(v) for v in columns.values()}) > 1:
        raise ValueError(f"{kind} chart: the columns have different lengths "
                         f"({ {k: len(v) for k, v in columns.items()} })")
    if thin:
        options = {**options, "sampled_from": _thin(columns, thin)}
    return {"kind": kind, "title": title, "data": {"columns": columns}, "encoding": encoding,
            "options": {k: v for k, v in options.items() if v is not None and v is not False}}


def _series(data, x, y) -> dict | None:
    """Several y series as long-form columns (x, value, series); None when ``y`` is a single series."""
    if isinstance(y, dict):
        series = {str(k): column(v) for k, v in y.items()}
    elif isinstance(y, (list, tuple)) and y and all(isinstance(k, str) for k in y) and data is not None:
        series = {k: _pick(data, k)[0] for k in y}
    else:
        return None
    xs = _pick(data, x)[0] if x is not None else None
    out: dict = {"x": [], "value": [], "series": []}
    for name, values in series.items():
        out["x"] += xs if xs is not None else list(range(len(values)))
        out["value"] += values
        out["series"] += [name] * len(values)
    return out


# ------------------------------------------------------------------- general charts
def line(data=None, *, x=None, y, color=None, low=None, high=None, title="", points=False, curve=None, **options) -> dict:
    """Lines over x. ``y`` is one series, or several: a list of column names, or {name: array}.

    ``color`` splits one y into a line per value. ``low``/``high`` draw a band around the line.
    ``curve`` is "step", "step-after", "step-before" or "smooth". Without ``x`` the row index is used.
    """
    return _xy("line", data, x, y, color, low, high, title, {**options, "points": points, "curve": curve})


def area(data=None, *, x=None, y, color=None, title="", stack=False, curve=None, **options) -> dict:
    """Filled areas over x; ``stack=True`` piles the series on top of each other."""
    return _xy("area", data, x, y, color, None, None, title, {**options, "stack": stack, "curve": curve})


def _xy(kind, data, x, y, color, low, high, title, options) -> dict:
    melted = _series(data, x, y)
    if melted:
        options = {"xlabel": x if isinstance(x, str) else ("index" if x is None else None), **options}
        return _chart(kind, melted, {"x": "x", "y": "value", "color": "series"}, title, options, thin="even")
    if x is None:
        x = list(range(len(_pick(data, y)[0])))
        options = {"xlabel": "index", **options}
    return _chart(kind, data, {"x": x, "y": y, "color": color, "low": low, "high": high}, title, options, thin="even")


def scatter(data=None, *, x, y, color=None, size=None, text=None, title="", **options) -> dict:
    """Points. ``color`` is a category or a number, ``size`` a number, ``text`` a label shown on hover."""
    return _chart("scatter", data, {"x": x, "y": y, "color": color, "size": size, "text": text}, title, options,
                  thin="random")


def bar(data=None, *, x, y, color=None, low=None, high=None, title="", stack=False, horizontal=False, sort=None,
        **options) -> dict:
    """Bars: ``x`` is the category, ``y`` the value. ``color`` groups bars side by side, or stacks with ``stack``.

    ``low``/``high`` draw error bars. ``sort`` is "asc" or "desc" by value (without ``color``).
    """
    chart = _chart("bar", data, {"x": x, "y": y, "color": color, "low": low, "high": high}, title,
                   {**options, "stack": stack, "horizontal": horizontal})
    cols, enc = chart["data"]["columns"], chart["encoding"]
    if sort and not color:
        pairs = sorted(zip(cols[enc["y"]], cols[enc["x"]]), key=lambda p: (p[0] is None, p[0] or 0), reverse=sort == "desc")
        chart["options"]["xorder"] = [str(name) for _, name in pairs]
    return chart


def pie(data=None, *, label, value, title="") -> dict:
    """Shares of a whole. Use a bar chart instead when there are more than about eight slices."""
    return _chart("pie", data, {"label": label, "value": value}, title, {})


def heatmap(data=None, *, x=None, y=None, value=None, matrix=None, x_labels=None, y_labels=None, title="",
            annotate=None, diverging=False, **options) -> dict:
    """A grid of coloured cells, from long-form x / y / value or from a 2-D ``matrix`` (rows are y).

    ``annotate`` prints the value in each cell (default: when there are at most 400 cells).
    ``diverging`` centres the colours on zero, for correlations and differences.
    """
    if matrix is not None:
        grid = [column(row) for row in matrix]
        ys = [str(v) for v in (y_labels if y_labels is not None else range(len(grid)))]
        xs = [str(v) for v in (x_labels if x_labels is not None else range(len(grid[0])))]
        data = {"x": [c for _ in ys for c in xs], "y": [r for r in ys for _ in xs], "value": [v for row in grid for v in row]}
        x, y, value = "x", "y", "value"
        options = {"xorder": xs, "yorder": ys, "xlabel": "", "ylabel": "", **options}
    return _chart("heatmap", data, {"x": x, "y": y, "value": value}, title,
                  {**options, "annotate": annotate, "diverging": diverging})


def table(data, columns=None, title="") -> dict:
    """A sortable table. ``columns`` picks and orders columns (or names those of a 2-D array)."""
    return {"kind": "table", "title": title, "data": {"columns": frame(data, columns)}, "encoding": {}, "options": {}}


# -------------------------------------------------------------- distributions (numpy)
def _numbers(np, values):
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def _groups(np, data, value, by):
    """Finite values split by group: ([(group name, array)], name of the value column or None)."""
    values, name = _pick(data, value)
    arr = _numbers(np, values)
    keep = np.isfinite(arr)
    if not keep.any():
        raise ValueError("no finite values to plot")
    if by is None:
        return [("", arr[keep])], name
    labels = np.array([str(v) for v in _pick(data, by)[0]])
    if len(labels) != len(arr):
        raise ValueError("value and by have different lengths")
    return [(g, arr[keep & (labels == g)]) for g in dict.fromkeys(labels.tolist())], name


def histogram(data=None, *, value, by=None, bins=30, range=None, density=False, cumulative=False, title="",
              **options) -> dict:
    """Distribution of ``value``, binned here so any amount of data is cheap to send.

    ``by`` overlays one histogram per group on shared bins. ``bins`` is a count or explicit edges.
    ``density`` normalises each group to area 1; ``cumulative`` accumulates left to right.
    """
    np = _np()
    groups, name = _groups(np, data, value, by)
    everything = np.concatenate([v for _, v in groups])
    edges = np.histogram_bin_edges(everything, bins=bins, range=range)
    cols: dict = {"low": [], "high": [], "count": [], "group": []}
    for group, values in groups:
        counts = np.histogram(values, bins=edges)[0].astype(float)
        if density and counts.sum():
            counts = counts / counts.sum() if cumulative else counts / (counts.sum() * np.diff(edges))
        if cumulative:
            counts = np.cumsum(counts)
        cols["low"] += edges[:-1].tolist()
        cols["high"] += edges[1:].tolist()
        cols["count"] += counts.tolist()
        cols["group"] += [group] * len(counts)
    y = ("cumulative share" if density else "cumulative count") if cumulative else ("density" if density else "count")
    return _chart("histogram", cols, {"low": "low", "high": "high", "value": "count", "color": "group" if by is not None else None},
                  title, {"xlabel": name, "ylabel": y, **options})


def box(data=None, *, value, by=None, title="", horizontal=False, **options) -> dict:
    """Box plots: median, quartiles, whiskers at 1.5 IQR and the points beyond them, one box per ``by`` group."""
    np = _np()
    groups, name = _groups(np, data, value, by)
    keys = ("group", "low", "q1", "median", "q3", "high", "outlier", "n")
    cols: dict = {k: [] for k in keys}
    for group, values in groups:
        if not len(values):
            continue
        q1, median, q3 = np.percentile(values, [25, 50, 75]).tolist()
        reach = 1.5 * (q3 - q1)
        inside = values[(values >= q1 - reach) & (values <= q3 + reach)]
        outside = values[(values < q1 - reach) | (values > q3 + reach)]
        outside = outside[np.argsort(-np.abs(outside - median))][:200]  # the 200 most extreme
        for row in [(group, float(inside.min()), q1, median, q3, float(inside.max()), None, len(values))] + \
                   [(group, None, None, None, None, None, v, None) for v in outside.tolist()]:
            for k, v in zip(keys, row):
                cols[k].append(v)
    encoding = {k: k for k in keys if k != "n"}
    return _chart("box", cols, encoding, title, {"ylabel": name, "horizontal": horizontal, **options})


def violin(data=None, *, value, by=None, title="", **options) -> dict:
    """Violin plots: the smoothed shape of the distribution of ``value``, one per ``by`` group."""
    np = _np()
    groups, name = _groups(np, data, value, by)
    cols: dict = {"group": [], "y": [], "density": []}
    rng = np.random.default_rng(0)
    for group, values in groups:
        if not len(values):
            continue
        if len(values) > 5000:
            values = rng.choice(values, 5000, replace=False)
        spread = float(values.std()) or float(abs(values.mean())) * 1e-3 or 1.0
        width = 1.06 * spread * len(values) ** -0.2  # Silverman's rule
        grid = np.linspace(values.min() - width, values.max() + width, 80)
        dens = np.exp(-0.5 * ((grid[:, None] - values[None, :]) / width) ** 2).sum(axis=1)
        cols["group"] += [group] * len(grid)
        cols["y"] += grid.tolist()
        cols["density"] += (dens / dens.max()).tolist()
    return _chart("violin", cols, {"group": "group", "y": "y", "density": "density"}, title, {"ylabel": name, **options})


# ------------------------------------------------------------------ machine learning
def _strings(values) -> list[str]:
    return [str(v) for v in column(values)]


def _class_names(labels, *observed) -> list[str]:
    if labels is not None:
        return [str(v) for v in column(labels)]
    seen = {v for values in observed for v in values}
    try:  # 2, 10 rather than "10", "2"
        return sorted(seen, key=float)
    except ValueError:
        return sorted(seen)


def _matrix(np, values):
    if hasattr(values, "detach"):
        values = values.detach().cpu()
    if hasattr(values, "to_numpy"):
        values = values.to_numpy()
    return np.asarray(values, dtype=float)


def _counts(np, y_true, y_pred, labels):
    true, pred = _strings(y_true), _strings(y_pred)
    if len(true) != len(pred):
        raise ValueError("y_true and y_pred have different lengths")
    names = _class_names(labels, true, pred)
    index = {name: i for i, name in enumerate(names)}
    counts = np.zeros((len(names), len(names)))
    for t, p in zip(true, pred):
        if t in index and p in index:
            counts[index[t], index[p]] += 1
    return counts, names


def confusion_matrix(y_true=None, y_pred=None, *, labels=None, matrix=None, normalize=None,
                     title="Confusion matrix") -> dict:
    """Actual against predicted class, from labels or from a ready ``matrix`` (rows actual, columns predicted).

    ``normalize`` is "true" (each row sums to 1: recall on the diagonal), "pred" (columns: precision) or "all".
    """
    np = _np()
    if matrix is None:
        counts, names = _counts(np, y_true, y_pred, labels)
    else:
        counts = _matrix(np, matrix)
        names = [str(v) for v in (column(labels) if labels is not None else range(len(counts)))]
    cols = {"actual": [a for a in names for _ in names], "predicted": [p for _ in names for p in names],
            "count": counts.ravel().tolist()}
    value = "count"
    if normalize:
        total = {"true": counts.sum(axis=1, keepdims=True), "pred": counts.sum(axis=0, keepdims=True),
                 "all": counts.sum()}[normalize]
        cols["share"] = np.nan_to_num(counts / np.where(total == 0, 1, total)).ravel().tolist()
        value = "share"
    return _chart("heatmap", cols, {"x": "predicted", "y": "actual", "value": value}, title,
                  {"xorder": names, "yorder": names, "annotate": True, "percent": bool(normalize)})


def _binary_tasks(np, y_true, y_score, labels, positive):
    """One (class name, is-positive array, score array) per curve: one for 1-D scores, one per class for 2-D."""
    true = np.array(_strings(y_true))
    scores = _matrix(np, y_score)
    if scores.ndim == 2 and scores.shape[1] == 1:
        scores = scores[:, 0]
    if len(true) != len(scores):
        raise ValueError("y_true and y_score have different lengths")
    names = _class_names(labels, true.tolist())
    if scores.ndim == 1:
        target = str(positive) if positive is not None else names[-1]
        tasks = [(target, true == target, scores)]
    else:
        if scores.shape[1] != len(names):
            raise ValueError(f"y_score has {scores.shape[1]} columns but there are {len(names)} classes; pass labels=")
        tasks = [(name, true == name, scores[:, j]) for j, name in enumerate(names)]
    tasks = [(n, t, s) for n, t, s in tasks if 0 < t.sum() < len(t)]
    if not tasks:
        raise ValueError("every class is either always or never present; nothing to plot")
    return tasks


def _cumulative(np, positive, scores):
    """True and false positive counts at every distinct score, highest first."""
    order = np.argsort(-scores, kind="stable")
    positive, scores = positive[order], scores[order]
    ends = np.r_[np.flatnonzero(np.diff(scores)), len(scores) - 1]
    tp = np.cumsum(positive)[ends].astype(float)
    return tp, (ends + 1) - tp, scores[ends]


def _keep(np, n):
    return np.unique(np.linspace(0, n - 1, min(n, CURVE_POINTS)).astype(int))


def roc_curve(y_true, y_score, *, labels=None, positive=None, title="ROC curve") -> dict:
    """ROC with the area under each curve.

    ``y_score`` is 1-D (score of the ``positive`` class, by default the last label) or 2-D (one column per class,
    drawn one-vs-rest).
    """
    np = _np()
    cols: dict = {"fpr": [], "tpr": [], "threshold": [], "class": []}
    for name, positive_, scores in _binary_tasks(np, y_true, y_score, labels, positive):
        tp, fp, thresholds = _cumulative(np, positive_, scores)
        tpr, fpr = np.r_[0, tp / tp[-1]], np.r_[0, fp / fp[-1]]
        auc = float(np.sum(np.diff(fpr) * (tpr[1:] + tpr[:-1]) / 2))
        keep = _keep(np, len(fpr))
        cols["fpr"] += fpr[keep].tolist()
        cols["tpr"] += tpr[keep].tolist()
        cols["threshold"] += [None if i == 0 else float(thresholds[i - 1]) for i in keep]
        cols["class"] += [f"{name} (AUC {auc:.3f})"] * len(keep)
    return _chart("line", cols, {"x": "fpr", "y": "tpr", "color": "class", "text": "threshold"}, title,
                  {"xlabel": "False positive rate", "ylabel": "True positive rate", "xdomain": [0, 1], "ydomain": [0, 1],
                   "refs": [{"diagonal": True}], "square": True})


def pr_curve(y_true, y_score, *, labels=None, positive=None, title="Precision-recall curve") -> dict:
    """Precision against recall with the average precision of each curve; ``y_score`` as in ``roc_curve``."""
    np = _np()
    cols: dict = {"recall": [], "precision": [], "threshold": [], "class": []}
    for name, positive_, scores in _binary_tasks(np, y_true, y_score, labels, positive):
        tp, fp, thresholds = _cumulative(np, positive_, scores)
        precision, recall = tp / (tp + fp), tp / tp[-1]
        ap = float(np.sum(np.diff(np.r_[0, recall]) * precision))
        keep = _keep(np, len(recall))
        cols["recall"] += [0.0] + recall[keep].tolist()
        cols["precision"] += [float(precision[0])] + precision[keep].tolist()
        cols["threshold"] += [None] + thresholds[keep].tolist()
        cols["class"] += [f"{name} (AP {ap:.3f})"] * (len(keep) + 1)
    return _chart("line", cols, {"x": "recall", "y": "precision", "color": "class", "text": "threshold"}, title,
                  {"xlabel": "Recall", "ylabel": "Precision", "xdomain": [0, 1], "ydomain": [0, 1], "curve": "step-before",
                   "square": True})


def calibration(y_true, y_prob, *, bins=10, labels=None, positive=None, title=None) -> dict:
    """Reliability diagram for one class: predicted probability against how often it was right, per bin.

    The default title carries the expected calibration error (ECE).
    """
    np = _np()
    _, hit, prob = _binary_tasks(np, y_true, y_prob, labels, positive)[0]
    which = np.minimum((prob * bins).astype(int), bins - 1)
    cols: dict = {"predicted": [], "observed": [], "samples": []}
    ece = 0.0
    for b in range(bins):
        inside = which == b
        if inside.any():
            mean, rate, n = float(prob[inside].mean()), float(hit[inside].mean()), int(inside.sum())
            ece += abs(mean - rate) * n / len(prob)
            cols["predicted"].append(mean)
            cols["observed"].append(rate)
            cols["samples"].append(n)
    return _chart("line", cols, {"x": "predicted", "y": "observed"}, title or f"Calibration (ECE {ece:.3f})",
                  {"xlabel": "Mean predicted probability", "ylabel": "Fraction positive", "xdomain": [0, 1],
                   "ydomain": [0, 1], "refs": [{"diagonal": True}], "points": True, "square": True})


def threshold_sweep(y_true, y_score, *, labels=None, positive=None, title="Precision, recall and F1 by threshold") -> dict:
    """Precision, recall and F1 of one class at 101 thresholds across the score range."""
    np = _np()
    _, hit, scores = _binary_tasks(np, y_true, y_score, labels, positive)[0]
    thresholds = np.linspace(scores.min(), scores.max(), 101)
    order = np.sort(scores)
    hits = np.sort(scores[hit])
    flagged = len(order) - np.searchsorted(order, thresholds, side="left")
    tp = len(hits) - np.searchsorted(hits, thresholds, side="left")
    precision = np.where(flagged > 0, tp / np.maximum(flagged, 1), 1.0)
    recall = tp / len(hits)
    f1 = np.where(precision + recall > 0, 2 * precision * recall / np.maximum(precision + recall, 1e-12), 0.0)
    return line(x=thresholds, y={"precision": precision, "recall": recall, "F1": f1}, title=title, xlabel="Threshold",
                ylabel="", ydomain=[0, 1])


def cumulative_gain(y_true, y_score, *, labels=None, positive=None, title="Cumulative gain") -> dict:
    """Share of the positives found against the share of samples reviewed, highest score first."""
    np = _np()
    _, hit, scores = _binary_tasks(np, y_true, y_score, labels, positive)[0]
    found = np.r_[0, np.cumsum(hit[np.argsort(-scores, kind="stable")]) / hit.sum()]
    keep = _keep(np, len(found))
    return _chart("line", {"reviewed": (keep / (len(found) - 1)).tolist(), "found": found[keep].tolist()},
                  {"x": "reviewed", "y": "found"}, title,
                  {"xlabel": "Share of samples reviewed", "ylabel": "Share of positives found", "xdomain": [0, 1],
                   "ydomain": [0, 1], "refs": [{"diagonal": True}], "square": True})


def class_distribution(y_true, y_pred=None, *, labels=None, title="Class distribution") -> dict:
    """Samples per class; with ``y_pred``, actual and predicted counts side by side."""
    sides = {"actual": _strings(y_true), **({"predicted": _strings(y_pred)} if y_pred is not None else {})}
    names = _class_names(labels, *sides.values())
    cols = {"class": [n for _ in sides for n in names],
            "samples": [values.count(n) for values in sides.values() for n in names],
            "side": [side for side in sides for _ in names]}
    return _chart("bar", cols, {"x": "class", "y": "samples", "color": "side" if y_pred is not None else None}, title,
                  {"xorder": names})


def per_class_metrics(y_true, y_pred, *, labels=None, title="Precision, recall and F1 by class") -> dict:
    """Precision, recall and F1 of each class as grouped bars."""
    np = _np()
    counts, names = _counts(np, y_true, y_pred, labels)
    tp = np.diag(counts)
    precision = tp / np.maximum(counts.sum(axis=0), 1)
    recall = tp / np.maximum(counts.sum(axis=1), 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    cols = {"class": names * 3, "score": np.r_[precision, recall, f1].tolist(),
            "metric": [m for m in ("precision", "recall", "F1") for _ in names]}
    return _chart("bar", cols, {"x": "class", "y": "score", "color": "metric"}, title, {"xorder": names, "ydomain": [0, 1]})


def predicted_vs_actual(y_true, y_pred, *, title="Predicted against actual") -> dict:
    """Regression: each sample's prediction against its true value, with the perfect-prediction diagonal."""
    return _chart("scatter", None, {"x": y_true, "y": y_pred}, title,
                  {"xlabel": "Actual", "ylabel": "Predicted", "refs": [{"diagonal": True}]}, thin="random")


def residuals(y_true, y_pred, *, title="Residuals") -> dict:
    """Regression: prediction error against the prediction; structure here means the model is missing something."""
    np = _np()
    true, pred = _numbers(np, column(y_true)), _numbers(np, column(y_pred))
    return _chart("scatter", None, {"x": pred, "y": pred - true}, title,
                  {"xlabel": "Predicted", "ylabel": "Predicted − actual", "refs": [{"y": 0}]}, thin="random")


def error_histogram(y_true, y_pred, *, bins=40, title="Prediction error") -> dict:
    """Regression: distribution of predicted minus actual."""
    np = _np()
    return histogram(value=_numbers(np, column(y_pred)) - _numbers(np, column(y_true)), bins=bins, title=title,
                     xlabel="Predicted − actual", refs=[{"x": 0}])


def feature_importance(names, values, *, top=15, title="Feature importance") -> dict:
    """The ``top`` features by absolute importance, largest first, as horizontal bars."""
    pairs = sorted(zip(column(values), (str(n) for n in column(names))), key=lambda p: -abs(p[0] or 0))[:top]
    return _chart("bar", {"feature": [n for _, n in pairs], "importance": [v for v, _ in pairs]},
                  {"x": "feature", "y": "importance"}, title, {"horizontal": True, "xorder": [n for _, n in pairs]})


def learning_curve(sizes, train_scores, validation_scores, *, title="Learning curve", ylabel="Score") -> dict:
    """Score against training-set size. Scores are 1-D, or 2-D (sizes x folds) for a mean line with a ±1 std band."""
    np = _np()
    cols: dict = {"size": [], "score": [], "low": [], "high": [], "split": []}
    for split, scores in (("train", train_scores), ("validation", validation_scores)):
        scores = _matrix(np, scores)
        scores = scores[:, None] if scores.ndim == 1 else scores
        mean, std = scores.mean(axis=1), scores.std(axis=1)
        cols["size"] += column(sizes)
        cols["score"] += mean.tolist()
        cols["low"] += (mean - std).tolist()
        cols["high"] += (mean + std).tolist()
        cols["split"] += [split] * len(mean)
    return _chart("line", cols, {"x": "size", "y": "score", "color": "split", "low": "low", "high": "high"}, title,
                  {"xlabel": "Training samples", "ylabel": ylabel, "points": True})


def embedding(points, *, labels=None, text=None, title="Embedding") -> dict:
    """Vectors as a 2-D scatter. More than two dimensions are projected onto their first two principal components."""
    np = _np()
    pts = _matrix(np, points)
    axes = ("x", "y")
    if pts.shape[1] > 2:
        centred = pts - pts.mean(axis=0)
        pts = centred @ np.linalg.svd(centred, full_matrices=False)[2][:2].T
        axes = ("PC 1", "PC 2")
    return _chart("scatter", None, {"x": pts[:, 0], "y": pts[:, 1], "color": None if labels is None else _strings(labels),
                                    "text": text}, title, {"xlabel": axes[0], "ylabel": axes[1]}, thin="random")
