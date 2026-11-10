"""Optional adapters for training libraries. Each module imports its library only when you import the module.

    from research_hub.integrations.ultralytics import attach          # YOLO
    from research_hub.integrations.transformers import HubCallback    # Hugging Face Trainer
    from research_hub.integrations.lightning import HubLogger         # PyTorch Lightning
    from research_hub.integrations.sklearn import log_classifier      # scikit-learn estimators
"""

import re

_BAD = re.compile(r"[^A-Za-z0-9_./-]+")


def metric_key(name: str) -> str:
    """A library's metric name as a hub key: ``metrics/mAP50(B)`` -> ``metrics/mAP50_B``."""
    return _BAD.sub("_", str(name)).strip("_")[:80]


def plain(value):
    """Config values as JSON: paths, enums and other objects become strings."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
