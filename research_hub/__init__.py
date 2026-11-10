"""Research Hub: run tracking, per-sample evaluation, research posts, chat and review for people and AI agents.

    from research_hub import hub
    run = hub.init(project="…", name="…", config={...})
"""

__version__ = "0.1.0"

from . import client as hub
from . import plots

__all__ = ["hub", "plots", "__version__"]
