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


# ── #19: 内置指标收集器 (不依赖 OTel，始终可用) ──

import time as _time
import threading


class MetricsCollector:
    """
    轻量级运行时指标收集器。

    per-turn / per-tool counter + 延迟 histogram，
    无外部依赖，线程安全。可通过 /api/health 或管理 API 暴露。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, list[float]] = {}  # name → [values] (最近 1000)
        self._start_time = _time.monotonic()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def record(self, name: str, value: float) -> None:
        """记录一个采样值到 histogram (保留最近 1000 个)。"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            hist = self._histograms[name]
            hist.append(value)
            if len(hist) > 1000:
                self._histograms[name] = hist[-1000:]

    def get_counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    def get_histogram_stats(self, name: str) -> dict:
        """返回 histogram 统计: count, min, max, avg, p50, p95, p99。"""
        with self._lock:
            values = list(self._histograms.get(name, []))
        if not values:
            return {"count": 0}
        values.sort()
        n = len(values)
        return {
            "count": n,
            "min": round(values[0], 2),
            "max": round(values[-1], 2),
            "avg": round(sum(values) / n, 2),
            "p50": round(values[n // 2], 2),
            "p95": round(values[int(n * 0.95)], 2) if n >= 20 else round(values[-1], 2),
            "p99": round(values[int(n * 0.99)], 2) if n >= 100 else round(values[-1], 2),
        }

    def snapshot(self) -> dict:
        """返回所有指标的快照。"""
        with self._lock:
            counters = dict(self._counters)
            hist_names = list(self._histograms.keys())
        return {
            "uptime_s": round(_time.monotonic() - self._start_time, 1),
            "counters": counters,
            "histograms": {name: self.get_histogram_stats(name) for name in hist_names},
        }


# 全局单例
_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """获取全局 MetricsCollector 单例。"""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics
