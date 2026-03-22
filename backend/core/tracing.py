"""OpenTelemetry 分布式追踪 — opt-in。

otel_enabled=False (默认) 时零开销: 不 import OTel 包，所有 span 操作为 NoOp。
未安装 OTel 包时自动 fallback 到 NoOp。
"""


class _NoOpSpan:
    """无操作 span — OTel 禁用时的替身。"""

    def set_attribute(self, key, value):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """无操作 tracer — OTel 禁用时的替身。"""

    def start_as_current_span(self, name, **kw):
        return _NoOpSpan()


_tracer = None
_enabled = False


def init_tracing(service_name: str, endpoint: str) -> None:
    """初始化 OTel 追踪。仅在 otel_enabled=True 时由 main.py 调用。"""
    global _tracer, _enabled
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("claw")
        _enabled = True
    except ImportError:
        _tracer = _NoOpTracer()


def get_tracer():
    """获取 tracer。未初始化时返回 NoOp tracer (零开销)。"""
    global _tracer
    if _tracer is None:
        _tracer = _NoOpTracer()
    return _tracer


def shutdown_tracing() -> None:
    """优雅关闭 OTel provider。"""
    if _enabled:
        try:
            from opentelemetry import trace
            provider = trace.get_tracer_provider()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception:
            pass
