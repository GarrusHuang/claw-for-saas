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
    async def test_run_subagent_invalid_whitelist_returns_empty(self):
        """白名单工具全部不存在，返回空 registry (不回退)。"""
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
        assert len(tool_registry.get_tool_names()) == 0  # empty, respects whitelist

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
        from tools.builtin.subagent_tools import spawn_subagent
        from core.context import RequestContext, current_request

        ctx = RequestContext(subagent_runner=None)
        token = current_request.set(ctx)
        try:
            result = await spawn_subagent(task="test")
            assert "未初始化" in result
        finally:
            current_request.reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagent_delegates(self):
        """正常调用委托给 runner。"""
        from tools.builtin.subagent_tools import spawn_subagent
        from core.context import RequestContext, current_request

        mock_runner = AsyncMock()
        mock_runner.run_subagent.return_value = "子任务结果"

        ctx = RequestContext(subagent_runner=mock_runner)
        token = current_request.set(ctx)
        try:
            result = await spawn_subagent(
                task="检查数据",
                prompt="你是验证专家",
                tools="arithmetic",
                timeout_s=60,
            )
        finally:
            current_request.reset(token)

        assert result == "子任务结果"
        mock_runner.run_subagent.assert_called_once_with(
            task="检查数据",
            prompt="你是验证专家",
            tools="arithmetic",
            timeout_s=60,
            inherit_context=False,
        )


# ── spawn_subagents Tool Tests ──


class TestSpawnSubagentsTool:

    def _set_runner(self, runner):
        from core.context import RequestContext, current_request
        ctx = RequestContext(subagent_runner=runner, user_id="U1", subagent_depth=0)
        return current_request.set(ctx)

    def _reset(self, token):
        from core.context import current_request
        current_request.reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_no_runner(self):
        """未注入 runner 时返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagents

        token = self._set_runner(None)
        try:
            result = await spawn_subagents(tasks='[{"task":"test"}]')
            assert "未初始化" in result
        finally:
            self._reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_invalid_json(self):
        """无效 JSON 返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagents

        token = self._set_runner(AsyncMock())
        try:
            result = await spawn_subagents(tasks="not json")
            assert "JSON 解析失败" in result
        finally:
            self._reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_empty_array(self):
        """空数组返回错误。"""
        from tools.builtin.subagent_tools import spawn_subagents

        token = self._set_runner(AsyncMock())
        try:
            result = await spawn_subagents(tasks="[]")
            assert "非空" in result
        finally:
            self._reset(token)

    @pytest.mark.asyncio
    async def test_spawn_subagents_parallel(self):
        """并行执行多个子任务 (start+wait 模式)。"""
        from tools.builtin.subagent_tools import spawn_subagents

        call_count = 0

        async def mock_start(**kwargs):
            nonlocal call_count
            call_count += 1
            return f"sa_{call_count}"

        async def mock_wait(agent_id, timeout_s=120):
            idx = agent_id.split("_")[1]
            return f"结果{idx}"

        mock_runner = AsyncMock()
        mock_runner.start_subagent.side_effect = mock_start
        mock_runner.wait_subagent.side_effect = mock_wait

        token = self._set_runner(mock_runner)
        try:
            tasks = json.dumps([
                {"task": "任务1", "prompt": "专家1"},
                {"task": "任务2"},
                {"task": "任务3", "tools": "arithmetic"},
            ])
            result = await spawn_subagents(tasks=tasks)
        finally:
            self._reset(token)

        assert mock_runner.start_subagent.call_count == 3
        assert "任务1" in result
        assert "任务2" in result
        assert "任务3" in result

    @pytest.mark.asyncio
    async def test_spawn_subagents_string_items(self):
        """支持简单字符串数组。"""
        from tools.builtin.subagent_tools import spawn_subagents

        mock_runner = AsyncMock()
        mock_runner.start_subagent.return_value = "sa_1"
        mock_runner.wait_subagent.return_value = "OK"

        token = self._set_runner(mock_runner)
        try:
            result = await spawn_subagents(tasks='["任务A","任务B"]')
        finally:
            self._reset(token)

        assert mock_runner.start_subagent.call_count == 2

    @pytest.mark.asyncio
    async def test_spawn_subagents_handles_exception(self):
        """某个子任务异常不影响其他 (start+wait 模式)。"""
        from tools.builtin.subagent_tools import spawn_subagents

        call_idx = 0

        async def mock_start(**kwargs):
            nonlocal call_idx
            call_idx += 1
            return f"sa_{call_idx}"

        async def mock_wait(agent_id, timeout_s=120):
            if agent_id == "sa_2":
                return "子智能体执行失败: boom"
            return "成功"

        mock_runner = AsyncMock()
        mock_runner.start_subagent.side_effect = mock_start
        mock_runner.wait_subagent.side_effect = mock_wait

        token = self._set_runner(mock_runner)
        try:
            tasks = json.dumps([
                {"task": "正常任务"},
                {"task": "失败任务"},
            ])
            result = await spawn_subagents(tasks=tasks)
        finally:
            self._reset(token)

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


# ── A4-4h Subagent Context Isolation Tests ──


class TestSubagentContextIsolation:
    """A4-4h: 验证子智能体上下文隔离 — 独立 config / 工具集 / prompt / 执行。"""

    @pytest.mark.asyncio
    async def test_separate_runtime_config(self):
        """子智能体创建独立的 RuntimeConfig(max_iterations=15)，不复用父级。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="测试任务")

        # 验证 RuntimeConfig 是新创建的，max_iterations=15
        call_kwargs = MockRuntime.call_args[1]
        config = call_kwargs["config"]
        assert config.max_iterations == 15
        assert config.max_tokens_per_turn == 4096

    @pytest.mark.asyncio
    async def test_config_independent_from_parent(self):
        """每次调用 run_subagent 都创建新的 RuntimeConfig 实例。"""
        from core.runtime import RuntimeConfig

        runner = _make_runner()

        configs_seen = []

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="任务1")
            configs_seen.append(MockRuntime.call_args[1]["config"])

            await runner.run_subagent(task="任务2")
            configs_seen.append(MockRuntime.call_args[1]["config"])

        # 两次调用应该创建不同的 config 实例
        assert configs_seen[0] is not configs_seen[1]
        # 但值相同
        assert configs_seen[0].max_iterations == configs_seen[1].max_iterations == 15

    @pytest.mark.asyncio
    async def test_separate_tool_registry_with_whitelist(self):
        """白名单过滤产生的工具集与父级 shared/capability registry 不同。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="任务", tools="arithmetic")

        child_registry = MockRuntime.call_args[1]["tool_registry"]
        child_names = set(child_registry.get_tool_names())

        # 子智能体只有白名单中的工具
        assert child_names == {"arithmetic"}

        # 父级 registry 未被修改
        parent_shared_names = set(runner.shared_registry.get_tool_names())
        parent_cap_names = set(runner.capability_registry.get_tool_names())
        assert len(parent_shared_names) == 2  # arithmetic, read_reference
        assert len(parent_cap_names) == 3  # read_source_file, write_source_file, run_command

    @pytest.mark.asyncio
    async def test_separate_tool_registry_is_new_instance(self):
        """子智能体的工具 registry 是新实例，不是父级引用。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="任务", tools="arithmetic,read_source_file")

        child_registry = MockRuntime.call_args[1]["tool_registry"]

        # 子智能体 registry 不是父级的 shared 或 capability registry
        assert child_registry is not runner.shared_registry
        assert child_registry is not runner.capability_registry

    @pytest.mark.asyncio
    async def test_separate_system_prompt_dynamic(self):
        """子智能体使用动态传入的 prompt，不是父级 prompt。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(
                task="分析数据",
                prompt="你是财务分析专家，专注于数据准确性。",
            )

        call_args = mock_runtime.run.call_args[0]
        system_prompt = call_args[0]
        assert "财务分析专家" in system_prompt
        # 不应包含默认子智能体 prompt
        assert "负责执行分配的子任务" not in system_prompt

    @pytest.mark.asyncio
    async def test_separate_system_prompt_default(self):
        """不传 prompt 时使用默认子智能体 prompt，而非父级。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="简单任务")

        call_args = mock_runtime.run.call_args[0]
        system_prompt = call_args[0]
        assert "负责执行分配的子任务" in system_prompt

    @pytest.mark.asyncio
    async def test_separate_system_prompt_with_prompt_builder(self):
        """有 PromptBuilder 时，子智能体用 minimal 模式构建基础 prompt。"""
        mock_pb = MagicMock()
        mock_pb.build_system_prompt.return_value = "MINIMAL_BASE"

        runner = _make_runner(prompt_builder=mock_pb)

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="任务", prompt="自定义角色")

        # PromptBuilder 以 minimal 模式调用
        mock_pb.build_system_prompt.assert_called_once_with(mode="minimal")

        system_prompt = mock_runtime.run.call_args[0][0]
        assert "MINIMAL_BASE" in system_prompt
        assert "自定义角色" in system_prompt

    @pytest.mark.asyncio
    async def test_independent_execution_with_asyncio(self):
        """子智能体通过 asyncio.wait_for 独立执行，支持超时。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult(final_answer="独立完成")
            MockRuntime.return_value = mock_runtime

            with patch("agent.subagent.asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                mock_wait.return_value = FakeRuntimeResult(final_answer="独立完成")

                result = await runner.run_subagent(task="独立任务", timeout_s=60)

                # 验证 asyncio.wait_for 被调用，带正确的超时
                mock_wait.assert_called_once()
                _, kwargs = mock_wait.call_args
                assert kwargs["timeout"] == 60

        assert result == "独立完成"

    @pytest.mark.asyncio
    async def test_independent_runtime_per_call(self):
        """每次 run_subagent 创建独立的 AgenticRuntime 实例。"""
        runner = _make_runner()

        runtimes_created = []

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()

            def capture_runtime(*args, **kwargs):
                instance = AsyncMock()
                instance.run.return_value = FakeRuntimeResult()
                runtimes_created.append(instance)
                return instance

            MockRuntime.side_effect = capture_runtime

            await runner.run_subagent(task="任务A")
            await runner.run_subagent(task="任务B")

        # 两次调用创建了两个独立的 runtime
        assert len(runtimes_created) == 2
        assert runtimes_created[0] is not runtimes_created[1]

    @pytest.mark.asyncio
    async def test_child_tool_parser_is_independent(self):
        """子智能体获得独立的 ToolCallParser 实例。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult()
            MockRuntime.return_value = mock_runtime

            await runner.run_subagent(task="任务")

        call_kwargs = MockRuntime.call_args[1]
        tool_parser = call_kwargs["tool_parser"]

        # 验证 ToolCallParser 被传入
        from core.tool_protocol import ToolCallParser
        assert isinstance(tool_parser, ToolCallParser)


# ── 3.3 Multi-Agent 生命周期增强 Tests ──


class TestSubagentLifecycle:
    """3.3: start/wait/send + depth limit + 并发控制。"""

    @pytest.mark.asyncio
    async def test_depth_limit(self):
        """depth >= MAX_DEPTH 时拒绝。"""
        runner = _make_runner()
        result = await runner.start_subagent(
            task="深层任务", depth=3, user_id="test_user_depth",
        )
        assert "错误" in result
        assert "深度" in result

    @pytest.mark.asyncio
    async def test_depth_within_limit(self):
        """depth < MAX_DEPTH 时正常启动。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult(final_answer="OK")
            MockRuntime.return_value = mock_runtime

            result = await runner.start_subagent(
                task="浅层任务", depth=2, user_id="test_user_shallow",
            )
        assert result.startswith("sa_")

    @pytest.mark.asyncio
    async def test_concurrent_guard(self):
        """同用户第 4 个并发 subagent 被拒绝。"""
        from agent.subagent import _user_semaphores, _MAX_CONCURRENT_PER_USER
        runner = _make_runner()
        user_id = "test_user_concurrent"

        # 清理可能残留的信号量
        _user_semaphores.pop(user_id, None)

        started_ids = []

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()

            async def slow_run(*args, **kwargs):
                await asyncio.sleep(10)  # 保持运行
                return FakeRuntimeResult(final_answer="done")

            mock_runtime.run.side_effect = slow_run
            MockRuntime.return_value = mock_runtime

            # 启动 3 个 (应成功)
            for i in range(3):
                aid = await runner.start_subagent(
                    task=f"任务{i}", depth=0, user_id=user_id,
                )
                assert aid.startswith("sa_"), f"第 {i+1} 个应成功: {aid}"
                started_ids.append(aid)

            # 第 4 个应失败
            result = await runner.start_subagent(
                task="任务3", depth=0, user_id=user_id,
            )
            assert "错误" in result
            assert "上限" in result

        # 清理: 取消运行中的任务
        for aid in started_ids:
            running = runner._running.get(aid)
            if running:
                running.task.cancel()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_wait_subagent_success(self):
        """wait_subagent 成功获取结果。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()
            mock_runtime.run.return_value = FakeRuntimeResult(final_answer="完成结果")
            MockRuntime.return_value = mock_runtime

            agent_id = await runner.start_subagent(
                task="快速任务", depth=0, user_id="test_wait_ok",
            )
            assert agent_id.startswith("sa_")

            result = await runner.wait_subagent(agent_id, timeout_s=5)
            assert result == "完成结果"

    @pytest.mark.asyncio
    async def test_wait_subagent_not_found(self):
        """wait_subagent 找不到 agent_id。"""
        runner = _make_runner()
        result = await runner.wait_subagent("sa_nonexistent", timeout_s=1)
        assert "错误" in result
        assert "不存在" in result

    @pytest.mark.asyncio
    async def test_wait_subagent_timeout(self):
        """wait_subagent 超时。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()

            async def slow_run(*args, **kwargs):
                await asyncio.sleep(10)
                return FakeRuntimeResult()

            mock_runtime.run.side_effect = slow_run
            MockRuntime.return_value = mock_runtime

            agent_id = await runner.start_subagent(
                task="慢任务", depth=0, user_id="test_wait_timeout",
            )

            result = await runner.wait_subagent(agent_id, timeout_s=0.1)
            assert "超时" in result

        # 清理
        running = runner._running.get(agent_id)
        if running:
            running.task.cancel()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_send_to_subagent_success(self):
        """send_to_subagent 成功发送消息。"""
        runner = _make_runner()

        with patch("agent.subagent.AgenticRuntime") as MockRuntime:
            mock_runtime = AsyncMock()

            async def slow_run(*args, **kwargs):
                await asyncio.sleep(5)
                return FakeRuntimeResult()

            mock_runtime.run.side_effect = slow_run
            MockRuntime.return_value = mock_runtime

            agent_id = await runner.start_subagent(
                task="交互任务", depth=0, user_id="test_send_ok",
            )

            result = await runner.send_to_subagent(agent_id, "新指令")
            assert "已发送" in result

        # 清理
        running = runner._running.get(agent_id)
        if running:
            running.task.cancel()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_send_to_subagent_not_found(self):
        """send_to_subagent 找不到 agent_id。"""
        runner = _make_runner()
        result = await runner.send_to_subagent("sa_nonexistent", "消息")
        assert "错误" in result
        assert "不存在" in result


# ── 3.3 spawn_subagent wait=False Tests ──


class TestSpawnSubagentWaitFalse:

    @pytest.mark.asyncio
    async def test_spawn_wait_true_compat(self):
        """wait=True (默认) 行为不变。"""
        from tools.builtin.subagent_tools import spawn_subagent
        from core.context import RequestContext, current_request

        mock_runner = AsyncMock()
        mock_runner.run_subagent.return_value = "同步结果"

        ctx = RequestContext(subagent_runner=mock_runner)
        token = current_request.set(ctx)
        try:
            result = await spawn_subagent(task="测试", wait=True)
        finally:
            current_request.reset(token)

        assert result == "同步结果"
        mock_runner.run_subagent.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_wait_false(self):
        """wait=False 返回 agent_id。"""
        from tools.builtin.subagent_tools import spawn_subagent
        from core.context import RequestContext, current_request

        mock_runner = AsyncMock()
        mock_runner.start_subagent.return_value = "sa_abc123"

        ctx = RequestContext(subagent_runner=mock_runner, user_id="U001", subagent_depth=0)
        token = current_request.set(ctx)
        try:
            result = await spawn_subagent(task="测试", wait=False)
        finally:
            current_request.reset(token)

        assert result == "sa_abc123"
        mock_runner.start_subagent.assert_called_once()


# ── 3.3 wait_subagent / send_to_subagent Tool Tests ──


class TestWaitSendTools:

    @pytest.mark.asyncio
    async def test_wait_subagent_tool(self):
        """wait_subagent 工具调用。"""
        from tools.builtin.subagent_tools import wait_subagent
        from core.context import RequestContext, current_request

        mock_runner = AsyncMock()
        mock_runner.wait_subagent.return_value = "子任务完成"

        ctx = RequestContext(subagent_runner=mock_runner)
        token = current_request.set(ctx)
        try:
            result = await wait_subagent(agent_id="sa_test", timeout_s=30)
        finally:
            current_request.reset(token)

        assert result == "子任务完成"

    @pytest.mark.asyncio
    async def test_send_to_subagent_tool(self):
        """send_to_subagent 工具调用。"""
        from tools.builtin.subagent_tools import send_to_subagent
        from core.context import RequestContext, current_request

        mock_runner = AsyncMock()
        mock_runner.send_to_subagent.return_value = "消息已发送"

        ctx = RequestContext(subagent_runner=mock_runner)
        token = current_request.set(ctx)
        try:
            result = await send_to_subagent(agent_id="sa_test", message="新指令")
        finally:
            current_request.reset(token)

        assert result == "消息已发送"
