"""
安全表达式评估器 — Phase 12。

白名单内建函数沙箱，禁止 import/exec/eval/__dunder__。
用于 Hook 规则引擎的条件表达式评估。

Usage:
    result = safe_eval("tool_input.get('field_id','').endswith('amount')", {"tool_input": {...}})
"""

from __future__ import annotations

import builtins

ALLOWED_BUILTINS = {
    "len", "int", "float", "str", "bool", "abs", "min", "max",
    "isinstance", "round", "sum", "any", "all", "sorted", "list",
    "dict", "set", "tuple", "type", "range", "enumerate", "zip",
    "True", "False", "None",
}

# 直接子串匹配即可检测的 (如 __ 出现在任何位置都危险)
FORBIDDEN_SUBSTRINGS = ["__"]

# 必须作为独立标识符匹配的关键词 (避免 "tool_input" 误匹配 "input")
FORBIDDEN_IDENTIFIERS = [
    "import", "exec", "eval", "compile", "open",
    "globals", "locals", "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit", "help",
    "classmethod", "staticmethod", "property", "super",
    "vars", "dir", "memoryview", "bytearray",
]


def _is_forbidden_identifier(expression: str, identifier: str) -> bool:
    """检查 identifier 是否作为独立标识符出现在 expression 中。"""
    import re
    return bool(re.search(r'\b' + re.escape(identifier) + r'\b', expression))


def safe_eval(expression: str, context: dict | None = None) -> bool:
    """
    安全评估 Python 表达式。

    Args:
        expression: Python 表达式字符串
        context: 表达式可访问的变量上下文

    Returns:
        表达式评估结果 (布尔值)

    Raises:
        ValueError: 表达式包含禁止的关键词
        Exception: 表达式评估失败
    """
    if not expression or not expression.strip():
        return True  # 空条件视为 True

    # 子串安全检查 (__ 等)
    for forbidden in FORBIDDEN_SUBSTRINGS:
        if forbidden in expression:
            raise ValueError(f"Forbidden keyword in expression: {forbidden}")

    # 独立标识符安全检查 (使用 word boundary 避免误匹配)
    for forbidden in FORBIDDEN_IDENTIFIERS:
        if _is_forbidden_identifier(expression, forbidden):
            raise ValueError(f"Forbidden keyword in expression: {forbidden}")

    # 构建安全的内建函数白名单
    safe_builtins = {}
    for name in ALLOWED_BUILTINS:
        if hasattr(builtins, name):
            safe_builtins[name] = getattr(builtins, name)

    # 添加 True/False/None
    safe_builtins["True"] = True
    safe_builtins["False"] = False
    safe_builtins["None"] = None

    # 评估环境
    eval_globals = {"__builtins__": safe_builtins}
    eval_locals = dict(context or {})

    try:
        result = eval(expression, eval_globals, eval_locals)  # noqa: S307
        return bool(result)
    except Exception as e:
        raise ValueError(f"Expression evaluation failed: {expression!r} — {e}") from e
