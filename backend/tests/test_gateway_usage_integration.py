"""
Integration tests: Gateway.chat() → UsageService.record_pipeline.

Verifies that Gateway step 14 (A10 usage recording) works correctly
without requiring a real LLM. All LLM and runtime behaviour is mocked.

Covers:
  1. Successful pipeline → record_pipeline called with status="success"
  2. Failed pipeline → record_pipeline called with status="failed"
  3. record_pipeline throws → gateway still returns result (silent failure)
  4. Tool names extracted and deduplicated from steps
  5. All fields passed correctly (tenant_id, user_id, tokens, etc.)
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch, ANY

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.runtime import RuntimeResult, RuntimeConfig, RuntimeStep, StepType
from core.llm_client import LLMGatewayClient, LLMClientConfig, TokenUsage
from core.tool_registry import ToolRegistry
from agent.gateway import AgentGateway
from agent.prompt import PromptBuilder
from agent.session import SessionManager
from agent.subagent import SubagentRunner
from agent.hooks import HookRegistry
from memory.markdown_store import MarkdownMemoryStore
from skills.loader import SkillLoader


def _make_runtime_result(
    *,
    final_answer: str = "Done.",
    error: str | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
    iterations: int = 2,
    steps: list[RuntimeStep] | None = None,
    thinking: str = "",
) -> RuntimeResult:
    """Helper to build a RuntimeResult with controlled values."""
    return RuntimeResult(
        final_answer=final_answer,
        steps=steps or [],
        token_usage=TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
        iterations=iterations,
        error=error,
        thinking=thinking,
    )


@pytest.fixture
def gateway_deps(tmp_path):
    """
    Build a fully-wired AgentGateway with mocked LLM + runtime.

    Returns a dict containing the gateway and all mock handles needed by tests.
    """
    # Real (lightweight) components
    session_dir = str(tmp_path / "sessions")
    memory_dir = str(tmp_path / "memory")
    skills_dir = str(tmp_path / "skills")

    session_manager = SessionManager(base_dir=session_dir)
    prompt_builder = PromptBuilder()
    skill_loader = SkillLoader(skills_dir=skills_dir)
    memory_store = MarkdownMemoryStore(base_dir=memory_dir)
    tool_registry = ToolRegistry()

    # Mocked LLM client (never called — runtime is patched)
    llm_config = LLMClientConfig(
        base_url="http://fake:11434/v1",
        model="test-model",
    )
    llm_client = LLMGatewayClient(llm_config)

    subagent_runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=ToolRegistry(),
        capability_registry=ToolRegistry(),
        prompt_builder=prompt_builder,
    )

    # Minimal hook registry (no default hooks to avoid quality-gate complexity)
    hooks = HookRegistry()

    gw = AgentGateway(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=memory_store,
        hooks=hooks,
        runtime_config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
    )

    return {
        "gateway": gw,
        "llm_client": llm_client,
        "session_manager": session_manager,
    }


# ---------------------------------------------------------------------------
# Helper: run gateway.chat() with a patched runtime returning `result`
# and a mock usage service, then return (chat_output, mock_usage_svc).
# ---------------------------------------------------------------------------

async def _run_chat_with_mocked_runtime(
    gateway_deps: dict,
    result: RuntimeResult,
    *,
    usage_svc_side_effect: Exception | None = None,
    tenant_id: str = "T1",
    user_id: str = "U1",
    business_type: str = "general_chat",
):
    """
    Patch AgenticRuntime.run to return *result* and
    dependencies.get_usage_service to return a mock.

    Returns (chat_output_dict, mock_usage_service).
    """
    gw = gateway_deps["gateway"]

    mock_usage = MagicMock()
    if usage_svc_side_effect:
        mock_usage.record_pipeline.side_effect = usage_svc_side_effect

    # Patch the runtime so no real LLM call is made
    with patch("agent.gateway.AgenticRuntime") as MockRuntime:
        mock_runtime_instance = AsyncMock()
        mock_runtime_instance.run.return_value = result
        MockRuntime.return_value = mock_runtime_instance

        # Patch get_usage_service inside gateway module
        with patch("agent.gateway.get_usage_service", return_value=mock_usage, create=True):
            # The gateway does `from dependencies import get_usage_service` inside chat()
            # so we need to patch it there too
            with patch.dict("sys.modules", {}):
                # Patch the import inside the function
                with patch("dependencies.get_usage_service", return_value=mock_usage):
                    output = await gw.chat(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        message="test message",
                        business_type=business_type,
                    )

    return output, mock_usage


# ── Test 1: Successful pipeline records status="success" ──


class TestSuccessPipeline:
    async def test_record_pipeline_called_on_success(self, gateway_deps):
        result = _make_runtime_result(final_answer="All good.")
        output, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        assert output["answer"] == "All good."
        mock_usage.record_pipeline.assert_called_once()
        call_kwargs = mock_usage.record_pipeline.call_args.kwargs
        assert call_kwargs["status"] == "success"

    async def test_token_fields_forwarded(self, gateway_deps):
        result = _make_runtime_result(
            prompt_tokens=200,
            completion_tokens=80,
            total_tokens=280,
        )
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["prompt_tokens"] == 200
        assert kw["completion_tokens"] == 80
        assert kw["total_tokens"] == 280

    async def test_iterations_forwarded(self, gateway_deps):
        result = _make_runtime_result(iterations=7)
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["iterations"] == 7


# ── Test 2: Failed pipeline records status="failed" ──


class TestFailedPipeline:
    async def test_error_result_records_failed(self, gateway_deps):
        result = _make_runtime_result(
            final_answer="Oops",
            error="LLM timeout",
        )
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["status"] == "failed"


# ── Test 3: record_pipeline exception → gateway still returns ──


class TestUsageRecordingSilentFailure:
    async def test_usage_error_does_not_break_gateway(self, gateway_deps):
        result = _make_runtime_result(final_answer="Fine result.")
        output, mock_usage = await _run_chat_with_mocked_runtime(
            gateway_deps,
            result,
            usage_svc_side_effect=RuntimeError("DB locked"),
        )

        # Gateway should still return the answer
        assert output["answer"] == "Fine result."
        assert "error" not in output  # no error propagated
        # record_pipeline was attempted
        mock_usage.record_pipeline.assert_called_once()


# ── Test 4: Tool names extracted and deduplicated ──


class TestToolNameExtraction:
    async def test_tool_names_deduplicated(self, gateway_deps):
        steps = [
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="arithmetic"),
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="read_reference"),
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="arithmetic"),  # duplicate
            RuntimeStep(step_type=StepType.OBSERVATION, content="result"),
            RuntimeStep(step_type=StepType.FINAL_ANSWER, content="42"),
        ]
        result = _make_runtime_result(steps=steps)
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        tool_names = kw["tool_names"]
        assert isinstance(tool_names, list)
        assert set(tool_names) == {"arithmetic", "read_reference"}
        assert len(tool_names) == 2  # deduplicated

    async def test_none_tool_name_excluded(self, gateway_deps):
        """Steps with tool_name=None should be excluded."""
        steps = [
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="arithmetic"),
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name=None),
        ]
        result = _make_runtime_result(steps=steps)
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert "arithmetic" in kw["tool_names"]
        assert None not in kw["tool_names"]

    async def test_no_tool_steps_gives_empty_list(self, gateway_deps):
        """Pipeline with no tool calls should pass empty tool_names."""
        steps = [
            RuntimeStep(step_type=StepType.LLM_CALL, content="thinking..."),
            RuntimeStep(step_type=StepType.FINAL_ANSWER, content="Just text."),
        ]
        result = _make_runtime_result(steps=steps)
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["tool_names"] == []

    async def test_non_tool_call_steps_ignored(self, gateway_deps):
        """Only TOOL_CALL steps contribute to tool_names."""
        steps = [
            RuntimeStep(step_type=StepType.OBSERVATION, tool_name="arithmetic"),
            RuntimeStep(step_type=StepType.ERROR, tool_name="broken_tool"),
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="read_reference"),
        ]
        result = _make_runtime_result(steps=steps)
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["tool_names"] == ["read_reference"]


# ── Test 5: All fields passed correctly ──


class TestAllFieldsCorrect:
    async def test_identity_fields(self, gateway_deps):
        result = _make_runtime_result()
        _, mock_usage = await _run_chat_with_mocked_runtime(
            gateway_deps,
            result,
            tenant_id="TENANT_X",
            user_id="USER_Y",
            business_type="reimbursement_create",
        )

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["tenant_id"] == "TENANT_X"
        assert kw["user_id"] == "USER_Y"
        assert kw["business_type"] == "reimbursement_create"

    async def test_session_id_forwarded(self, gateway_deps):
        result = _make_runtime_result()
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        # session_id should be a non-empty string (auto-generated)
        assert isinstance(kw["session_id"], str)
        assert len(kw["session_id"]) > 0

    async def test_model_name_forwarded(self, gateway_deps):
        result = _make_runtime_result()
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert kw["model"] == "test-model"

    async def test_duration_ms_is_positive(self, gateway_deps):
        result = _make_runtime_result()
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        assert isinstance(kw["duration_ms"], float)
        assert kw["duration_ms"] >= 0

    async def test_tool_call_count_from_result(self, gateway_deps):
        steps = [
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="a"),
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="b"),
            RuntimeStep(step_type=StepType.TOOL_CALL, tool_name="c"),
        ]
        result = _make_runtime_result(steps=steps)
        _, mock_usage = await _run_chat_with_mocked_runtime(gateway_deps, result)

        kw = mock_usage.record_pipeline.call_args.kwargs
        # tool_call_count comes from result.tool_call_count property
        assert kw["tool_call_count"] == 3
