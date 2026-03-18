"""
ToolCallParser: 双模式工具调用解析。

支持两种模式，自动检测：
- Mode 1 (Primary): 原生 OpenAI tool_calls（vLLM --tool-call-parser hermes）
- Mode 2 (Fallback): Hermes XML <tool_call>JSON</tool_call> 格式

兼容多种 LLM 通过 vLLM 服务时的两种格式，Parser 透明处理。
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
    thinking: str = ""  # thinking 内容（如果有）


class ToolCallParser:
    """
    双模式工具调用解析器。

    解析策略：
    1. 检查 response 是否包含原生 tool_calls 数组 → Mode 1
    2. 检查 text 内容是否包含 <tool_call> XML → Mode 2
    3. 都没有 → 视为 final_answer
    """

    # Hermes XML — 提取 <tool_call>...</tool_call> 之间的原始内容
    _TOOL_CALL_TAG_PATTERN = re.compile(
        r"<tool_call>\s*(.*?)\s*</tool_call>",
        re.DOTALL,
    )
    # thinking 标签 (<think>...</think>)
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

        # 提取 thinking（thinking 模式）
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
                clean_content = re.sub(
                    r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL
                ).strip()
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

        部分 LLM (如 vLLM) 偶尔输出畸形 JSON:
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

        # 策略 5: 截断的 JSON 字符串修复
        # LLM 生成长 content 参数时 JSON 可能被截断，例如:
        # {"path": "output.py", "content": "import os\ndef main():\n    print(...
        # 尝试: 关闭未终结的字符串值 + 补全 }
        truncated_result = self._try_fix_truncated_json(s)
        if truncated_result is not None:
            logger.debug(f"Fixed truncated JSON: {args_str[:60]}...")
            return truncated_result

        # 所有策略失败
        raise ValueError(f"Cannot parse tool arguments: {args_str[:100]}")

    @staticmethod
    def _try_fix_truncated_json(s: str) -> dict | None:
        """
        尝试修复被截断的 JSON 参数。

        常见场景: write_source_file 的 content 参数很长，LLM 输出被 max_tokens 截断:
          {"path": "output.py", "content": "import os\ndef main():\n    print(
        策略: 逐步去掉尾部字符，尝试关闭字符串和对象。
        """
        if not s.startswith("{"):
            return None

        # 从尾部开始，找到最后一个完整的 key-value pair
        # 尝试在不同位置截断并修复
        for trim in range(0, min(len(s), 2000), 1):
            candidate = s if trim == 0 else s[:-trim]
            # 尝试: candidate + '"}'  (关闭字符串值 + 对象)
            for suffix in ('"}}', '"}', '"]}', '"}]}', '"}]}}'):
                try:
                    result = json.loads(candidate + suffix)
                    if isinstance(result, dict) and len(result) >= 1:
                        return result
                except json.JSONDecodeError:
                    continue
            # 尝试: candidate + '}'  (值不是字符串的情况)
            for suffix in ("}", "]}"):
                try:
                    result = json.loads(candidate + suffix)
                    if isinstance(result, dict) and len(result) >= 1:
                        return result
                except json.JSONDecodeError:
                    continue

        return None

    @staticmethod
    def _extract_balanced_json(text: str) -> str | None:
        """
        从文本中提取第一个平衡大括号的 JSON 对象。

        解决 {.*?} 正则在嵌套 JSON (如 arguments 包含嵌套 dict) 时
        截断的问题。
        """
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                if in_string:
                    escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    def _parse_hermes_xml(self, content: str) -> list[ParsedToolCall]:
        """解析 Hermes XML <tool_call>JSON</tool_call> 格式。"""
        parsed = []
        matches = self._TOOL_CALL_TAG_PATTERN.findall(content)

        for match in matches:
            try:
                # 使用平衡大括号提取，避免嵌套 JSON 截断
                json_str = self._extract_balanced_json(match)
                if not json_str:
                    logger.warning(f"No balanced JSON found in tool_call: {match[:100]}")
                    continue
                data = json.loads(json_str)
                name = data.get("name", "")
                arguments = data.get("arguments", data.get("parameters", {}))
                if name:
                    parsed.append(ParsedToolCall(
                        id=f"call_{uuid4().hex[:8]}",
                        name=name,
                        arguments=arguments,
                    ))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Hermes XML tool call: {e}, raw: {match[:100]}")
                continue

        return parsed
