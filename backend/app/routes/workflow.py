"""Workflow route aggregator.

This keeps workflow-related routes discoverable from a single module while
preserving existing API endpoints and prefixes in `app.main`.
"""

from app.api.ai import router as ai_router
from app.api.models import router as model_router

__all__ = [
    "ai_router",
    "model_router",
]

