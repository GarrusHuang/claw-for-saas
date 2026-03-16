"""
Claw Agent API routes.

Core endpoints:
- POST /api/chat — Agent Gateway chat (returns JSON, events via WebSocket)
- POST /api/chat/{session_id}/cancel — Cancel running pipeline
- GET /api/health — Health check
- GET /api/tools — List registered tools
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agent.gateway import SessionBusyError
from core.event_bus import EventBus
from core.ws_bridge import EventBusWSBridge
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
    processes it through the AgentGateway. Returns JSON with session_id and trace_id.
    Pipeline events are pushed via WebSocket (pipeline_event).
    """
    from dependencies import build_gateway, get_notification_manager

    # Generate request trace ID
    trace_id = uuid.uuid4().hex[:12]
    current_trace_id.set(trace_id)

    # Create EventBus
    bus = EventBus(trace_id=trace_id)

    # Build Gateway
    gateway = build_gateway()

    # Get notification manager for WS bridge
    nm = get_notification_manager()

    # Track the session_id for active session registration.
    effective_session_id = request.session_id

    # Wrap emit to auto-register on pipeline_started (captures new session_id)
    _original_emit = bus.emit

    def _tracking_emit(event_type: str, data: dict | None = None) -> None:
        nonlocal effective_session_id
        if event_type == "pipeline_started" and data and "session_id" in data:
            sid = data["session_id"]
            if sid != effective_session_id:
                if effective_session_id and effective_session_id in _active_sessions:
                    del _active_sessions[effective_session_id]
                effective_session_id = sid
                _active_sessions[sid] = bus
                # Update WSBridge session_id for correct routing
                if hasattr(bus, '_ws_bridge'):
                    bus._ws_bridge.session_id = sid
        _original_emit(event_type, data)

    bus.emit = _tracking_emit  # type: ignore[method-assign]

    # Run Gateway.chat in background task
    async def run_chat():
        nonlocal effective_session_id

        # Start WSBridge — subscribes to EventBus and forwards to WebSocket
        bridge = EventBusWSBridge(
            bus=bus,
            session_id=effective_session_id or trace_id,
            user_id=user.user_id,
            notification_manager=nm,
        )
        bus._ws_bridge = bridge  # type: ignore[attr-defined]
        bridge.start()

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
            effective_session_id = result.get("session_id", effective_session_id)
        except asyncio.CancelledError:
            # 即时取消 — 发 cancelled 事件，不改步骤状态
            if not bus.is_closed:
                bus.emit("pipeline_complete", {
                    "status": "cancelled",
                    "duration_ms": 0,
                    "summary": {"session_id": effective_session_id},
                })
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
            # Wait for bridge to finish forwarding remaining events
            try:
                await asyncio.wait_for(bridge._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                bridge.stop()
            except Exception:
                bridge.stop()
            # WebSocket 通知: 会话完成
            if effective_session_id:
                try:
                    await nm.notify_user(user.user_id, "session_completed", {
                        "session_id": effective_session_id,
                    })
                except Exception:
                    pass

    # Register EventBus for message injection (if session_id is known)
    if effective_session_id:
        _active_sessions[effective_session_id] = bus

    task = asyncio.create_task(run_chat())
    bus._chat_task = task  # type: ignore[attr-defined]

    return {
        "session_id": effective_session_id,
        "trace_id": trace_id,
    }


@router.get("/chat/running")
async def list_running_sessions(user: AuthUser = Depends(get_current_user)):
    """返回当前用户所有运行中的 session IDs。"""
    # _active_sessions 包含所有用户的 session，这里返回全部
    # （前端只用于恢复蓝点状态，安全性由 WS 事件路由保障）
    return {"session_ids": list(_active_sessions.keys())}


@router.post("/chat/{session_id}/cancel")
async def cancel_chat(session_id: str, user: AuthUser = Depends(get_current_user)):
    """Cancel a running pipeline by cancelling its asyncio Task."""
    bus = _active_sessions.get(session_id)
    if not bus:
        return JSONResponse(
            status_code=404,
            content={"error": "NO_ACTIVE_SESSION", "message": "该会话当前没有运行中的 pipeline"},
        )
    # 即时取消: cancel Task 让 CancelledError 在 await 点抛出
    chat_task = getattr(bus, '_chat_task', None)
    if chat_task and not chat_task.done():
        chat_task.cancel()
    return {"status": "cancelled", "session_id": session_id}


@router.post("/chat/{session_id}/inject")
async def inject_message(session_id: str, body: dict, user: AuthUser = Depends(get_current_user)):
    """
    Inject a user message into a running session's conversation.
    """
    bus = _active_sessions.get(session_id)
    if not bus:
        return JSONResponse(
            status_code=404,
            content={"error": "NO_ACTIVE_SESSION", "message": "该会话当前没有运行中的 pipeline"},
        )

    if bus.is_closed:
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


@router.get("/chat/{session_id}/events")
async def get_session_events(session_id: str, user: AuthUser = Depends(get_current_user)):
    """返回运行中 session 的 pipeline 状态快照（从 EventBus.history 计算）。"""
    bus = _active_sessions.get(session_id)
    if not bus:
        return JSONResponse(
            status_code=404,
            content={"error": "NO_ACTIVE_SESSION", "message": "该会话当前没有运行中的 pipeline"},
        )

    snapshot = _build_pipeline_snapshot(bus, session_id)
    return snapshot


def _build_pipeline_snapshot(bus: EventBus, session_id: str) -> dict:
    """从 EventBus.history 累积计算 pipeline 状态快照。"""
    streaming_text = ""
    thinking_text = ""
    tool_executions: list[dict] = []
    plan: dict | None = None
    plan_steps: list[dict] = []
    agent_message: str | None = None
    loaded_skills: list[str] = []
    agent_iteration: dict = {"current": 0, "max": 15}
    file_artifacts: list[dict] = []
    is_complete = False
    error: str | None = None
    # step status tracking: index → status
    step_status: dict[int, str] = {}

    for evt in bus.history:
        et = evt.event_type
        d = evt.data

        if et == "text_delta":
            streaming_text += d.get("content", "")
        elif et == "thinking":
            thinking_text += d.get("content", "")
        elif et == "tool_executed":
            tool_executions.append({
                "tool": d.get("tool", ""),
                "success": d.get("success", True),
                "latency_ms": d.get("latency_ms", 0),
                "args_summary": d.get("args_summary"),
                "result_summary": d.get("result_summary"),
                "blocked": d.get("blocked", False),
                "ts": evt.timestamp,
            })
        elif et == "plan_proposed":
            plan = {
                "summary": d.get("summary", ""),
                "steps": d.get("steps", []),
                "detail": d.get("detail", ""),
                "estimated_actions": d.get("estimated_actions", 0),
            }
        elif et == "step_started":
            idx = d.get("step_index", 0)
            step_status[idx] = "running"
        elif et == "step_completed":
            idx = d.get("step_index", 0)
            step_status[idx] = "completed"
        elif et == "step_failed":
            idx = d.get("step_index", 0)
            step_status[idx] = "failed"
        elif et == "agent_message":
            agent_message = d.get("content")
        elif et == "skills_loaded":
            loaded_skills = d.get("skills", [])
        elif et == "agent_progress":
            status = d.get("status", "")
            if status == "started":
                agent_iteration = {"current": 0, "max": d.get("max_iterations", 15)}
            elif status == "calling_tools":
                agent_iteration["current"] = d.get("iteration", agent_iteration["current"])
            elif status in ("completed", "max_iterations_reached"):
                agent_iteration["current"] = d.get("iterations", agent_iteration["current"])
        elif et == "file_artifact":
            file_artifacts.append({
                "path": d.get("path", ""),
                "filename": d.get("filename", ""),
                "size_bytes": d.get("size_bytes", 0),
                "content_type": d.get("content_type", "application/octet-stream"),
                "session_id": d.get("session_id", session_id),
            })
        elif et == "pipeline_complete":
            is_complete = True
        elif et == "error":
            error = d.get("message", "Unknown error")

    plan_steps_list = [{"index": idx, "status": st} for idx, st in sorted(step_status.items())]

    return {
        "session_id": session_id,
        "trace_id": bus.trace_id,
        "status": "completed" if is_complete else "running",
        "streaming_text": streaming_text,
        "thinking_text": thinking_text,
        "tool_executions": tool_executions,
        "plan": plan,
        "plan_steps": plan_steps_list,
        "agent_iteration": agent_iteration,
        "agent_message": agent_message,
        "loaded_skills": loaded_skills,
        "file_artifacts": file_artifacts,
        "is_complete": is_complete,
        "error": error,
    }


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
