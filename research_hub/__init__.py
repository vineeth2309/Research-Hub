"""Research Hub: run tracking, per-sample evaluation, research posts, chat and review for people and AI agents.

    from research_hub import hub
    run = hub.init(project="…", name="…", config={...})
"""

__version__ = "0.1.0"

from . import client as hub  # noqa: E402,F401  (``hub.init``, ``hub.Run``, ``hub.Hub``)
from . import plots  # noqa: E402,F401  (chart builders for ``run.log_chart``)

__all__ = ["hub", "plots", "__version__"]
