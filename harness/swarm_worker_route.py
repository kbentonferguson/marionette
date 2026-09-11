from __future__ import annotations

"""Product workers use the agentic adapter with routed provider/model pairs."""

from typing import Optional


def resolve_product_worker_adapter(configured: Optional[str] = None) -> str:
    """Return the only adapter permitted for Marionette product workers."""
    return "agentic"
