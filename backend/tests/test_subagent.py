"""
A3 子Agent动态化 — 测试套件。

覆盖:
- SubagentRunner 基本执行
- 动态 prompt
- 工具白名单过滤
- 超时控制
- spawn_subagent 工具函数
- spawn_subagents 批量并行
"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from core.tool_registry import ToolRegistry


# ── Fixtures ──


@dataclass
class FakeRuntimeResult:
    final_answer: str = "done"
    iterations: int = 2
    tool_call_count: int = 1
    steps: list = None
    thinking: str = ""
    error: str = ""
    max_iterations_reached: bool = False

    def __post_init__(self):
        if self.steps is None:
            self.steps = []


def _make_registries():
    """Create shared + capability registries with dummy tools."""
    shared = ToolRegistry()
    capability = ToolRegistry()

    @shared.tool(description="计算器", read_only=True, name="arithmetic")
    async def arithmetic(expression: str) -> str:
        return str(eval(expression))

    @shared.tool(description="读引用", read_only=True, name="read_reference")
    async def read_reference(name: str) -> str:
        return f"ref: {name}"

    @capability.tool(description="读文件", read_only=True, name="read_source_file")
    async def read_source_file(path: str) -> str:
        return f"content of {path}"

    @capability.tool(description="写文件", read_only=False, name="write_source_file")
    async def write_source_file(path: str, content: str) -> str:
        return "ok"

    @capability.tool(description="运行命令", read_only=False, name="run_command")
    async def run_command(command: str) -> str:
        return "output"

    return shared, capability


def _make_runner(**overrides):
    """Create a SubagentRunner with mocked LLM."""
    from agent.subagent import SubagentRunner

    shared, capability = _make_registries()
    llm_client = MagicMock()

    return SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
        **overrides,
    )


# ── SubagentRunner Tests ──


class TestSubagentRunner:

    @pytest.mark.asyncio
    async def test_run_subagent_default_prompt(self):
        """无 prompt 时使用默认 prompt。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult(final_answer="结果A")
            MockRuntime.return_value = mock_runtime

            result = await runner.run_subagent(task="测试任务")

        assert result == "结果A"
        mock_runtime.run.assert_called_once()
        # 检查 system_prompt 包含默认 prompt
        call_args = mock_runtime.run.call_args
        system_prompt = call_args[0][0]
        assert "子智能体" in system_prompt

    @pytest.mark.asyncio
    async def test_run_subagent_custom_prompt(self):
        """传入自定义 prompt。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult(final_answer="OK")
            MockRuntime.return_value = mock_runtime

            result = await runner.run_subagent(
                task="验证数据",
                prompt="你是数据验证专家。检查所有数值计算。",
            )

        assert result == "OK"
        call_args = mock_runtime.run.call_args
        system_prompt = call_args[0][0]
        assert "数据验证专家" in system_prompt

    @pytest.mark.asyncio
    async def test_run_subagent_tool_whitelist(self):
        """工具白名单过滤。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(
                task="读代码",
                tools="arithmetic,read_source_file",
            )

        # 检查传入的 tool_registry 只包含白名单工具
        call_args = MockRuntime.call_args
        tool_registry = call_args[1]["tool_registry"]
        tool_names = set(tool_registry.get_tool_names())
        assert tool_names == {"arithmetic", "read_source_file"}

    @pytest.mark.asyncio
    async def test_run_subagent_empty_whitelist_uses_all(self):
        """空白名单使用全部工具。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="任务", tools="")

        call_args = MockRuntime.call_args
        tool_registry = call_args[1]["tool_registry"]
        tool_names = set(tool_registry.get_tool_names())
        assert len(tool_names) == 5  # 2 shared + 3 capability

    @pytest.mark.asyncio
    async def test_run_subagent_invalid_whitelist_falls_back(self):
        """白名单工具全部不存在，回退到全部工具。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(
                task="任务",
                tools="nonexistent_tool_1,nonexistent_tool_2",
            )

        call_args = MockRuntime.call_args
        tool_registry = call_args[1]["tool_registry"]
        assert len(tool_registry.get_tool_names()) == 5  # fallback to all

    @pytest.mark.asyncio
    async def test_run_subagent_timeout(self):
        """超时返回错误信息。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()

            async def slow_run(*args, **kwargs):
                await asyncio.sleep(10)
                return FakeRuntimeResult()

            mock_runtime.run.side_effect = slow_run
            MockRuntime.return_value = mock_runtime

            result = await runner.run_subagent(task="慢任务", timeout_s=1)

        assert "超时" in result

    @pytest.mark.asyncio
    async def test_run_subagent_exception(self):
        """运行时异常返回错误信息。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.side_effect = RuntimeError("LLM 连接失败")
            MockRuntime.return_value = mock_runtime

            result = await runner.run_subagent(task="失败任务")

        assert "执行失败" in result
        assert "LLM 连接失败" in result


# ── Tool Registry Build Tests ──


class TestToolRegistryBuild:

    def test_build_tool_registry_no_filter(self):
        """空 tools 参数返回全部工具。"""
        runner = _make_runner()
        registry = runner._build_tool_registry("")
        assert len(registry.get_tool_names()) == 5

    def test_build_tool_registry_with_filter(self):
        """逗号分隔白名单正确过滤。"""
        runner = _make_runner()
        registry = runner._build_tool_registry("arithmetic, read_source_file")
        names = set(registry.get_tool_names())
        assert names == {"arithmetic", "read_source_file"}

    def test_build_tool_registry_partial_match(self):
        """部分匹配（有的存在有的不存在）。"""
        runner = _make_runner()
        registry = runner._build_tool_registry("arithmetic,nonexistent")
        names = set(registry.get_tool_names())
        assert names == {"arithmetic"}

    def test_build_system_prompt_default(self):
        """默认 prompt 包含关键内容。"""
        runner = _make_runner()
        shared, cap = _make_registries()
        all_tools = shared.merge(cap)
        prompt = runner._build_system_prompt("", all_tools)
        assert "子智能体" in prompt
        assert "可用工具" in prompt

    def test_build_system_prompt_custom(self):
        """自定义 prompt 替换默认。"""
        runner = _make_runner()
        shared, cap = _make_registries()
        all_tools = shared.merge(cap)
        prompt = runner._build_system_prompt("你是审计专家", all_tools)
        assert "审计专家" in prompt
        assert "子智能体" not in prompt  # 默认 prompt 不应出现


# ── spawn_subagent Tool Tests ──


class TestSpawnSubagentTool:

    @pytest.mark.asyncio
    async def test_spawn_subagent_no_runner(self):
        """未注入 runner 时返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagent, _subagent_runner

        token = _subagent_runner.set(None)
        try:
            result = await spawn_subagent(task="test")
            assert "未初始化" in result
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagent_delegates(self):
        """正常调用委托给 runner。"""
        from tools.builtin.subagent_tools import spawn_subagent, _subagent_runner

        mock_runner = AsyncMock()
        mock_runner.run_subagent.return_value = "子任务结果"

        token = _subagent_runner.set(mock_runner)
        try:
            result = await spawn_subagent(
                task="检查数据",
                prompt="你是验证专家",
                tools="arithmetic",
                timeout_s=60,
            )
        finally:
            _subagent_runner.reset(token)

        assert result == "子任务结果"
        mock_runner.run_subagent.assert_called_once_with(
            task="检查数据",
            prompt="你是验证专家",
            tools="arithmetic",
            timeout_s=60,
        )


# ── spawn_subagents Tool Tests ──


class TestSpawnSubagentsTool:

    @pytest.mark.asyncio
    async def test_spawn_subagents_no_runner(self):
        """未注入 runner 时返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagents, _subagent_runner

        token = _subagent_runner.set(None)
        try:
            result = await spawn_subagents(tasks='[{"task":"test"}]')
            assert "未初始化" in result
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_invalid_json(self):
        """无效 JSON 返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagents, _subagent_runner

        mock_runner = AsyncMock()
        token = _subagent_runner.set(mock_runner)
        try:
            result = await spawn_subagents(tasks="not json")
            assert "JSON 解析失败" in result
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_empty_array(self):
        """空数组返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagents, _subagent_runner

        mock_runner = AsyncMock()
        token = _subagent_runner.set(mock_runner)
        try:
            result = await spawn_subagents(tasks="[]")
            assert "非空" in result
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_parallel(self):
        """并行执行多个子任务。"""
        from tools.builtin.subagent_tools import spawn_subagents, _subagent_runner

        call_count = 0

        async def mock_run(**kwargs):
            nonlocal call_count
            call_count += 1
            return f"结果{call_count}"

        mock_runner = AsyncMock()
        mock_runner.run_subagent.side_effect = mock_run

        token = _subagent_runner.set(mock_runner)
        try:
            tasks = json.dumps([
                {"task": "任务1", "prompt": "专家1"},
                {"task": "任务2"},
                {"task": "任务3", "tools": "arithmetic"},
            ])
            result = await spawn_subagents(tasks=tasks)
        finally:
            _subagent_runner.reset(token)

        assert mock_runner.run_subagent.call_count == 3
        assert "任务1" in result
        assert "任务2" in result
        assert "任务3" in result

    @pytest.mark.asyncio
    async def test_spawn_subagents_string_items(self):
        """支持简单字符串数组。"""
        from tools.builtin.subagent_tools import spawn_subagents, _subagent_runner

        mock_runner = AsyncMock()
        mock_runner.run_subagent.return_value = "OK"

        token = _subagent_runner.set(mock_runner)
        try:
            result = await spawn_subagents(tasks='["任务A","任务B"]')
        finally:
            _subagent_runner.reset(token)

        assert mock_runner.run_subagent.call_count == 2

    @pytest.mark.asyncio
    async def test_spawn_subagents_handles_exception(self):
        """某个子任务异常不影响其他。"""
        from tools.builtin.subagent_tools import spawn_subagents, _subagent_runner

        async def mock_run(**kwargs):
            if kwargs["task"] == "失败任务":
                raise RuntimeError("boom")
            return "成功"

        mock_runner = AsyncMock()
        mock_runner.run_subagent.side_effect = mock_run

        token = _subagent_runner.set(mock_runner)
        try:
            tasks = json.dumps([
                {"task": "正常任务"},
                {"task": "失败任务"},
            ])
            result = await spawn_subagents(tasks=tasks)
        finally:
            _subagent_runner.reset(token)

        assert "成功" in result
        assert "错误" in result or "boom" in result


# ── Registry Builder Tests ──


class TestRegistryBuilder:

    def test_no_review_in_capability_registry(self):
        """确认 parallel_review 已从 capability registry 移除。"""
        from tools.registry_builder import build_capability_registry

        registry = build_capability_registry()
        tool_names = set(registry.get_tool_names())
        assert "parallel_review" not in tool_names

    def test_spawn_subagents_in_registry(self):
        """确认 spawn_subagents 已注册。"""
        from tools.registry_builder import build_capability_registry

        registry = build_capability_registry()
        tool_names = set(registry.get_tool_names())
        assert "spawn_subagent" in tool_names
        assert "spawn_subagents" in tool_names
