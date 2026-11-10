"""The smallest possible run: no ML library, no GPU. Shows the whole logging API in 30 lines.

    export HUB_URL=http://localhost:6230 HUB_TOKEN=hub_...  HUB_PROJECT=my-project
    python examples/01_quickstart.py
"""

import math
import random

from research_hub import hub


def main():
    config = {"lr": 3e-3, "epochs": 20, "batch_size": 64}
    run = hub.init(title="Quickstart: a simulated training run", config=config,   # project comes from HUB_PROJECT
                   pinned=["val/accuracy", "train/loss"])
    random.seed(0)
    for epoch in range(config["epochs"]):
        loss = 2.3 * math.exp(-epoch / 6) + random.uniform(0, 0.05)
        accuracy = 0.95 - 0.85 * math.exp(-epoch / 5) + random.uniform(-0.01, 0.01)
        run.log({"train/loss": loss, "val": {"accuracy": accuracy}, "lr": config["lr"] * 0.9 ** epoch},
                step=(epoch + 1) * 100, epoch=epoch)
    run.note("Nothing was trained: the curves are made up.")
    run.summary({"val/accuracy": accuracy, "train/loss": {"value": loss, "direction": "min"}})
    run.finish("Quickstart finished. Open the run to see the charts, the config and this conclusion.")
    print(f"logged {run.slug} to {run.hub.url}")


if __name__ == "__main__":
    main()
