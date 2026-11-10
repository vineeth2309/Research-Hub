"""One run that logs every kind of per-sample result the hub understands, on synthetic images of shapes.

Classification, regression, segmentation masks, heatmaps, detection boxes and text all go through the same
call, ``run.log_eval(rows, ...)``: a row carries whatever the task produced. No model is trained; predictions
are the ground truth with noise that shrinks every "epoch", so the dashboard shows results improving.

    pip install pillow numpy
    python examples/03_all_task_types.py
"""

import numpy as np

from research_hub import hub

SIZE, SAMPLES, EPOCHS = 96, 60, 5
SHAPES = ("circle", "square", "none")
COLOURS = {"red": (0.85, 0.2, 0.2), "green": (0.2, 0.7, 0.3), "blue": (0.2, 0.35, 0.85)}


def make_sample(rng, i):
    """An image with at most one shape, and everything known about it."""
    shape = SHAPES[i % 3] if i % 7 else "none"
    colour = list(COLOURS)[int(rng.integers(3))]
    image = np.full((SIZE, SIZE, 3), 0.92) + rng.normal(0, 0.02, (SIZE, SIZE, 3))
    mask = np.zeros((SIZE, SIZE))
    r = int(rng.integers(10, 26))
    cx, cy = rng.integers(r + 2, SIZE - r - 2, 2)
    yy, xx = np.mgrid[:SIZE, :SIZE]
    if shape == "circle":
        mask = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r).astype(float)
    elif shape == "square":
        mask = ((abs(xx - cx) <= r) & (abs(yy - cy) <= r)).astype(float)
    image[mask > 0] = COLOURS[colour]
    box = [int(cx - r), int(cy - r), 2 * r, 2 * r, shape] if shape != "none" else None
    caption = f"a {colour} {shape}" if shape != "none" else "an empty image"
    return {"id": f"shape-{i:03d}", "shape": shape, "colour": colour, "size": "large" if r > 18 else "small",
            "image": image.clip(0, 1), "mask": mask, "box": box, "area": float(mask.sum()), "caption": caption}


def predict(rng, s, noise):
    """A fake model: the truth, degraded by ``noise`` (1 = useless, 0 = perfect). Returns (prediction, metrics)."""
    shape = SHAPES[int(rng.integers(3))] if rng.random() < noise * 0.6 else s["shape"]
    mask = np.clip(s["mask"] * (1 - 0.5 * noise) + rng.normal(0, 0.25 * noise, s["mask"].shape), 0, 1)
    attention = np.clip(s["mask"] * 0.8 + rng.random(s["mask"].shape) * noise, 0, 1)
    boxes = []
    if s["box"] and rng.random() > noise * 0.4:
        xywh = (np.array(s["box"][:4]) + rng.normal(0, 8 * noise, 4)).round(1).tolist()
        boxes.append([*xywh, shape if shape != "none" else s["shape"], round(float(1 - noise * rng.random()), 2)])
    if rng.random() < noise * 0.3:  # a false positive somewhere else
        boxes.append([*rng.integers(0, SIZE - 20, 2).tolist(), 18, 18, "circle", 0.35])
    union = float(((mask > 0.5) | (s["mask"] > 0)).sum())
    iou = float(((mask > 0.5) & (s["mask"] > 0)).sum()) / union if union else 1.0
    caption = s["caption"] if shape == s["shape"] else f"a {s['colour']} {shape}" if shape != "none" else "an empty image"
    return {"class": shape, "score": round(float(1 - noise * rng.random()), 3),
            "value": s["area"] * (1 + rng.normal(0, noise)),            # regression target: the shape's area in pixels
            "masks": {"shape": mask}, "heatmaps": {"attention": attention}, "boxes": boxes, "text": caption}, {"iou": iou}


def main():
    rng = np.random.default_rng(0)
    samples = [make_sample(rng, i) for i in range(SAMPLES)]
    run = hub.init(title="All task types on synthetic shapes", dataset="shapes@1.0",
                   pinned=["val/accuracy", "val/mean_iou"],
                   config={"samples": SAMPLES, "epochs": EPOCHS, "note": "predictions are simulated"})
    for epoch in range(EPOCHS):
        noise = 0.9 * (1 - epoch / EPOCHS) ** 1.5 + 0.05
        rows, correct, ious = [], 0, []
        for s in samples:
            pred, metrics = predict(rng, s, noise)
            correct += pred["class"] == s["shape"]
            ious.append(metrics["iou"])
            rows.append({
                "sample": s["id"],
                "facts": {"colour": s["colour"], "size": s["size"]},
                "image": s["image"],
                "true": {"class": s["shape"], "value": s["area"], "masks": {"shape": s["mask"]},
                         "boxes": [s["box"]] if s["box"] else [], "text": s["caption"]},
                "pred": pred,
                "metrics": metrics,
            })
        step = (epoch + 1) * 500
        run.log({"val": {"accuracy": correct / SAMPLES, "mean_iou": float(np.mean(ious))}, "train/loss": noise},
                step=step, epoch=epoch)
        run.log_eval(rows, step=step, epoch=epoch, eval_set="shapes@1.0:val", negatives=["none"])
    run.summary({"val/accuracy": correct / SAMPLES, "val/mean_iou": float(np.mean(ious))})
    run.finish("Synthetic run: open Samples to see masks, heatmaps, boxes and text on one image per sample.")
    print(f"logged {run.slug} to {run.hub.url}")


if __name__ == "__main__":
    main()
