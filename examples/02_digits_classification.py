"""Handwritten-digit classification with scikit-learn, with every validation sample logged.

Trains a small MLP on the 8x8 digits dataset (a few seconds on a CPU) and logs, after each epoch, one row per
validation image: the image, the true and predicted class, the confidence and two filterable facts. In the
dashboard, open the run's Samples tab to browse mistakes, filter them, and step one image through the epochs.

    pip install scikit-learn pillow numpy
    python examples/02_digits_classification.py
"""

import numpy as np
from sklearn.datasets import load_digits
from sklearn.metrics import accuracy_score, f1_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier

from research_hub import hub

EPOCHS = 12


def main():
    digits = load_digits()
    idx = np.arange(len(digits.target))
    train, val = train_test_split(idx, test_size=0.25, random_state=0, stratify=digits.target)
    x = digits.data / 16.0
    config = {"model": "MLP", "hidden": [64], "lr": 0.02, "epochs": EPOCHS, "seed": 0}
    run = hub.init(title="Digits: MLP baseline", config=config, dataset="sklearn_digits@1.0",
                   pinned=["val/accuracy", "val/macro_f1", "train/loss"])
    model = MLPClassifier(hidden_layer_sizes=config["hidden"], learning_rate_init=config["lr"], random_state=0)
    classes = np.unique(digits.target)
    for epoch in range(EPOCHS):
        model.partial_fit(x[train], digits.target[train], classes=classes)
        proba = model.predict_proba(x[val])
        pred = proba.argmax(1)
        step = (epoch + 1) * len(train)
        run.log({"train/loss": model.loss_, "val": {"loss": log_loss(digits.target[val], proba),
                                                    "accuracy": accuracy_score(digits.target[val], pred),
                                                    "macro_f1": f1_score(digits.target[val], pred, average="macro")}},
                step=step, epoch=epoch)
        rows = [{
            "sample": f"digit-{i:04d}",                                   # a stable id: the same image across epochs
            "facts": {"ink": "heavy" if digits.data[i].sum() > 310 else "light",   # any key=value you want to filter by
                      "writer_group": f"g{i % 7}"},
            "image": np.kron(digits.images[i] / 16.0, np.ones((12, 12)))[..., None].repeat(3, -1),  # stored once
            "true": {"class": str(digits.target[i])},
            "pred": {"class": str(pred[j]), "score": float(proba[j].max())},
            "error": float(1 - proba[j, digits.target[i]]),               # sorts the grid: least confident first
        } for j, i in enumerate(val)]
        run.log_eval(rows, step=step, epoch=epoch, eval_set="sklearn_digits@1.0:val")
    accuracy = accuracy_score(digits.target[val], pred)
    run.summary({"val/accuracy": accuracy, "val/macro_f1": f1_score(digits.target[val], pred, average="macro"),
                 "val/loss": {"value": log_loss(digits.target[val], proba), "direction": "min"}})
    run.finish(f"MLP reaches {accuracy:.3f} validation accuracy after {EPOCHS} epochs. "
               "Open the Samples tab and its confusion matrix to see which digits are still confused.")
    print(f"logged {run.slug} to {run.hub.url}")


if __name__ == "__main__":
    main()
