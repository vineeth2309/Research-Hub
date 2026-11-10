"""Hugging Face Trainer: a callback that logs training and evaluation metrics to a hub run.

    from research_hub.integrations.transformers import HubCallback

    callback = HubCallback(title="DistilBERT on SST-2", dataset="sst2@1.0")    # hub.init arguments
    trainer = Trainer(model=model, args=args, ..., callbacks=[callback])
    trainer.train()
    callback.run.finish("accuracy 0.91")

Pass ``report_to="none"`` in TrainingArguments to switch the built-in reporters off.
"""

from __future__ import annotations

from transformers import TrainerCallback

from .. import client as hub
from . import metric_key, plain


class HubCallback(TrainerCallback):
    """Logs ``loss``/``learning_rate`` as ``train/…`` and ``eval_*`` metrics as ``eval/…`` at each logging step.

    The run is created when training begins (or pass ``run=``). The last evaluation becomes the run's summary.
    Finish the run yourself, with a conclusion: ``callback.run.finish("…")``.
    """

    def __init__(self, run: hub.Run | None = None, **init):
        self.run, self._init, self._last_eval = run, init, {}

    def on_train_begin(self, args, state, control, **kwargs):
        if not state.is_world_process_zero:
            return
        if self.run is None:
            self.run = hub.init(**self._init)
        self.run.set_config(plain(args.to_dict()))

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not state.is_world_process_zero or self.run is None or not logs:
            return
        metrics = {}
        for key, value in logs.items():
            if not isinstance(value, (int, float)) or key == "epoch":
                continue
            if key.startswith("eval_"):
                metrics[metric_key("eval/" + key[5:])] = value
            elif not key.startswith("train_"):  # train_runtime etc. arrive once at the end; skip them
                metrics[metric_key("train/" + key)] = value
        self._last_eval.update({k: v for k, v in metrics.items() if k.startswith("eval/")})
        if metrics:
            self.run.log(metrics, step=state.global_step, epoch=int(state.epoch or 0))

    def on_train_end(self, args, state, control, **kwargs):
        if state.is_world_process_zero and self.run is not None and self._last_eval:
            keep = {k: v for k, v in self._last_eval.items() if not k.endswith(("runtime", "per_second"))}
            self.run.summary({k: {"value": v, "direction": "min" if k.endswith("loss") else "max"} for k, v in keep.items()})
