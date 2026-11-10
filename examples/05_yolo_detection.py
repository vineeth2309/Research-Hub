"""Ultralytics YOLO on the 8-image coco8 dataset: per-epoch metrics through the integration, then every
validation image with its true and predicted boxes.

Downloads the yolo11n weights and coco8 on first use. A few minutes on a CPU.

    pip install ultralytics pillow numpy
    python examples/05_yolo_detection.py            # add --device 0 to train on a GPU
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

from research_hub.integrations.ultralytics import attach


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", default="cpu")
    p.add_argument("--epochs", type=int, default=3)
    args = p.parse_args()

    model = YOLO("yolo11n.pt")
    run = attach(model, title="YOLO11n fine-tuned on coco8", dataset="coco8@1.0",
                 pinned=["metrics/mAP50_B", "metrics/mAP50-95_B", "train/box_loss"])
    try:
        results = model.train(data="coco8.yaml", epochs=args.epochs, imgsz=320, device=args.device, workers=0,
                              plots=False, verbose=False)

        # One eval row per validation image: ground-truth boxes from the label files, predictions from the model.
        images = sorted(Path(model.trainer.data["val"]).glob("*.jpg"))
        rows = []
        for image, pred in zip(images, model.predict(images, device=args.device, verbose=False)):
            h, w = pred.orig_shape
            truth = []
            label_file = Path(str(image).replace("/images/", "/labels/")).with_suffix(".txt")
            for line in label_file.read_text().splitlines():
                cls, cx, cy, bw, bh = line.split()
                truth.append([(float(cx) - float(bw) / 2) * w, (float(cy) - float(bh) / 2) * h, float(bw) * w, float(bh) * h,
                              pred.names[int(cls)]])                       # boxes are [x, y, width, height, label]
            boxes = [[x1, y1, x2 - x1, y2 - y1, pred.names[int(c)], round(conf, 3)]
                     for (x1, y1, x2, y2), c, conf in zip(pred.boxes.xyxy.tolist(), pred.boxes.cls.tolist(), pred.boxes.conf.tolist())]
            rows.append({"sample": image.stem, "image": str(image), "facts": {"objects": str(min(len(truth), 5)) + ("+" if len(truth) > 5 else "")},
                         "true": {"boxes": truth}, "pred": {"boxes": boxes}})
        run.log_eval(rows, step=args.epochs, epoch=args.epochs - 1, eval_set="coco8@1.0:val")
    except Exception as e:
        run.fail(f"{type(e).__name__}: {e}")
        raise
    run.finish(f"mAP50 {results.results_dict['metrics/mAP50(B)']:.3f} on coco8 val after {args.epochs} epochs.")
    print(f"logged {run.slug} to {run.hub.url}")


if __name__ == "__main__":
    main()
