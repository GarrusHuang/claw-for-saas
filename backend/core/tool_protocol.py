"""
ToolCallParser: 双模式工具调用解析。

支持两种模式，自动检测：
- Mode 1 (Primary): 原生 OpenAI tool_calls（vLLM --tool-call-parser hermes）
- Mode 2 (Fallback): Hermes XML <tool_call>JSON</tool_call> 格式

Qwen3 模型通过 vLLM 服务时支持两种格式，Parser 透明处理两种情况。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class ParsedToolCall:
    """解析出的工具调用"""
    id: str
    name: str
    arguments: dict

    def __repr__(self) -> str:
        return f"ToolCall({self.name}, args={self.arguments})"


@dataclass
class ParsedResponse:
    """LLM 响应解析结果"""
    is_final_answer: bool
    content: str = ""
    tool_calls: list[ParsedToolCall] = field(default_factory=list)
    raw_content: str = ""  # 原始 LLM 输出（含 tool_call 标签）
    thinking: str = ""  # Qwen3 thinking 内容（如果有）


class ToolCallParser:
    """
    双模式工具调用解析器。

    解析策略：
    1. 检查 response 是否包含原生 tool_calls 数组 → Mode 1
    2. 检查 text 内容是否包含 <tool_call> XML → Mode 2
    3. 都没有 → 视为 final_answer
    """

    # Hermes XML 格式正则
    _TOOL_CALL_PATTERN = re.compile(
        r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
        re.DOTALL,
    )
    # Qwen3 thinking 标签
    _THINKING_PATTERN = re.compile(
        r"<think>(.*?)</think>",
        re.DOTALL,
    )

    def parse(self, response: dict) -> ParsedResponse:
        """
        解析 LLM 响应。

        Args:
            response: OpenAI Chat Completion 响应的 message 对象
                      可以是 dict 或带 tool_calls 属性的对象

        Returns:
            ParsedResponse 包含 is_final_answer、content 和 tool_calls
        """
        # 提取 message 内容
        content = self._get_content(response)
        tool_calls_native = self._get_native_tool_calls(response)

        # 提取 thinking（Qwen3 thinking 模式）
        thinking = ""
        if content:
            think_match = self._THINKING_PATTERN.search(content)
            if think_match:
                thinking = think_match.group(1).strip()
                # 从 content 中移除 thinking 标签
                content = self._THINKING_PATTERN.sub("", content).strip()

        # Mode 1: 原生 OpenAI tool_calls
        if tool_calls_native:
            parsed_calls = self._parse_native(tool_calls_native)
            if parsed_calls:
                return ParsedResponse(
                    is_final_answer=False,
                    content=content,
                    tool_calls=parsed_calls,
                    raw_content=content,
                    thinking=thinking,
                )

        # Mode 2: Hermes XML 格式
        if content and "<tool_call>" in content:
            parsed_calls = self._parse_hermes_xml(content)
            if parsed_calls:
                # 提取非 tool_call 的文本作为 reasoning
                clean_content = self._TOOL_CALL_PATTERN.sub("", content).strip()
                return ParsedResponse(
                    is_final_answer=False,
                    content=clean_content,
                    tool_calls=parsed_calls,
                    raw_content=content,
                    thinking=thinking,
                )

        # Mode 3: 没有工具调用 → final answer
        return ParsedResponse(
            is_final_answer=True,
            content=content or "",
            raw_content=content or "",
            thinking=thinking,
        )

    def _get_content(self, response: dict) -> str:
        """从响应中提取 text content。"""
        if isinstance(response, dict):
            return response.get("content", "") or ""
        return getattr(response, "content", "") or ""

    def _get_native_tool_calls(self, response: dict) -> list | None:
        """从响应中提取原生 tool_calls 数组。"""
        if isinstance(response, dict):
            return response.get("tool_calls")
        return getattr(response, "tool_calls", None)

    def _parse_native(self, tool_calls: list) -> list[ParsedToolCall]:
        """解析原生 OpenAI tool_calls 数组。"""
        parsed = []
        for tc in tool_calls:
            try:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    call_id = tc.get("id", f"call_{uuid4().hex[:8]}")
                    name = func.get("name", "")
                    args_str = func.get("arguments", "{}")
                else:
                    call_id = getattr(tc, "id", f"call_{uuid4().hex[:8]}")
                    func = getattr(tc, "function", None)
                    name = getattr(func, "name", "") if func else ""
                    args_str = getattr(func, "arguments", "{}") if func else "{}"

                # 解析 arguments JSON
                if isinstance(args_str, str):
                    arguments = self._safe_parse_arguments(args_str)
                else:
                    arguments = args_str or {}

                if name:
                    parsed.append(ParsedToolCall(id=call_id, name=name, arguments=arguments))
            except (json.JSONDecodeError, AttributeError, ValueError) as e:
                logger.warning(f"Failed to parse native tool call: {e}, raw: {tc}")
                continue

        return parsed

    def _safe_parse_arguments(self, args_str: str) -> dict:
        """
        安全解析工具调用参数 JSON。

        部分 LLM (如 vLLM Qwen3) 偶尔输出畸形 JSON:
        - 缺少开头 `{`: '"user_id": "U001"}'
        - 缺少结尾 `}`: '{"user_id": "U001"'
        - 缺少两端 `{}`: '"user_id": "U001"'

        本方法尝试多种策略修复。
        """
        if not args_str or not args_str.strip():
            return {}

        s = args_str.strip()

        # 策略 1: 直接解析
        try:
            result = json.loads(s)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 策略 2: 补全缺少的 {}
        if not s.startswith("{"):
            s_fixed = "{" + s
            try:
                result = json.loads(s_fixed)
                if isinstance(result, dict):
                    logger.debug(f"Fixed missing opening brace: {args_str[:60]}")
                    return result
            except json.JSONDecodeError:
                pass

        if not s.endswith("}"):
            s_fixed = s + "}"
            try:
                result = json.loads(s_fixed)
                if isinstance(result, dict):
                    logger.debug(f"Fixed missing closing brace: {args_str[:60]}")
                    return result
            except json.JSONDecodeError:
                pass

        # 策略 3: 两端都补
        if not s.startswith("{") and not s.endswith("}"):
            s_fixed = "{" + s + "}"
            try:
                result = json.loads(s_fixed)
                if isinstance(result, dict):
                    logger.debug(f"Fixed missing both braces: {args_str[:60]}")
                    return result
            except json.JSONDecodeError:
                pass

        # 策略 4: 内容已经是正确 JSON 但被引号包裹
        if s.startswith('"') and s.endswith('"'):
            try:
                inner = json.loads(s)
                if isinstance(inner, str):
                    result = json.loads("{" + inner + "}")
                    if isinstance(result, dict):
                        return result
            except json.JSONDecodeError:
                pass

        # 所有策略失败
        raise ValueError(f"Cannot parse tool arguments: {args_str[:100]}")

    def _parse_hermes_xml(self, content: str) -> list[ParsedToolCall]:
        """解析 Hermes XML <tool_call>JSON</tool_call> 格式。"""
        parsed = []
        matches = self._TOOL_CALL_PATTERN.findall(content)

        for match in matches:
            try:
                data = json.loads(match)
                name = data.get("name", "")
                arguments = data.get("arguments", data.get("parameters", {}))
                if name:
                    parsed.append(ParsedToolCall(
                        id=f"call_{uuid4().hex[:8]}",
                        name=name,
                        arguments=arguments,
                    ))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Hermes XML tool call: {e}, raw: {match}")
                continue

        return parsed
