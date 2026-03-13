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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agent.gateway import SessionBusyError
from api.sse import event_bus_to_sse
from core.event_bus import EventBus
from core.context import current_trace_id
from core.errors import AgentError, classify_error
from core.auth import AuthUser, get_current_user, get_current_user_optional
from models.request import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agent"])

# Active session EventBus registry — maps session_id to EventBus for running pipelines
_active_sessions: dict[str, EventBus] = {}


@router.post("/chat")
async def chat(request: ChatRequest, raw_request: Request, user: AuthUser = Depends(get_current_user)):
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

    # Track the session_id for active session registration.
    # When request.session_id is provided, register immediately.
    # Otherwise, auto-register when gateway emits pipeline_started with the new session_id.
    effective_session_id = request.session_id

    # Wrap emit to auto-register on pipeline_started (captures new session_id)
    _original_emit = bus.emit

    def _tracking_emit(event_type: str, data: dict | None = None) -> None:
        nonlocal effective_session_id
        if event_type == "pipeline_started" and data and "session_id" in data:
            sid = data["session_id"]
            if sid != effective_session_id:
                # Remove old registration if any
                if effective_session_id and effective_session_id in _active_sessions:
                    del _active_sessions[effective_session_id]
                effective_session_id = sid
                _active_sessions[sid] = bus
        _original_emit(event_type, data)

    bus.emit = _tracking_emit  # type: ignore[method-assign]

    # Run Gateway.chat in background task
    async def run_chat():
        nonlocal effective_session_id
        try:
            result = await gateway.chat(
                tenant_id=user.tenant_id,
                user_id=user.user_id,
                session_id=request.session_id,
                message=request.message,
                business_type=request.business_type,
                materials=[m.model_dump() for m in request.materials],
                event_bus=bus,
            )
            # Track the actual session_id returned (may differ from request)
            effective_session_id = result.get("session_id", effective_session_id)
        except SessionBusyError:
            bus.emit("error", {
                "code": "SESSION_BUSY",
                "message": "该会话正在处理中，请稍后再试",
                "recoverable": True,
                "category": "rate_limit",
                "trace_id": trace_id,
            })
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
            # Unregister from active sessions
            if effective_session_id and effective_session_id in _active_sessions:
                del _active_sessions[effective_session_id]
            await asyncio.sleep(0.1)
            if not bus.is_closed:
                bus.close()

    # Register EventBus for message injection (if session_id is known)
    if effective_session_id:
        _active_sessions[effective_session_id] = bus

    asyncio.create_task(run_chat())
    return EventSourceResponse(event_bus_to_sse(bus, request=raw_request))


@router.post("/chat/{session_id}/inject")
async def inject_message(session_id: str, body: dict, user: AuthUser = Depends(get_current_user)):
    """
    Inject a user message into a running session's conversation.

    The message will be picked up by the runtime on its next ReAct iteration,
    allowing real-time interaction with a running pipeline.

    Body: {"message": "user text", "files": [...]}
    """
    bus = _active_sessions.get(session_id)
    if not bus:
        return JSONResponse(
            status_code=404,
            content={"error": "NO_ACTIVE_SESSION", "message": "该会话当前没有运行中的 pipeline"},
        )

    if bus.is_closed:
        # Cleanup stale entry
        _active_sessions.pop(session_id, None)
        return JSONResponse(
            status_code=404,
            content={"error": "SESSION_CLOSED", "message": "该会话的 pipeline 已结束"},
        )

    message_text = body.get("message", "").strip()
    if not message_text:
        return JSONResponse(
            status_code=400,
            content={"error": "EMPTY_MESSAGE", "message": "消息内容不能为空"},
        )

    bus.inject_message({
        "message": message_text,
        "files": body.get("files", []),
    })

    return {"status": "injected", "session_id": session_id}


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
async def list_tools(user: AuthUser | None = Depends(get_current_user_optional)):
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
async def get_soul(user: AuthUser | None = Depends(get_current_user_optional)):
    """Return soul.md content for preview."""
    from pathlib import Path
    soul_path = Path(__file__).parent.parent / "prompts" / "soul.md"
    try:
        return {"content": soul_path.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"content": "(soul.md 文件未找到)"}
