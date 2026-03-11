"""Tests for models/request.py and models/response.py — Pydantic models."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.request import ChatRequest, MaterialInfo
from models.response import (
    AgentProgressEvent,
    TextDeltaEvent,
    PipelineCompleteEvent,
    PlanProposedEvent,
    ErrorEvent,
)


class TestChatRequest:
    def test_defaults(self):
        req = ChatRequest(message="hello")
        assert req.session_id is None
        assert req.business_type == "general_chat"
        assert req.materials == []

    def test_full_request(self):
        req = ChatRequest(
            session_id="sess-abc",
            message="review this",
            business_type="invoice_review",
            materials=[MaterialInfo(material_id="m1", filename="doc.pdf")],
        )
        assert len(req.materials) == 1
        assert req.materials[0].filename == "doc.pdf"

    def test_serialization(self):
        req = ChatRequest(message="test")
        d = req.model_dump()
        assert d["message"] == "test"
        assert "materials" in d

    def test_message_required(self):
        with pytest.raises(Exception):
            ChatRequest()


class TestMaterialInfo:
    def test_defaults(self):
        m = MaterialInfo(material_id="m1")
        assert m.material_type == "text"
        assert m.content == ""
        assert m.filename == ""


class TestResponseModels:
    def test_agent_progress_event(self):
        e = AgentProgressEvent(status="started", iteration=1)
        assert e.event == "agent_progress"
        assert e.status == "started"

    def test_text_delta_event(self):
        e = TextDeltaEvent(delta="hello")
        assert e.event == "text_delta"
        assert e.delta == "hello"

    def test_pipeline_complete_event(self):
        e = PipelineCompleteEvent(status="success", duration_ms=1500.0)
        assert e.event == "pipeline_complete"
        assert e.duration_ms == 1500.0

    def test_pipeline_complete_no_plan_awaiting(self):
        """A2: plan_awaiting_approval status removed."""
        e = PipelineCompleteEvent(status="success")
        assert e.status == "success"
        # Only valid statuses: success, partial, failed
        with pytest.raises(Exception):
            PipelineCompleteEvent(status="plan_awaiting_approval")

    def test_plan_proposed_event(self):
        e = PlanProposedEvent(
            summary="Execute plan",
            steps=[{"action": "step1"}],
        )
        assert e.event == "plan_proposed"
        # A2: requires_approval field removed

    def test_error_event(self):
        e = ErrorEvent(
            code="RATE_LIMIT",
            message="Too many requests",
            recoverable=True,
            category="rate_limit",
        )
        assert e.event == "error"
        assert e.recoverable is True
