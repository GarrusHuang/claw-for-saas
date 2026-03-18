"""
浏览器能力工具。

通过 contextvars 获取 BrowserService，
Agent 可访问外部网页，用于供应商核查/药品比价/发票验真/政策查询。

A6 集成: 访问前通过 SandboxManager.validate_url() 校验网络白名单。
所有工具为 read_only=True（只读取网页，不修改）。
"""

from __future__ import annotations

import logging

from core.context import current_event_bus, current_sandbox
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

browser_capability_registry = ToolRegistry()


def _get_browser_service():
    """从 contextvars 获取 BrowserService，并检查可用性。"""
    from core.context import current_browser_service
    service = current_browser_service.get()
    if service is None:
        raise RuntimeError("BrowserService not available (not injected)")
    if not service.is_available():
        raise RuntimeError(
            "浏览器工具不可用 — Playwright 浏览器未安装。"
            "请联系管理员运行 'playwright install chromium'。"
        )
    return service


def _validate_url(url: str) -> str | None:
    """
    A6: 通过 SandboxManager 验证 URL 安全性。

    Returns:
        None 如果允许，否则返回拒绝原因。
    """
    sandbox = current_sandbox.get(None)
    if sandbox is None:
        return None  # 无 sandbox 时不阻止 (由 security_hooks 兜底)
    return sandbox.validate_url(url)


def _emit_event(event_type: str, data: dict):
    """发射 SSE 事件 (EventBus.emit 是同步的)。"""
    bus = current_event_bus.get()
    if bus:
        try:
            bus.emit(event_type, data)
        except Exception:
            pass


@browser_capability_registry.tool(
    description="Open a URL and return page title, final URL and HTTP status. "
                "Use this for supplier verification, policy lookup, or any web access. "
                "Example: open_url(url='https://www.example.com')",
    read_only=True,
)
async def open_url(url: str) -> dict:
    """打开网页，返回标题/URL/状态码。"""
    # A6: URL 安全校验
    reject = _validate_url(url)
    if reject:
        raise RuntimeError(f"URL 访问被拒绝: {reject}")

    service = _get_browser_service()
    result = await service.open_page(url)

    _emit_event('browser_action', {
        'action': 'open_url',
        'url': result.get('url', url),
        'title': result.get('title', ''),
        'status': result.get('status', 0),
    })

    if 'error' in result:
        raise RuntimeError(result['error'])

    return result


@browser_capability_registry.tool(
    description="Take a screenshot of a web page and return it as base64 PNG. "
                "Use this to capture visual evidence of web content. "
                "Example: page_screenshot(url='https://www.example.com')",
    read_only=True,
)
async def page_screenshot(url: str) -> dict:
    """对网页截图，返回 base64 PNG。"""
    reject = _validate_url(url)
    if reject:
        raise RuntimeError(f"URL 访问被拒绝: {reject}")

    service = _get_browser_service()
    result = await service.screenshot(url)

    _emit_event('browser_screenshot', {
        'action': 'screenshot',
        'url': result.get('url', url),
        'title': result.get('title', ''),
        'has_screenshot': bool(result.get('screenshot_base64')),
    })

    if 'error' in result:
        raise RuntimeError(result['error'])

    return result


@browser_capability_registry.tool(
    description="Extract text content from a web page (up to 5000 characters). "
                "Use this to read web page content for analysis, comparison, or verification. "
                "Example: page_extract_text(url='https://www.example.com')",
    read_only=True,
)
async def page_extract_text(url: str) -> dict:
    """提取网页文本内容。"""
    reject = _validate_url(url)
    if reject:
        raise RuntimeError(f"URL 访问被拒绝: {reject}")

    service = _get_browser_service()
    result = await service.extract_text(url)

    _emit_event('browser_action', {
        'action': 'extract_text',
        'url': result.get('url', url),
        'title': result.get('title', ''),
        'text_length': len(result.get('text', '')),
    })

    if 'error' in result:
        raise RuntimeError(result['error'])

    return result
