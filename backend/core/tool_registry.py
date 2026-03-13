"""
ToolRegistry: 装饰器注册 + 类型提示自动 schema 提取。

借鉴 agent-engine 的 ToolRegistry 模式：
- @registry.tool() 装饰器注册函数为工具
- 从 Python 类型提示自动提取 OpenAI function calling schema
- 支持 read_only 标记（可并行执行）
- 支持 merge() 合并多个 registry（共享工具 + Agent 专有工具）

Usage:
    registry = ToolRegistry()

    @registry.tool(description="比较两个数值", read_only=True)
    async def numeric_compare(actual: float, limit: float, op: str = "lte") -> dict:
        '''Compare actual against limit using the specified operator.'''
        ops = {"lte": actual <= limit, "gte": actual >= limit, "eq": actual == limit}
        return {"pass": ops[op], "actual": actual, "limit": limit, "diff": actual - limit}
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Union, get_args, get_origin, get_type_hints

logger = logging.getLogger(__name__)

# ─── 最低保留字符数 ───
_MIN_TRUNCATE_CHARS = 2000


def smart_truncate(text: str, max_chars: int) -> str:
    """
    智能 head+tail 截断 (A4: 4a)。

    策略:
    1. 检测尾部是否有重要内容 (错误信息、JSON 闭合、总结段落)
    2. 有 → 30% 给尾部, 70% 给头部
    3. 无 → 全部给头部
    4. 中间插入 "[...truncated N chars...]" 标记
    """
    if len(text) <= max_chars:
        return text

    # 小预算时直接简单截断 (不强制拉高到 _MIN_TRUNCATE_CHARS)
    if max_chars < _MIN_TRUNCATE_CHARS:
        return text[:max_chars] + "...[truncated]"

    marker_template = "\n...[truncated {} chars]...\n"

    # 检测尾部是否包含重要内容
    tail_500 = text[-500:] if len(text) > 500 else text
    has_important_tail = any(sig in tail_500 for sig in (
        '"error"', '"Error"', '"status"', '"total"', '"summary"',
        "Exception", "Traceback", "错误", "失败", "总计",
        "}", "]",  # JSON 闭合标签
    ))

    if has_important_tail:
        # 30% 尾部, 70% 头部
        tail_budget = int(max_chars * 0.3)
        head_budget = max_chars - tail_budget - 40  # 40 for marker
    else:
        # 全部给头部
        head_budget = max_chars - 40
        tail_budget = 0

    head_budget = max(head_budget, 200)
    truncated_count = len(text) - head_budget - tail_budget
    marker = marker_template.format(truncated_count)

    if tail_budget > 0:
        return text[:head_budget] + marker + text[-tail_budget:]
    else:
        return text[:head_budget] + marker


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: str | None = None

    def to_json(self, max_chars: int = 0) -> str:
        """
        序列化为 JSON 字符串 (A4: 智能 head+tail 截断)。

        Args:
            max_chars: 最大字符数限制。0 表示不限制（向后兼容）。
                       超出时使用 head+tail 策略截断。
        """
        if self.success:
            raw = json.dumps(self.data, ensure_ascii=False, default=str)
        else:
            raw = json.dumps({"error": self.error}, ensure_ascii=False)

        if max_chars > 0 and len(raw) > max_chars:
            return smart_truncate(raw, max_chars)
        return raw


@dataclass
class RegisteredTool:
    """注册的工具定义"""
    name: str
    description: str
    func: Callable
    schema: dict
    read_only: bool = False


class ToolRegistry:
    """
    装饰器注册 + 类型提示自动 Schema 提取的工具注册表。

    支持：
    - 从函数签名自动提取参数 schema（类型、默认值、required）
    - 从 Literal 类型提取 enum 值
    - 从 Optional 类型标记为非必需
    - read_only 标记（用于并行执行判断）
    - merge() 合并多个 registry
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def tool(
        self,
        description: str | None = None,
        read_only: bool = False,
        name: str | None = None,
    ) -> Callable:
        """装饰器：注册一个函数为工具。"""

        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            tool_desc = description or func.__doc__ or f"Tool: {tool_name}"
            schema = self._extract_schema(func, tool_name, tool_desc)
            self._tools[tool_name] = RegisteredTool(
                name=tool_name,
                description=tool_desc,
                func=func,
                schema=schema,
                read_only=read_only,
            )
            return func

        return decorator

    def register(
        self,
        func: Callable,
        description: str | None = None,
        read_only: bool = False,
        name: str | None = None,
    ) -> None:
        """命令式注册（非装饰器）。"""
        tool_name = name or func.__name__
        tool_desc = description or func.__doc__ or f"Tool: {tool_name}"
        schema = self._extract_schema(func, tool_name, tool_desc)
        self._tools[tool_name] = RegisteredTool(
            name=tool_name,
            description=tool_desc,
            func=func,
            schema=schema,
            read_only=read_only,
        )

    def _extract_schema(self, func: Callable, tool_name: str, tool_desc: str) -> dict:
        """从函数签名提取 OpenAI function calling schema。"""
        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}
        sig = inspect.signature(func)
        properties: dict[str, dict] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            hint = hints.get(param_name, str)
            prop = self._type_to_json_schema(hint)

            # 提取参数描述（从函数源码的内联注释）
            param_desc = self._get_param_description(func, param_name)
            if param_desc:
                prop["description"] = param_desc

            # 判断 required
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            elif param.default is not None:
                prop["default"] = param.default

            properties[param_name] = prop

        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _type_to_json_schema(self, hint: Any) -> dict:
        """将 Python 类型提示转换为 JSON Schema 类型。"""
        origin = get_origin(hint)
        args = get_args(hint)

        # Optional[X] -> X 但非 required
        if origin is Union:
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                return self._type_to_json_schema(non_none[0])

        # Literal["a", "b", "c"] -> enum
        if origin is Literal:
            return {"type": "string", "enum": list(args)}

        # list[X] -> array
        if origin is list:
            items = self._type_to_json_schema(args[0]) if args else {"type": "string"}
            return {"type": "array", "items": items}

        # dict -> object
        if origin is dict or hint is dict:
            return {"type": "object"}

        # 基本类型映射
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
        }

        if hint in type_map:
            return {"type": type_map[hint]}

        # 默认 string
        return {"type": "string"}

    def _get_param_description(self, func: Callable, param_name: str) -> str | None:
        """尝试从源码内联注释提取参数描述。"""
        try:
            source = inspect.getsource(func)
            for line in source.split("\n"):
                stripped = line.strip()
                # 匹配 "param_name: Type,  # description" 格式
                if re.search(rf'\b{re.escape(param_name)}\b', stripped) and "#" in stripped:
                    comment = stripped.split("#", 1)[1].strip()
                    return comment
        except (OSError, TypeError):
            pass
        return None

    def list_tools(self) -> list[RegisteredTool]:
        """返回所有已注册工具。"""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """返回所有工具的 OpenAI function calling schema 列表。"""
        return [tool.schema for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """返回所有已注册工具名称。"""
        return list(self._tools.keys())

    def get_tool(self, name: str) -> RegisteredTool | None:
        """获取指定工具的定义。"""
        return self._tools.get(name)

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        """执行指定工具。"""
        tool = self._tools.get(name)
        if not tool:
            logger.warning(f"Unknown tool: {name}")
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        try:
            logger.info(f"Executing tool: {name}", extra={"arguments": arguments})
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(**arguments)
            else:
                result = tool.func(**arguments)
            return ToolResult(success=True, data=result)
        except TypeError as e:
            logger.error(f"Tool {name} argument error: {e}")
            return ToolResult(success=False, error=f"Invalid arguments for {name}: {e}")
        except Exception as e:
            logger.error(f"Tool {name} execution error: {e}")
            return ToolResult(success=False, error=f"Tool {name} failed: {e}")

    def is_read_only(self, name: str) -> bool:
        """判断工具是否为只读（可并行执行）。"""
        tool = self._tools.get(name)
        return tool.read_only if tool else False

    def merge(self, other: ToolRegistry) -> ToolRegistry:
        """合并另一个 registry，返回新 registry（other 优先）。"""
        merged = ToolRegistry()
        merged._tools = {**self._tools, **other._tools}
        return merged

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        tools_str = ", ".join(self._tools.keys())
        return f"ToolRegistry(tools=[{tools_str}])"
