"""
交互工具 — Agent 向用户请求输入/确认。

通过 EventBus 发射 request_input / request_confirmation 事件，
前端 InteractiveMessage 组件渲染交互 UI，用户回复通过 inject 端点注入。
"""

from __future__ import annotations

import logging

from core.context import get_request_context
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

interaction_capability_registry = ToolRegistry()


@interaction_capability_registry.tool(
    description=(
        "向用户提问获取信息或请求确认。"
        "有 options (逗号分隔) 时显示按钮选择，无 options 时显示文本输入框。"
        "调用后应停止输出，等待用户回复 (回复会作为下一轮用户消息出现)。"
        "仅在缺少关键信息或需要用户在多方案中选择时使用。"
    ),
    read_only=False,
)
def request_user_input(
    question: str,           # 问题文本
    options: str = "",       # 逗号分隔选项 (有选项→按钮模式, 无→文本输入)
    input_type: str = "text",  # 输入类型 (text/number/email)
) -> dict:
    """向用户提问获取信息，通过 EventBus 发射交互事件。"""
    ctx = get_request_context()
    bus = ctx.event_bus

    if bus is None:
        return {"error": "EventBus not available — cannot request user input"}

    if options:
        # 按钮选择模式
        option_list = [
            {"label": o.strip(), "value": o.strip()}
            for o in options.split(",")
            if o.strip()
        ]
        bus.emit("request_confirmation", {
            "message": question,
            "options": option_list,
        })
    else:
        # 文本输入模式
        bus.emit("request_input", {
            "prompt": question,
            "field_type": input_type,
        })

    return {"status": "waiting_for_user", "question": question}
