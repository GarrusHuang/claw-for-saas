"""
Request models for the Claw Agent API.

Generic models — no domain-specific types.
A2: Removed BusinessContext (MCP pull mode) and plan_mode (Plan simplification).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MaterialInfo(BaseModel):
    """Uploaded material reference"""

    material_id: str
    material_type: str = "text"  # image, pdf, text, file
    content: str = ""  # base64 or text content
    filename: str = ""


class ChatRequest(BaseModel):
    """Agent Gateway chat request"""

    session_id: str | None = Field(None, description="Resume existing session")
    message: str = Field(..., max_length=100_000, description="User message")
    business_type: str = Field(
        "general_chat",
        description="Business type identifier (e.g. 'invoice_review', 'general_chat')",
    )
    materials: list[MaterialInfo] = Field(
        default_factory=list,
        description="Uploaded materials",
    )
