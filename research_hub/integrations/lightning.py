"""PyTorch Lightning: a logger that sends ``self.log(...)`` metrics and hyperparameters to a hub run.

    from research_hub.integrations.lightning import HubLogger

    logger = HubLogger(title="ResNet18 on CIFAR-10", dataset="cifar10@1.0")   # hub.init arguments
    trainer = Trainer(logger=logger, max_epochs=5)
    trainer.fit(model, datamodule)
    logger.run.finish("val accuracy 0.93")
"""

from __future__ import annotations

try:
    from lightning.pytorch.loggers.logger import Logger, rank_zero_experiment
    from lightning.pytorch.utilities import rank_zero_only
except ImportError:  # the older package name
    from pytorch_lightning.loggers.logger import Logger, rank_zero_experiment
    from pytorch_lightning.utilities import rank_zero_only

from .. import client as hub
from . import metric_key, plain


class HubLogger(Logger):
    """The run is created on first use, on the main process only. Finish it yourself, with a conclusion."""

    def __init__(self, run: hub.Run | None = None, **init):
        super().__init__()
        self._run, self._init = run, init

    @property
    @rank_zero_experiment
    def run(self) -> hub.Run:
        if self._run is None:
            self._run = hub.init(**self._init)
        return self._run

    experiment = run

    @property
    def name(self) -> str:
        return self.run.hub.project or "hub"

    @property
    def version(self) -> str:
        return self.run.slug

    @rank_zero_only
    def log_hyperparams(self, params, *args, **kwargs):
        params = vars(params) if hasattr(params, "__dict__") and not isinstance(params, dict) else dict(params or {})
        if params:
            self.run.set_config(plain(params))

    @rank_zero_only
    def log_metrics(self, metrics, step=None):
        epoch = metrics.get("epoch")
        values = {metric_key(k): v for k, v in metrics.items() if k != "epoch"}
        if values:
            self.run.log(values, step=int(step or 0), epoch=None if epoch is None else int(epoch))

    @rank_zero_only
    def finalize(self, status):
        if status == "failed" and self._run is not None:
            self._run.fail("Training stopped with an error; see the job's log.")
