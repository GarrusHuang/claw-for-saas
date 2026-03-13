"""
声明式 Hook 规则引擎 — Phase 12 (Hookify)。

将 JSON 声明式规则编译为 hook handler 函数，
实现"改配置不改代码"的 Hook 管理。

Usage:
    engine = HookRuleEngine("data/hook_rules")
    count = engine.register_all(hook_registry)
    print(f"Loaded {count} rules")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.hooks import HookEvent, HookRegistry, HookResult
from agent.safe_eval import safe_eval

logger = logging.getLogger(__name__)


@dataclass
class HookRule:
    """声明式 Hook 规则。"""
    rule_id: str
    name: str
    description: str = ""
    event_type: str = "pre_tool_use"  # pre_tool_use | post_tool_use | agent_stop
    matcher: str | None = None  # 工具名匹配 (可选)
    condition: str = ""  # Python 表达式 (safe_eval 沙箱)
    action: str = "block"  # block | modify | log
    message_template: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        """序列化为 dict。"""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "event_type": self.event_type,
            "matcher": self.matcher,
            "condition": self.condition,
            "action": self.action,
            "message_template": self.message_template,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HookRule:
        """从 dict 反序列化。"""
        return cls(
            rule_id=data.get("rule_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            event_type=data.get("event_type", "pre_tool_use"),
            matcher=data.get("matcher"),
            condition=data.get("condition", ""),
            action=data.get("action", "block"),
            message_template=data.get("message_template", ""),
            enabled=data.get("enabled", True),
        )


class HookRuleEngine:
    """
    声明式规则引擎。

    从 JSON 文件加载规则，编译为 hook handler 并注册到 HookRegistry。
    支持 CRUD 操作 + 安全条件评估。
    """

    def __init__(self, rules_dir: str = "data/hook_rules") -> None:
        self.rules_dir = Path(rules_dir)
        self.rules_dir.mkdir(parents=True, exist_ok=True)

    def load_rules(self) -> list[HookRule]:
        """从 JSON 文件加载所有规则。"""
        rules: list[HookRule] = []

        for json_file in sorted(self.rules_dir.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, list):
                    for item in data:
                        rule = HookRule.from_dict(item)
                        if rule.rule_id:
                            rules.append(rule)
                elif isinstance(data, dict):
                    rule = HookRule.from_dict(data)
                    if rule.rule_id:
                        rules.append(rule)

            except Exception as e:
                logger.error(f"Failed to load hook rules from {json_file}: {e}")

        logger.info(f"Loaded {len(rules)} hook rules from {self.rules_dir}")
        return rules

    def save_rule(self, rule: HookRule) -> None:
        """保存单个规则到 JSON 文件。"""
        rule_file = self.rules_dir / f"{rule.rule_id}.json"
        with open(rule_file, "w", encoding="utf-8") as f:
            json.dump(rule.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"Rule saved: {rule.rule_id}")

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则文件。"""
        rule_file = self.rules_dir / f"{rule_id}.json"
        if rule_file.exists():
            rule_file.unlink()
            logger.info(f"Rule deleted: {rule_id}")
            return True

        # 也尝试从 builtin.json 等多规则文件中删除
        for json_file in self.rules_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    original_len = len(data)
                    data = [item for item in data if item.get("rule_id") != rule_id]
                    if len(data) < original_len:
                        with open(json_file, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        logger.info(f"Rule {rule_id} removed from {json_file.name}")
                        return True
            except Exception:
                continue

        return False

    def get_rule(self, rule_id: str) -> HookRule | None:
        """按 rule_id 查找规则。"""
        for rule in self.load_rules():
            if rule.rule_id == rule_id:
                return rule
        return None

    def validate_rule(self, rule: HookRule) -> list[str]:
        """
        验证规则合法性。

        Returns:
            错误列表 (空列表 = 合法)
        """
        errors = []

        if not rule.rule_id:
            errors.append("rule_id 不能为空")
        if not rule.name:
            errors.append("name 不能为空")
        if rule.event_type not in ("pre_tool_use", "post_tool_use", "agent_stop", "pre_compact"):
            errors.append(f"event_type 不合法: {rule.event_type}")
        if rule.action not in ("block", "modify", "log"):
            errors.append(f"action 不合法: {rule.action}")

        # 验证 condition 安全性
        if rule.condition:
            try:
                # 用空上下文测试 condition 是否可编译
                safe_eval(rule.condition, {"event": None, "tool_input": {}})
            except ValueError as e:
                if "Forbidden" in str(e):
                    errors.append(f"condition 包含禁止的关键词: {e}")
            except Exception:
                pass  # 运行时错误在实际执行时处理

        return errors

    def compile_hook(self, rule: HookRule) -> Callable[[HookEvent], HookResult]:
        """将声明式规则编译为 hook handler 函数。"""

        def _handler(event: HookEvent) -> HookResult:
            # 条件评估
            if rule.condition:
                try:
                    ctx = {
                        "event": event,
                        "tool_input": event.tool_input,
                        "tool_name": event.tool_name,
                        "tool_output": event.tool_output,
                    }
                    if not safe_eval(rule.condition, ctx):
                        return HookResult(action="allow")
                except Exception as e:
                    logger.warning(f"Rule {rule.rule_id} condition eval failed: {e}")
                    return HookResult(action="allow")  # 条件评估失败 → 放行

            # 格式化消息
            message = rule.message_template
            if message:
                if "__" in message:
                    message = f"[Rule {rule.rule_id}] Action blocked"
                else:
                    try:
                        message = message.format(
                            tool_name=event.tool_name,
                            tool_input=event.tool_input,
                            rule_name=rule.name,
                            rule_id=rule.rule_id,
                        )
                    except (KeyError, IndexError, ValueError):
                        pass  # 模板变量缺失不影响

            # 根据 action 返回结果
            if rule.action == "block":
                return HookResult(action="block", message=message or f"Rule {rule.rule_id}: {rule.name}")
            elif rule.action == "log":
                logger.info(f"[RULE] {rule.rule_id}: {message or rule.name}")
                return HookResult(action="allow")
            elif rule.action == "modify":
                return HookResult(action="modify", message=message)
            else:
                return HookResult(action="allow")

        # 标记规则来源
        _handler.__rule_id__ = rule.rule_id  # type: ignore
        _handler.__rule_name__ = rule.name  # type: ignore
        return _handler

    def register_all(self, hook_registry: HookRegistry) -> int:
        """
        加载所有启用的规则并注册到 HookRegistry。

        Returns:
            注册的规则数量
        """
        rules = self.load_rules()
        count = 0

        for rule in rules:
            if not rule.enabled:
                logger.debug(f"Skipping disabled rule: {rule.rule_id}")
                continue

            # 验证规则
            errors = self.validate_rule(rule)
            if errors:
                logger.warning(f"Rule {rule.rule_id} validation failed: {errors}")
                continue

            handler = self.compile_hook(rule)
            hook_registry.register(rule.event_type, handler, matcher=rule.matcher)
            count += 1

        logger.info(f"Registered {count}/{len(rules)} hook rules")
        return count
