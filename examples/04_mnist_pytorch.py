"""MNIST with a small PyTorch CNN: metrics every epoch and every validation image as an eval sample.

Runs on a CPU in about a minute with the default subset; pass --device cuda and --train 60000 for the real thing.

    pip install torch torchvision pillow numpy
    python examples/04_mnist_pytorch.py
"""

import argparse

import torch
import torch.nn.functional as F
from torch import nn
from torchvision import datasets, transforms

from research_hub import hub


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", default="cpu")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--train", type=int, default=6000, help="training images to use")
    p.add_argument("--val", type=int, default=500, help="validation images to evaluate and log")
    p.add_argument("--lr", type=float, default=2e-3)
    p.add_argument("--data", default="~/.cache/mnist")
    args = p.parse_args()
    torch.manual_seed(0)

    to_tensor = transforms.ToTensor()
    train_set = torch.utils.data.Subset(datasets.MNIST(args.data, train=True, download=True, transform=to_tensor), range(args.train))
    val_set = torch.utils.data.Subset(datasets.MNIST(args.data, train=False, download=True, transform=to_tensor), range(args.val))
    train = torch.utils.data.DataLoader(train_set, batch_size=64, shuffle=True)
    val = torch.utils.data.DataLoader(val_set, batch_size=250)
    model = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2), nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
                          nn.MaxPool2d(2), nn.Flatten(), nn.Linear(32 * 7 * 7, 10)).to(args.device)
    optimiser = torch.optim.Adam(model.parameters(), lr=args.lr)

    run = hub.init(title="MNIST: two-layer CNN", config=vars(args), dataset="mnist@1.0", pinned=["val/accuracy", "train/loss"])
    step = 0
    try:
        for epoch in range(args.epochs):
            model.train()
            for x, y in train:
                loss = F.cross_entropy(model(x.to(args.device)), y.to(args.device))
                optimiser.zero_grad()
                loss.backward()
                optimiser.step()
                step += 1
                if step % 20 == 0:
                    run.log({"train/loss": loss}, step=step, epoch=epoch)      # tensors are accepted

            model.eval()
            rows, correct, total_loss = [], 0, 0.0
            with torch.no_grad():
                for b, (x, y) in enumerate(val):
                    prob = model(x.to(args.device)).softmax(1).cpu()
                    total_loss += F.nll_loss(prob.log(), y, reduction="sum").item()
                    correct += (prob.argmax(1) == y).sum().item()
                    for i in range(len(y)):
                        rows.append({
                            "sample": f"mnist-test-{b * val.batch_size + i:05d}",
                            "image": x[i, 0].numpy(),                          # HxW float array in 0..1
                            "true": {"class": str(y[i].item())},
                            "pred": {"class": str(prob[i].argmax().item()), "score": prob[i].max().item()},
                            "error": 1 - prob[i, y[i]].item(),
                        })
            run.log({"val": {"accuracy": correct / len(val_set), "loss": total_loss / len(val_set)}}, step=step, epoch=epoch)
            run.log_eval(rows, step=step, epoch=epoch, eval_set="mnist@1.0:test")
    except Exception as e:
        run.fail(f"{type(e).__name__}: {e}")
        raise
    run.summary({"val/accuracy": correct / len(val_set), "val/loss": {"value": total_loss / len(val_set), "direction": "min"}})
    run.finish(f"{correct / len(val_set):.3f} accuracy on {len(val_set)} test images after {args.epochs} epochs "
               f"on {args.train} training images.")
    print(f"logged {run.slug} to {run.hub.url}")


if __name__ == "__main__":
    main()
