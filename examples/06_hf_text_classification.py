"""Hugging Face Trainer: fine-tune a tiny BERT on a toy sentiment set, logging through the hub callback, then
log every validation sentence with its true and predicted label.

Downloads a 17 MB model on first use; under a minute on a CPU.

    pip install transformers torch accelerate
    python examples/06_hf_text_classification.py
"""

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments

from research_hub.integrations.transformers import HubCallback

MODEL = "prajjwal1/bert-tiny"
LABELS = ["negative", "positive"]
GOOD = ["great", "wonderful", "excellent", "a joy", "brilliant", "delightful", "superb", "charming"]
BAD = ["terrible", "boring", "awful", "a mess", "dreadful", "tedious", "clumsy", "forgettable"]
THINGS = ["The film", "This book", "The acting", "The soundtrack", "Dinner", "The ending", "The plot", "Our trip"]


class Sentences(torch.utils.data.Dataset):
    def __init__(self, tokenizer, things):
        self.text = [f"{t} was {w}." for t in things for w in GOOD + BAD]
        self.label = [int(w in GOOD) for _ in things for w in GOOD + BAD]
        self.encoded = tokenizer(self.text, padding=True, truncation=True, return_tensors="pt")

    def __len__(self):
        return len(self.text)

    def __getitem__(self, i):
        return {**{k: v[i] for k, v in self.encoded.items()}, "labels": self.label[i]}


def main():
    tokenizer = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=2)
    train, val = Sentences(tokenizer, THINGS[:6]), Sentences(tokenizer, THINGS[6:])
    callback = HubCallback(title="bert-tiny on toy sentiment", dataset="toy_sentiment@1.0",
                           pinned=["eval/accuracy", "train/loss"])
    args = TrainingArguments(output_dir="/tmp/hub-example-hf", num_train_epochs=8, per_device_train_batch_size=16,
                             learning_rate=3e-4, logging_steps=5, eval_strategy="epoch", save_strategy="no",
                             report_to="none", use_cpu=not torch.cuda.is_available(), seed=0)
    trainer = Trainer(model=model, args=args, train_dataset=train, eval_dataset=val, callbacks=[callback],
                      compute_metrics=lambda p: {"accuracy": float((p.predictions.argmax(1) == p.label_ids).mean())})
    trainer.train()
    run = callback.run

    out = trainer.predict(val)
    prob = torch.tensor(out.predictions).softmax(1).numpy()
    rows = [{"sample": f"val-{i:03d}", "facts": {"subject": val.text[i].split(" was ")[0]},
             "true": {"class": LABELS[val.label[i]], "text": val.text[i]},      # `text` shows the sentence in the viewer
             "pred": {"class": LABELS[int(prob[i].argmax())], "score": float(prob[i].max())},
             "error": float(1 - prob[i, val.label[i]])} for i in range(len(val))]
    run.log_eval(rows, step=trainer.state.global_step, eval_set="toy_sentiment@1.0:val", negatives=["negative"])
    accuracy = float(np.mean(prob.argmax(1) == np.array(val.label)))
    run.finish(f"{accuracy:.2f} accuracy on {len(val)} held-out sentences about unseen subjects.")
    print(f"logged {run.slug} to {run.hub.url}")


if __name__ == "__main__":
    main()
