"""
Claw Agent data models.

Re-exports all Pydantic v2 models for API and agent modules.
"""

# ── request models ──────────────────────────────────────────────
from .request import (
    ChatRequest,
    MaterialInfo,
)

# ── response / SSE event models ─────────────────────────────────
from .response import (
    AgentProgressEvent,
    ErrorEvent,
    PipelineCompleteEvent,
    PlanProposedEvent,
    TextDeltaEvent,
)

__all__ = [
    # request
    "ChatRequest",
    "MaterialInfo",
    # response
    "AgentProgressEvent",
    "ErrorEvent",
    "PipelineCompleteEvent",
    "PlanProposedEvent",
    "TextDeltaEvent",
]
