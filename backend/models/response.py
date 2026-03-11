"""
SSE event response models.

Generic event types for the Claw Agent SSE stream.
Domain-specific events are emitted as plain dicts by capability tools.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentProgressEvent(BaseModel):
    """Agent execution progress event"""

    event: Literal["agent_progress"] = "agent_progress"
    status: str  # started, calling_tools, completed, max_iterations_reached, error
    agent: str = ""
    iteration: int | None = None
    tool_calls: int | None = None
    trace_id: str = ""
    phase: str = ""          # Current workflow phase (WorkflowPhase.value)
    progress: float = 0.0    # Completion progress 0.0-1.0


class TextDeltaEvent(BaseModel):
    """Streaming text chunk event"""

    event: Literal["text_delta"] = "text_delta"
    delta: str = ""


class PipelineCompleteEvent(BaseModel):
    """Pipeline completion event"""

    event: Literal["pipeline_complete"] = "pipeline_complete"
    status: Literal["success", "partial", "failed", "plan_awaiting_approval"] = "success"
    duration_ms: float = 0.0
    summary: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""


class PlanProposedEvent(BaseModel):
    """Plan proposal event"""

    event: Literal["plan_proposed"] = "plan_proposed"
    summary: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    estimated_actions: int = 0
    requires_approval: bool = False


class ErrorEvent(BaseModel):
    """Error event"""

    event: Literal["error"] = "error"
    code: str = "UNKNOWN"
    message: str = ""
    step: str = ""
    recoverable: bool = True
    category: str = ""           # Error classification (ErrorCategory.value)
    affected_step: str = ""      # Step that errored
    suggested_action: str = ""   # Suggested remediation
    trace_id: str = ""           # Request trace ID
