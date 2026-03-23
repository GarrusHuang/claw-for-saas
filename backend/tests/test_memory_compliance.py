"""Tests for check_memory_compliance — quality gate memory preference check."""
import sys
import os
from unittest.mock import MagicMock, patch
import contextvars

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.hooks import HookEvent
from agent.quality_gate import check_memory_compliance, QualityGate
from core.context import RequestContext, current_request


def _make_event(final_answer: str = "", **kwargs) -> HookEvent:
    return HookEvent(
        event_type="agent_stop",
        session_id=kwargs.get("session_id", "S1"),
        user_id=kwargs.get("user_id", "U1"),
        runtime_steps=[],
        context={"final_answer": final_answer},
    )


def _run_with_memory(final_answer: str, memory_content: str) -> tuple[bool, str, str]:
    """Helper: 设置 RequestContext 并运行 check_memory_compliance。"""
    mock_store = MagicMock()
    mock_store.build_memory_prompt.return_value = (memory_content, {})

    ctx = RequestContext(memory_store=mock_store, tenant_id="default", user_id="U1")
    token = current_request.set(ctx)
    try:
        event = _make_event(final_answer=final_answer)
        return check_memory_compliance(event)
    finally:
        current_request.reset(token)


class TestCheckMemoryCompliance:
    """check_memory_compliance 单元测试。"""

    def test_no_memory_store_passes(self):
        """没有 memory store 时应通过。"""
        ctx = RequestContext(memory_store=None)
        token = current_request.set(ctx)
        try:
            event = _make_event(final_answer="Hello world, this is a test")
            passed, _, _ = check_memory_compliance(event)
            assert passed is True
        finally:
            current_request.reset(token)

    def test_empty_final_answer_passes(self):
        """空 final_answer 时应通过。"""
        event = _make_event(final_answer="")
        passed, _, _ = check_memory_compliance(event)
        assert passed is True

    def test_table_preference_violated(self):
        """记忆要求表格格式但回复无表格 → 不通过。"""
        passed, issue, correction = _run_with_memory(
            final_answer="这是一个普通的文本回复，没有任何表格",
            memory_content="用户偏好: 使用表格格式输出数据",
        )
        assert passed is False
        assert "表格" in issue
        assert correction

    def test_table_preference_satisfied(self):
        """记忆要求表格格式且回复包含表格 → 通过。"""
        passed, _, _ = _run_with_memory(
            final_answer="| 项目 | 金额 |\n|------|------|\n| A | 100 |",
            memory_content="用户偏好: 使用表格格式",
        )
        assert passed is True

    def test_chinese_preference_violated(self):
        """记忆要求中文回复但全英文 → 不通过。"""
        passed, issue, _ = _run_with_memory(
            final_answer="This is a long English response that does not contain any Chinese characters at all.",
            memory_content="用户偏好: 使用中文回复",
        )
        assert passed is False
        assert "中文" in issue

    def test_chinese_preference_satisfied(self):
        """记忆要求中文且回复包含中文 → 通过。"""
        passed, _, _ = _run_with_memory(
            final_answer="这是一个中文回复，包含了用户需要的信息。",
            memory_content="用户偏好: 使用中文回复",
        )
        assert passed is True

    def test_deny_pattern_violated(self):
        """记忆说"不要使用缩写"但回复包含缩写 → 不通过。"""
        passed, issue, _ = _run_with_memory(
            final_answer="请参考 API 文档中关于缩写的定义",
            memory_content="用户要求: 不要使用缩写，应使用全称",
        )
        assert passed is False
        assert "缩写" in issue

    def test_no_preferences_in_memory(self):
        """记忆中无特定偏好 → 通过。"""
        passed, _, _ = _run_with_memory(
            final_answer="A normal response with nothing special.",
            memory_content="上次对话讨论了天气。用户喜欢编程。",
        )
        assert passed is True

    def test_empty_memory_passes(self):
        """记忆内容为空 → 通过。"""
        passed, _, _ = _run_with_memory(
            final_answer="Some response",
            memory_content="",
        )
        assert passed is True

    def test_memory_store_exception_passes(self):
        """memory store 抛异常时应通过 (不影响整体流程)。"""
        mock_store = MagicMock()
        mock_store.build_memory_prompt.side_effect = Exception("DB error")
        ctx = RequestContext(memory_store=mock_store)
        token = current_request.set(ctx)
        try:
            event = _make_event(final_answer="Some response")
            passed, _, _ = check_memory_compliance(event)
            assert passed is True
        finally:
            current_request.reset(token)

    def test_quality_gate_with_memory_check(self):
        """验证 check_memory_compliance 可以作为 QualityGate check 使用。"""
        gate = QualityGate(checks=[check_memory_compliance])
        event = _make_event(final_answer="")
        result = gate.evaluate(event)
        # Empty final_answer → passes
        assert result.passed is True

    def test_short_ascii_passes_chinese_check(self):
        """短英文（<= 20字符）不触发中文偏好检查。"""
        passed, _, _ = _run_with_memory(
            final_answer="OK, done.",
            memory_content="用户偏好: 使用中文回复",
        )
        assert passed is True

    def test_multiple_violations(self):
        """同时违反多个偏好 → 所有问题合并报告。"""
        passed, issue, correction = _run_with_memory(
            final_answer="This is a long English text reply without any table format whatsoever and nothing special.",
            memory_content="用户偏好: 使用表格格式，使用中文回复",
        )
        assert passed is False
        assert "表格" in issue
        assert "中文" in issue
