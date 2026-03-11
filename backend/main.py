"""
Claw-for-SaaS AI Backend — FastAPI entry point.

Start:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

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
from api.file_routes import router as file_router
from core.logging import setup_logging
from api.hook_rule_routes import router as hook_rule_router
from api.plugin_routes import router as plugin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    setup_logging(level="INFO", format="console")
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

    logger.info("Agent Gateway routes mounted at /api")

    yield

    logger.info("Claw-for-SaaS backend shutting down...")

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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


@app.get("/")
async def root():
    return {
        "service": "Claw-for-SaaS Backend",
        "version": "0.1.0",
        "docs": "/docs",
    }
