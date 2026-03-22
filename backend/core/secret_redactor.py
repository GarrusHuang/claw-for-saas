"""
Secret 输出脱敏器。

在工具结果发送给 LLM 前，自动替换已知 secret 值和常见 secret 模式。

Usage:
    redactor = SecretRedactor()
    redactor.collect_from_settings(settings)
    safe_text = redactor.redact("API key is sk-abc123def456...")
"""

from __future__ import annotations

import re


class SecretRedactor:
    """Secret 输出脱敏器。"""

    # 通用 secret 正则模式
    _PATTERNS: list[tuple[str, str]] = [
        # Bearer token
        (r"(?i)(Bearer\s+)[A-Za-z0-9\-._~+/]{20,}=*", r"\1[REDACTED]"),
        # OpenAI-style API key
        (r"sk-[A-Za-z0-9]{20,}", "[REDACTED_API_KEY]"),
        # AWS access key
        (r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]"),
        # Generic key=value patterns for sensitive keys
        (r"(?i)(password|passwd|secret|api_key|apikey|access_token)\s*[=:]\s*\S+",
         r"\1=[REDACTED]"),
    ]

    def __init__(self) -> None:
        self._literals: list[tuple[str, str]] = []  # (secret_value, label)
        self._compiled_patterns = [
            (re.compile(p), r) for p, r in self._PATTERNS
        ]

    def collect_from_settings(self, settings: object) -> None:
        """从 Settings 对象收集已知 secret 值。"""
        candidates = [
            (getattr(settings, "llm_api_key", ""), "API_KEY"),
            (getattr(settings, "auth_jwt_secret", ""), "JWT_SECRET"),
        ]
        for value, label in candidates:
            if value and len(value) >= 8 and value != "not-needed":
                self._literals.append((value, f"[REDACTED_{label}]"))
        # 按长度降序排列，避免短 secret 先匹配导致长 secret 部分残留
        self._literals.sort(key=lambda x: -len(x[0]))

    def add_secret(self, value: str, label: str = "SECRET") -> None:
        """手动添加需要脱敏的 secret 值。"""
        if value and len(value) >= 5:
            self._literals.append((value, f"[REDACTED_{label}]"))
            self._literals.sort(key=lambda x: -len(x[0]))

    def redact(self, text: str) -> str:
        """
        脱敏文本: 先替换已知字面值，再匹配正则模式。

        Args:
            text: 原始文本

        Returns:
            脱敏后的文本
        """
        if not text:
            return text
        # 字面值替换 (精确匹配，高优先级)
        for secret, label in self._literals:
            text = text.replace(secret, label)
        # 正则模式匹配 (通用兜底)
        for pattern, replacement in self._compiled_patterns:
            text = pattern.sub(replacement, text)
        return text
