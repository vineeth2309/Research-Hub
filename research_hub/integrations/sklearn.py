"""scikit-learn: log the standard evaluation charts for a fitted estimator in one call.

    from research_hub.integrations.sklearn import log_classifier, log_regressor
    log_classifier(run, model, X_test, y_test)      # confusion matrix, ROC, PR, calibration, per-class scores, ...
    log_regressor(run, model, X_test, y_test)       # predicted vs actual, residuals, error distribution

Works with anything that follows the scikit-learn estimator interface (XGBoost, LightGBM, CatBoost, pipelines).
"""

from __future__ import annotations

import numpy as np

from .. import plots


def _importance(run, model, X, prefix, step):  # noqa: N803
    final = model.steps[-1][1] if hasattr(model, "steps") else model  # a Pipeline's last step
    values = getattr(final, "feature_importances_", None)
    if values is None and getattr(final, "coef_", None) is not None:
        values = np.abs(np.atleast_2d(final.coef_)).mean(axis=0)
    if values is None:
        return
    names = getattr(final, "feature_names_in_", None)
    if names is None:
        names = getattr(X, "columns", None) if len(getattr(X, "columns", ())) == len(values) else None
    if names is None:
        names = [f"feature {i}" for i in range(len(values))]
    run.log_chart(f"{prefix}/feature_importance", plots.feature_importance(names, values), step)


def log_classifier(run, model, X, y, *, labels=None, prefix="eval", step=None) -> dict:  # noqa: N803
    """Log a fitted classifier's charts and summary scores on held-out data; returns the summary values."""
    y = np.asarray(y)
    pred = model.predict(X)
    classes = list(labels if labels is not None else model.classes_)
    run.log_chart(f"{prefix}/confusion_matrix", plots.confusion_matrix(y, pred, labels=classes), step)
    run.log_chart(f"{prefix}/per_class", plots.per_class_metrics(y, pred, labels=classes), step)
    run.log_chart(f"{prefix}/class_distribution", plots.class_distribution(y, pred, labels=classes), step)
    scores = model.predict_proba(X) if hasattr(model, "predict_proba") else (
        model.decision_function(X) if hasattr(model, "decision_function") else None)
    if scores is not None:
        scores = np.asarray(scores)
        binary = len(classes) == 2
        if binary and scores.ndim == 2:
            scores = scores[:, 1]
        run.log_chart(f"{prefix}/roc", plots.roc_curve(y, scores, labels=classes), step)
        run.log_chart(f"{prefix}/precision_recall", plots.pr_curve(y, scores, labels=classes), step)
        if binary:
            run.log_chart(f"{prefix}/threshold_sweep", plots.threshold_sweep(y, scores, labels=classes), step)
            if hasattr(model, "predict_proba"):
                run.log_chart(f"{prefix}/calibration", plots.calibration(y, scores, labels=classes), step)
    _importance(run, model, X, prefix, step)
    names = np.array([str(c) for c in classes])
    true, guess = y.astype(str), np.asarray(pred).astype(str)
    recalls = [float((guess[true == c] == c).mean()) for c in names if (true == c).any()]
    summary = {f"{prefix}/accuracy": float((true == guess).mean()), f"{prefix}/balanced_accuracy": float(np.mean(recalls))}
    run.summary(summary)
    return summary


def log_regressor(run, model, X, y, *, prefix="eval", step=None) -> dict:  # noqa: N803
    """Log a fitted regressor's charts and summary errors on held-out data; returns the summary values."""
    y = np.asarray(y, dtype=float)
    pred = np.asarray(model.predict(X), dtype=float)
    run.log_chart(f"{prefix}/predicted_vs_actual", plots.predicted_vs_actual(y, pred), step)
    run.log_chart(f"{prefix}/residuals", plots.residuals(y, pred), step)
    run.log_chart(f"{prefix}/error_histogram", plots.error_histogram(y, pred), step)
    _importance(run, model, X, prefix, step)
    error = pred - y
    scores = {f"{prefix}/mae": float(np.abs(error).mean()), f"{prefix}/rmse": float(np.sqrt((error ** 2).mean()))}
    run.summary(scores, direction="min")
    spread = float(((y - y.mean()) ** 2).sum())
    if spread:
        scores[f"{prefix}/r2"] = 1 - float((error ** 2).sum()) / spread
        run.summary({f"{prefix}/r2": scores[f"{prefix}/r2"]})
    return scores
