"""Every kind of plot the hub draws, from NumPy arrays, pandas DataFrames and scikit-learn models.

Trains a gradient-boosted classifier and a regressor on two small built-in datasets (seconds on a CPU) and logs:
the standard evaluation charts in one call each (`log_classifier`, `log_regressor`), then one of every general
chart built by hand with `research_hub.plots`, a table, and a histogram logged at every boosting stage so the
Plots tab can show it moving over time.

    pip install scikit-learn pandas numpy
    python examples/07_plots_gallery.py
"""

import numpy as np
import pandas as pd
from sklearn.datasets import load_breast_cancer, load_diabetes
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.model_selection import learning_curve, train_test_split

from research_hub import hub, plots
from research_hub.integrations.sklearn import log_classifier, log_regressor

STAGES = 60


def classifier():
    data = load_breast_cancer(as_frame=True)
    frame, target = data.data, data.target.map(dict(enumerate(data.target_names)))  # "malignant" / "benign"
    x_train, x_test, y_train, y_test = train_test_split(frame, target, test_size=0.3, random_state=0, stratify=target)
    config = {"model": "GradientBoostingClassifier", "n_estimators": STAGES, "max_depth": 2, "learning_rate": 0.1}
    run = hub.init(title="Plots gallery: tumour classifier", config=config, dataset="sklearn_breast_cancer@1.0",
                   pinned=["test/accuracy", "test/log_loss"])
    model = GradientBoostingClassifier(n_estimators=STAGES, max_depth=2, learning_rate=0.1, random_state=0)
    model.fit(x_train, y_train)

    # Scalars and one histogram per boosting stage: the score distribution separates as trees are added.
    malignant = list(model.classes_).index("malignant")
    for stage, proba in enumerate(model.staged_predict_proba(x_test), start=1):
        truth = (y_test == "malignant").to_numpy()
        p = np.clip(proba[:, malignant], 1e-9, 1 - 1e-9)
        run.log({"test": {"accuracy": float(((p > 0.5) == truth).mean()),
                          "log_loss": float(-np.mean(np.where(truth, np.log(p), np.log(1 - p))))}}, step=stage)
        if stage % 5 == 0:
            run.log_histogram("training/malignant_score", p, step=stage, bins=30)

    # The standard evaluation charts for any scikit-learn style estimator, in one call.
    log_classifier(run, model, x_test, y_test, prefix="eval")

    # General charts. Pass a DataFrame and column names ...
    scored = x_test.assign(diagnosis=y_test, score=model.predict_proba(x_test)[:, malignant])
    run.log_chart("data/radius_vs_texture", plots.scatter(
        scored, x="mean radius", y="mean texture", color="diagnosis", size="mean area", title="Radius against texture"))
    run.log_chart("data/score_by_diagnosis", plots.histogram(
        scored, value="score", by="diagnosis", bins=25, title="Malignant score by true diagnosis"))
    run.log_chart("data/radius_box", plots.box(scored, value="mean radius", by="diagnosis", title="Mean radius"))
    run.log_chart("data/concavity_violin", plots.violin(scored, value="mean concavity", by="diagnosis",
                                                        title="Mean concavity"))
    run.log_chart("data/score_vs_area", plots.scatter(
        scored, x="mean area", y="mean smoothness", color="score", title="Coloured by malignant score"))
    # ... or pass arrays directly.
    counts = y_test.value_counts()
    run.log_chart("data/class_share", plots.pie(label=counts.index, value=counts.to_numpy(), title="Test set"))
    first = frame.columns[:8]
    run.log_chart("data/correlation", plots.heatmap(
        matrix=frame[first].corr().to_numpy(), x_labels=first, y_labels=first, diverging=True,
        title="Feature correlation"))
    run.log_chart("data/embedding", plots.embedding(
        (frame - frame.mean()) / frame.std(), labels=target, title="All 30 features, first two principal components"))
    sizes, train_scores, val_scores = learning_curve(
        GradientBoostingClassifier(n_estimators=20, max_depth=2, random_state=0), frame, target, cv=4,
        train_sizes=np.linspace(0.15, 1.0, 6))
    run.log_chart("training/learning_curve", plots.learning_curve(sizes, train_scores, val_scores, ylabel="Accuracy"))
    trees = np.arange(1, STAGES + 1)
    run.log_chart("training/deviance", plots.area(x=trees, y=model.train_score_, title="Training deviance by tree",
                                                  xlabel="Trees", ylabel="Deviance"))
    means = scored.groupby("diagnosis")[["mean radius", "mean perimeter", "mean concave points"]].mean()
    long = means.reset_index().melt("diagnosis", var_name="feature", value_name="mean")
    run.log_chart("data/feature_means", plots.bar(long, x="feature", y="mean", color="diagnosis",
                                                  title="Feature means by diagnosis", ylog=True))
    run.log_table("eval/least_confident", pd.DataFrame({
        "diagnosis": y_test, "predicted": model.predict(x_test), "malignant score": scored["score"].round(4),
        "mean radius": x_test["mean radius"], "mean texture": x_test["mean texture"],
    }).assign(doubt=lambda d: (0.5 - (d["malignant score"] - 0.5).abs()).round(4)).sort_values("doubt", ascending=False))

    run.finish("Gradient boosting separates the classes almost completely by tree 30. Open the Plots tab.")
    return run


def regressor():
    data = load_diabetes(as_frame=True)
    x_train, x_test, y_train, y_test = train_test_split(data.data, data.target, test_size=0.3, random_state=0)
    run = hub.init(title="Plots gallery: disease progression regressor", dataset="sklearn_diabetes@1.0",
                   config={"model": "GradientBoostingRegressor", "n_estimators": 80, "max_depth": 2})
    model = GradientBoostingRegressor(n_estimators=80, max_depth=2, random_state=0).fit(x_train, y_train)
    scores = log_regressor(run, model, x_test, y_test, prefix="eval")
    run.finish(f"R² {scores['eval/r2']:.3f}, MAE {scores['eval/mae']:.1f}. Residuals grow with the predicted value.")
    return run


if __name__ == "__main__":
    first = classifier()
    second = regressor()
    print(f"logged {first.slug} and {second.slug} to {first.hub.url}")
