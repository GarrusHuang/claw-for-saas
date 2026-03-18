"""
Claw-for-SaaS AI Backend — FastAPI entry point.

Start:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.auth import router as auth_router
from api.admin import router as admin_router
from api.routes import router as agent_router
from api.session_routes import router as session_router
from api.correction_routes import router as correction_router
from api.memory_routes import router as memory_router
from api.skill_routes import router as skill_router
from api.file_routes import router as file_router, workspace_router
from core.logging import setup_logging
from api.hook_rule_routes import router as hook_rule_router
from api.plugin_routes import router as plugin_router
from api.schedule_routes import router as schedule_router
from api.webhook_routes import router as webhook_router
from api.usage_routes import router as usage_admin_router
from api.my_usage_routes import router as my_usage_router
from api.knowledge_routes import router as knowledge_router
from api.ws_routes import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    from dependencies import get_settings as _get_settings
    _s = _get_settings()
    setup_logging(level=_s.log_level, format=_s.log_format)
    logger = logging.getLogger(__name__)
    logger.info("Claw-for-SaaS backend starting...")

    # Initialize database (creates default tenant + admin if needed)
    from dependencies import get_database
    get_database()
    logger.info("Database initialized")

    # Load plugins
    from dependencies import get_plugin_registry
    plugin_registry = get_plugin_registry()
    plugin_count = len(plugin_registry.list_plugins())
    if plugin_count:
        logger.info(f"Loaded {plugin_count} plugins")

    # Cleanup orphan session locks (from previous crashes)
    from dependencies import get_session_manager
    sm = get_session_manager()
    orphan_count = sm.cleanup_orphan_locks()
    if orphan_count:
        logger.info(f"Cleaned {orphan_count} orphan session locks")

    # Start scheduler (A9)
    from dependencies import get_scheduler, get_settings
    s = get_settings()
    if s.scheduler_enabled:
        scheduler = get_scheduler()
        await scheduler.start()
        logger.info("Scheduler started")

    # Start file cleanup background task
    file_cleanup_task = None
    if s.file_retention_days > 0:
        async def _file_cleanup_loop():
            """启动立即执行一次，之后每 6 小时清理过期的用户上传文件。"""
            from dependencies import get_file_service
            first_run = True
            while True:
                try:
                    if not first_run:
                        await asyncio.sleep(6 * 3600)  # 6 小时
                    first_run = False
                    svc = get_file_service()
                    deleted = svc.cleanup_expired(s.file_retention_days)
                    if deleted:
                        logger.info(f"File cleanup: removed {deleted} expired files")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"File cleanup error: {e}")
                    if first_run:
                        first_run = False  # 防止首次失败后无限重试
                    await asyncio.sleep(60)  # 出错等 60s 再继续

        file_cleanup_task = asyncio.create_task(_file_cleanup_loop())
        logger.info(f"File cleanup enabled: retention={s.file_retention_days} days, interval=6h")

    logger.info("Agent Gateway routes mounted at /api")

    yield

    logger.info("Claw-for-SaaS backend shutting down...")

    # Stop file cleanup
    if file_cleanup_task and not file_cleanup_task.done():
        file_cleanup_task.cancel()
        try:
            await file_cleanup_task
        except asyncio.CancelledError:
            pass

    # Stop scheduler (A9)
    try:
        if s.scheduler_enabled:
            await scheduler.stop()
            logger.info("Scheduler stopped")
    except Exception:
        pass

    try:
        from dependencies import _llm_client_instance
        if _llm_client_instance is not None:
            await _llm_client_instance.close()
            logger.info("LLMGatewayClient closed")
    except Exception:
        pass

    try:
        from dependencies import _browser_service
        if _browser_service is not None:
            await _browser_service.close()
            logger.info("BrowserService closed")
    except Exception:
        pass


app = FastAPI(
    title="Claw-for-SaaS Backend",
    description="AI Agent runtime for SaaS",
    version="0.1.0",
    lifespan=lifespan,
)

from config import settings as _settings

_cors_origins = [o.strip() for o in _settings.cors_allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(agent_router)
app.include_router(session_router)
app.include_router(correction_router)
app.include_router(memory_router)
app.include_router(skill_router)
app.include_router(file_router)
app.include_router(hook_rule_router)
app.include_router(plugin_router)
app.include_router(schedule_router)
app.include_router(webhook_router)
app.include_router(usage_admin_router)
app.include_router(my_usage_router)
app.include_router(knowledge_router)
app.include_router(workspace_router)
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "service": "Claw-for-SaaS Backend",
        "version": "0.1.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=_settings.app_host,
        port=_settings.app_port,
        reload=_settings.app_debug,
    )
