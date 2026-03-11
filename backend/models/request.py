"""
Request models for the Claw Agent API.

Generic models — no domain-specific types.
SaaS integrators pass domain data via the opaque `context` dict.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MaterialInfo(BaseModel):
    """Uploaded material reference"""

    material_id: str
    material_type: str = "text"  # image, pdf, text, file
    content: str = ""  # base64 or text content
    filename: str = ""


class BusinessContext(BaseModel):
    """
    Generic business context — opaque container.

    SaaS integrators pass arbitrary domain data here.
    The prompt builder serializes it into XML for the agent.
    """

    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary context data (serialized as XML for the agent)",
    )
    protected_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Values the agent cannot override",
    )
    materials: list[MaterialInfo] = Field(
        default_factory=list,
        description="Uploaded materials",
    )


class ChatRequest(BaseModel):
    """Agent Gateway chat request"""

    user_id: str = Field("U001", description="User ID (isolation)")
    session_id: str | None = Field(None, description="Resume existing session")
    message: str = Field(..., description="User message")
    business_type: str = Field(
        "general_chat",
        description="Business type identifier (e.g. 'invoice_review', 'general_chat')",
    )
    plan_mode: bool = Field(
        True,
        description="True=AUTO (agent decides), False=EXECUTE (confirmed plan)",
    )
    context: BusinessContext = Field(
        default_factory=BusinessContext,
        description="Business context",
    )
