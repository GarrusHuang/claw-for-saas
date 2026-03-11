"""Tests for agent/hook_rules.py — declarative hook rule engine."""
import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.hook_rules import HookRule, HookRuleEngine
from agent.hooks import HookEvent, HookRegistry


# ── HookRule ──


class TestHookRule:
    def test_to_dict(self):
        rule = HookRule(rule_id="r1", name="Test Rule", action="block")
        d = rule.to_dict()
        assert d["rule_id"] == "r1"
        assert d["enabled"] is True

    def test_from_dict(self):
        data = {"rule_id": "r2", "name": "Rule 2", "action": "log", "enabled": False}
        rule = HookRule.from_dict(data)
        assert rule.rule_id == "r2"
        assert rule.action == "log"
        assert rule.enabled is False

    def test_from_dict_defaults(self):
        rule = HookRule.from_dict({"rule_id": "r3", "name": "R3"})
        assert rule.event_type == "pre_tool_use"
        assert rule.action == "block"
        assert rule.enabled is True

    def test_roundtrip(self):
        rule = HookRule(rule_id="r1", name="Test", condition="len(tool_input) > 0")
        restored = HookRule.from_dict(rule.to_dict())
        assert restored.rule_id == rule.rule_id
        assert restored.condition == rule.condition


# ── HookRuleEngine CRUD ──


class TestHookRuleEngineCRUD:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.engine = HookRuleEngine(rules_dir=str(tmp_path / "rules"))

    def test_save_and_load(self):
        rule = HookRule(rule_id="r1", name="Test Rule")
        self.engine.save_rule(rule)
        rules = self.engine.load_rules()
        assert len(rules) == 1
        assert rules[0].rule_id == "r1"

    def test_get_rule(self):
        self.engine.save_rule(HookRule(rule_id="r1", name="R1"))
        self.engine.save_rule(HookRule(rule_id="r2", name="R2"))
        rule = self.engine.get_rule("r2")
        assert rule is not None
        assert rule.name == "R2"

    def test_get_rule_not_found(self):
        assert self.engine.get_rule("nonexistent") is None

    def test_delete_rule_single_file(self):
        self.engine.save_rule(HookRule(rule_id="r1", name="R1"))
        assert self.engine.delete_rule("r1") is True
        assert self.engine.load_rules() == []

    def test_delete_rule_from_array_file(self):
        # Write a multi-rule JSON file
        rules_file = self.engine.rules_dir / "batch.json"
        data = [
            {"rule_id": "r1", "name": "R1"},
            {"rule_id": "r2", "name": "R2"},
        ]
        with open(rules_file, "w") as f:
            json.dump(data, f)

        assert self.engine.delete_rule("r1") is True
        rules = self.engine.load_rules()
        assert len(rules) == 1
        assert rules[0].rule_id == "r2"

    def test_delete_nonexistent(self):
        assert self.engine.delete_rule("nope") is False

    def test_load_array_file(self):
        rules_file = self.engine.rules_dir / "batch.json"
        data = [
            {"rule_id": "r1", "name": "R1"},
            {"rule_id": "r2", "name": "R2"},
        ]
        with open(rules_file, "w") as f:
            json.dump(data, f)

        rules = self.engine.load_rules()
        assert len(rules) == 2

    def test_load_ignores_invalid_json(self):
        bad_file = self.engine.rules_dir / "bad.json"
        bad_file.write_text("not json")
        rules = self.engine.load_rules()
        assert rules == []

    def test_load_ignores_empty_rule_id(self):
        rules_file = self.engine.rules_dir / "empty_id.json"
        with open(rules_file, "w") as f:
            json.dump({"rule_id": "", "name": "No ID"}, f)
        rules = self.engine.load_rules()
        assert rules == []


# ── Validation ──


class TestValidateRule:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.engine = HookRuleEngine(rules_dir=str(tmp_path / "rules"))

    def test_valid_rule(self):
        rule = HookRule(rule_id="r1", name="Test")
        errors = self.engine.validate_rule(rule)
        assert errors == []

    def test_missing_rule_id(self):
        rule = HookRule(rule_id="", name="Test")
        errors = self.engine.validate_rule(rule)
        assert any("rule_id" in e for e in errors)

    def test_missing_name(self):
        rule = HookRule(rule_id="r1", name="")
        errors = self.engine.validate_rule(rule)
        assert any("name" in e for e in errors)

    def test_invalid_event_type(self):
        rule = HookRule(rule_id="r1", name="Test", event_type="invalid")
        errors = self.engine.validate_rule(rule)
        assert any("event_type" in e for e in errors)

    def test_invalid_action(self):
        rule = HookRule(rule_id="r1", name="Test", action="destroy")
        errors = self.engine.validate_rule(rule)
        assert any("action" in e for e in errors)

    def test_forbidden_condition(self):
        rule = HookRule(rule_id="r1", name="Test", condition="__import__('os')")
        errors = self.engine.validate_rule(rule)
        assert any("禁止" in e for e in errors)

    def test_valid_condition(self):
        rule = HookRule(rule_id="r1", name="Test", condition="len(tool_input) > 0")
        errors = self.engine.validate_rule(rule)
        assert errors == []

    def test_valid_event_types(self):
        for et in ("pre_tool_use", "post_tool_use", "agent_stop", "pre_compact"):
            rule = HookRule(rule_id="r1", name="Test", event_type=et)
            errors = self.engine.validate_rule(rule)
            assert not any("event_type" in e for e in errors)


# ── compile_hook ──


class TestCompileHook:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.engine = HookRuleEngine(rules_dir=str(tmp_path / "rules"))

    def _event(self, tool_input: dict | None = None) -> HookEvent:
        return HookEvent(
            event_type="pre_tool_use",
            tool_name="test_tool",
            tool_input=tool_input or {},
        )

    def test_block_action(self):
        rule = HookRule(rule_id="r1", name="Block All", action="block")
        handler = self.engine.compile_hook(rule)
        result = handler(self._event())
        assert result.action == "block"

    def test_log_action(self):
        rule = HookRule(rule_id="r1", name="Log All", action="log")
        handler = self.engine.compile_hook(rule)
        result = handler(self._event())
        assert result.action == "allow"  # log → allow

    def test_modify_action(self):
        rule = HookRule(rule_id="r1", name="Modify", action="modify", message_template="modified")
        handler = self.engine.compile_hook(rule)
        result = handler(self._event())
        assert result.action == "modify"

    def test_condition_true_blocks(self):
        rule = HookRule(
            rule_id="r1", name="Cond Block",
            action="block",
            condition="len(tool_input) > 0",
        )
        handler = self.engine.compile_hook(rule)
        result = handler(self._event({"key": "val"}))
        assert result.action == "block"

    def test_condition_false_allows(self):
        rule = HookRule(
            rule_id="r1", name="Cond Block",
            action="block",
            condition="len(tool_input) > 0",
        )
        handler = self.engine.compile_hook(rule)
        result = handler(self._event({}))
        assert result.action == "allow"

    def test_condition_error_allows(self):
        rule = HookRule(
            rule_id="r1", name="Bad Cond",
            action="block",
            condition="undefined_var > 0",
        )
        handler = self.engine.compile_hook(rule)
        result = handler(self._event())
        assert result.action == "allow"  # Eval error → allow

    def test_message_template_formatting(self):
        rule = HookRule(
            rule_id="r1", name="Templated",
            action="block",
            message_template="Blocked {tool_name} by {rule_name}",
        )
        handler = self.engine.compile_hook(rule)
        result = handler(self._event())
        assert "test_tool" in result.message
        assert "Templated" in result.message

    def test_handler_has_rule_id(self):
        rule = HookRule(rule_id="r1", name="Test")
        handler = self.engine.compile_hook(rule)
        assert handler.__rule_id__ == "r1"


# ── register_all ──


class TestRegisterAll:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.engine = HookRuleEngine(rules_dir=str(tmp_path / "rules"))

    def test_register_enabled_rules(self):
        self.engine.save_rule(HookRule(rule_id="r1", name="R1"))
        self.engine.save_rule(HookRule(rule_id="r2", name="R2", enabled=False))
        registry = HookRegistry()
        count = self.engine.register_all(registry)
        assert count == 1

    def test_skip_invalid_rules(self):
        self.engine.save_rule(HookRule(rule_id="", name="No ID"))
        registry = HookRegistry()
        count = self.engine.register_all(registry)
        assert count == 0

    def test_register_with_matcher(self):
        self.engine.save_rule(HookRule(rule_id="r1", name="R1", matcher="open_url"))
        registry = HookRegistry()
        count = self.engine.register_all(registry)
        assert count == 1
