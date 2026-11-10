"""Ultralytics YOLO: log every epoch's losses and validation metrics to a hub run.

    from ultralytics import YOLO
    from research_hub.integrations.ultralytics import attach

    model = YOLO("yolo11n.pt")
    run = attach(model, title="YOLO11n on coco8", dataset="coco8@1.0")   # hub.init arguments
    model.train(data="coco8.yaml", epochs=3)
    run.finish("mAP50 0.71 after 3 epochs")
"""

from __future__ import annotations

from .. import client as hub
from . import metric_key, plain


def attach(model, run: hub.Run | None = None, watch: bool = True, **init) -> hub.Run:
    """Register callbacks on ``model`` that log to ``run`` (created with ``hub.init(**init)`` when not given).

    Logged per epoch: ``train/<loss>``, ``lr/<group>`` and the validation metrics (``metrics/mAP50_B``, …).
    When training ends the final validation metrics become the run's summary and the training arguments its
    config. The model's architecture is captured from the first training step (``watch=False`` turns that off).
    Finish the run yourself, with a conclusion.
    """
    run = run or hub.init(**init)

    def on_train_start(trainer):
        run.set_config(plain(vars(trainer.args)))
        if watch:
            run.watch(getattr(trainer.model, "module", trainer.model))  # unwrap DataParallel

    def on_fit_epoch_end(trainer):
        metrics = {metric_key(k): v for k, v in trainer.label_loss_items(trainer.tloss, prefix="train").items()}
        metrics.update({metric_key(k): v for k, v in trainer.lr.items()})
        metrics.update({metric_key(k): v for k, v in trainer.metrics.items()})
        run.log(metrics, step=trainer.epoch + 1, epoch=trainer.epoch)

    def on_train_end(trainer):
        final = {metric_key(k): float(v) for k, v in trainer.metrics.items() if k.startswith("metrics/")}
        if final:
            run.summary(final)

    for event, fn in (("on_train_start", on_train_start), ("on_fit_epoch_end", on_fit_epoch_end),
                      ("on_train_end", on_train_end)):
        model.add_callback(event, fn)
    return run
