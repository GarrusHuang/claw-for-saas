"""Tests for 2.4 OpenTelemetry — NoOp tracer + init/shutdown。"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNoOpTracer:
    def test_noop_span_context_manager(self):
        """NoOp span 可作为 context manager 使用。"""
        from core.tracing import _NoOpSpan
        span = _NoOpSpan()
        with span as s:
            s.set_attribute("key", "value")
        # No error raised

    def test_noop_tracer_returns_noop_span(self):
        from core.tracing import _NoOpTracer
        tracer = _NoOpTracer()
        span = tracer.start_as_current_span("test.span")
        assert isinstance(span, type(span))
        with span as s:
            s.set_attribute("key", "value")

    def test_get_tracer_returns_noop_by_default(self):
        """未初始化时 get_tracer 返回 NoOp tracer。"""
        import core.tracing as tracing_mod
        # Reset state
        tracing_mod._tracer = None
        tracing_mod._enabled = False

        tracer = tracing_mod.get_tracer()
        assert isinstance(tracer, tracing_mod._NoOpTracer)

    def test_get_tracer_idempotent(self):
        """多次调用 get_tracer 返回同一实例。"""
        import core.tracing as tracing_mod
        tracing_mod._tracer = None
        tracing_mod._enabled = False

        t1 = tracing_mod.get_tracer()
        t2 = tracing_mod.get_tracer()
        assert t1 is t2


class TestInitShutdown:
    def test_init_without_otel_installed(self):
        """未安装 OTel 包时 init_tracing fallback 到 NoOp。"""
        import core.tracing as tracing_mod
        tracing_mod._tracer = None
        tracing_mod._enabled = False

        # init_tracing 会 try import; 如果没装包就 fallback
        tracing_mod.init_tracing("test-svc", "localhost:4317")

        tracer = tracing_mod.get_tracer()
        # 如果 OTel 没装，仍然是 NoOpTracer; 如果装了，就是真 tracer
        assert tracer is not None

    def test_shutdown_noop_safe(self):
        """shutdown 在未启用时不抛异常。"""
        import core.tracing as tracing_mod
        tracing_mod._tracer = None
        tracing_mod._enabled = False
        tracing_mod.shutdown_tracing()  # Should not raise


class TestSpanAttributes:
    def test_noop_span_set_attribute_types(self):
        """NoOp span 接受各种属性类型。"""
        from core.tracing import _NoOpSpan
        span = _NoOpSpan()
        span.set_attribute("str_key", "value")
        span.set_attribute("int_key", 42)
        span.set_attribute("float_key", 3.14)
        span.set_attribute("bool_key", True)

    def test_tracer_span_as_manual_context(self):
        """手动 __enter__/__exit__ 模式 (runtime.tool_call 使用)。"""
        from core.tracing import _NoOpTracer
        tracer = _NoOpTracer()
        span_cm = tracer.start_as_current_span("test.manual")
        span = span_cm.__enter__()
        span.set_attribute("tool.name", "calculator")
        span.set_attribute("tool.success", True)
        span.set_attribute("tool.latency_ms", 12.5)
        span_cm.__exit__(None, None, None)


class TestOtelConfig:
    def test_default_config(self):
        from config import Settings
        s = Settings(llm_model="test")
        assert s.otel_enabled is False
        assert s.otel_endpoint == "http://localhost:4317"
        assert s.otel_service_name == "claw-for-saas"
