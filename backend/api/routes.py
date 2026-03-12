"""
Claw Agent API routes.

Core endpoints:
- POST /api/chat — Agent Gateway chat (SSE stream)
- GET /api/health — Health check
- GET /api/tools — List registered tools
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from api.sse import event_bus_to_sse
from core.event_bus import EventBus
from core.context import current_trace_id
from core.errors import AgentError, classify_error
from core.auth import AuthUser, get_current_user
from models.request import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agent"])


@router.post("/chat")
async def chat(request: ChatRequest, user: AuthUser = Depends(get_current_user)):
    """
    Agent Gateway chat endpoint.

    Accepts a user message with optional business context,
    processes it through the AgentGateway, and returns an SSE event stream.

    SSE Events:
    - pipeline_started: Session started (includes session_id)
    - agent_progress: Agent work progress
    - text_delta: Streaming text output
    - plan_proposed: Execution plan (plan mode)
    - pipeline_complete: Completion
    - error: Error
    """
    from dependencies import build_gateway

    # Generate request trace ID
    trace_id = uuid.uuid4().hex[:12]
    current_trace_id.set(trace_id)

    # Create EventBus
    bus = EventBus(trace_id=trace_id)

    # Build Gateway
    gateway = build_gateway()

    # Run Gateway.chat in background task
    async def run_chat():
        try:
            await gateway.chat(
                tenant_id=user.tenant_id,
                user_id=user.user_id,
                session_id=request.session_id,
                message=request.message,
                business_type=request.business_type,
                materials=[m.model_dump() for m in request.materials],
                event_bus=bus,
            )
        except AgentError as e:
            logger.exception(f"Gateway chat error (category={e.category}): {e}")
            bus.emit("error", e.to_error_event(trace_id=trace_id))
        except Exception as e:
            logger.exception(f"Gateway chat error: {e}")
            category = classify_error(error_msg=str(e), exception=e)
            bus.emit("error", {
                "code": category.value.upper(),
                "message": str(e),
                "recoverable": False,
                "category": category.value,
                "trace_id": trace_id,
            })
        finally:
            await asyncio.sleep(0.1)
            if not bus.is_closed:
                bus.close()

    asyncio.create_task(run_chat())
    return EventSourceResponse(event_bus_to_sse(bus))


@router.get("/health")
async def health_check():
    """Health check."""
    return {
        "status": "ok",
        "service": "claw-agent",
        "version": "0.1.0",
        "architecture": "agent-gateway",
    }


@router.get("/tools")
async def list_tools():
    """List all registered tools."""
    from tools.registry_builder import build_full_registry

    tools_list = []
    try:
        registry = build_full_registry()
        for name, tool in registry._tools.items():
            fn = tool.schema.get("function", {})
            tools_list.append({
                "name": fn.get("name", name),
                "description": fn.get("description", tool.description),
                "category": getattr(tool, "category", "general"),
                "read_only": tool.read_only,
            })
    except Exception:
        logger.debug("Failed to load tool registry", exc_info=True)

    return {"tools": tools_list}


@router.get("/soul")
async def get_soul():
    """Return soul.md content for preview."""
    from pathlib import Path
    soul_path = Path(__file__).parent.parent / "prompts" / "soul.md"
    try:
        return {"content": soul_path.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"content": "(soul.md 文件未找到)"}
