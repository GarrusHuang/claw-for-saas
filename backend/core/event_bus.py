"""
EventBus: 解耦 SSE 事件发射。

设计：
- 基于 asyncio.Queue 的内存事件总线
- Agent/Service 发射事件（无需知道 SSE 传输层）
- API 路由层消费事件并格式化为 SSE
- 每个 Pipeline 执行有独立的 EventBus 实例

事件类型（对应 V3.3 SSE 协议）：
- agent_progress: Agent 状态变更
- type_inferred: 类型推断完成
- field_update: 字段填写（逐字段）
- form_completed: 表单填写完成
- audit_result: 单条审计结果
- audit_completed: 审计完成
- doc_generated: 文档生成完成
- pipeline_complete: 整个 Pipeline 完成
- error: 异常
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """事件数据结构"""
    event_type: str
    data: dict
    trace_id: str
    timestamp: float = field(default_factory=time.time)

    def to_sse_dict(self) -> dict:
        """转换为 SSE 格式。"""
        return {
            "event": self.event_type,
            "data": {
                **self.data,
                "trace_id": self.trace_id,
                "ts": self.timestamp,
            },
        }


class EventBus:
    """
    异步事件总线。

    Features:
    - 非阻塞 emit（不等待消费者）
    - 异步 subscribe 迭代器（用于 SSE 流）
    - Keepalive 心跳（30 秒超时发送）
    - pipeline_complete 事件自动关闭
    - 事件历史记录（用于调试和重放）
    """

    def __init__(self, trace_id: str, keepalive_interval: float = 30.0) -> None:
        self.trace_id = trace_id
        self.keepalive_interval = keepalive_interval
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._closed = False
        self._history: list[Event] = []

    def emit(self, event_type: str, data: dict | None = None) -> None:
        """
        非阻塞发射事件。

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if self._closed:
            logger.warning(f"EventBus closed, dropping event: {event_type}")
            return

        event = Event(
            event_type=event_type,
            data=data or {},
            trace_id=self.trace_id,
        )
        self._history.append(event)
        self._queue.put_nowait(event)

        logger.debug(f"Event emitted: {event_type}", extra={"trace_id": self.trace_id})

    async def subscribe(self) -> AsyncIterator[dict]:
        """
        异步事件订阅迭代器。

        Yields:
            SSE 格式的事件 dict
        """
        while not self._closed:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self.keepalive_interval,
                )

                # pipeline_complete 或 error(fatal) 事件关闭总线
                # 在 yield 前设置 _closed，避免消费者 break 后状态不一致
                should_close = event.event_type in ("pipeline_complete", "fatal_error")
                if should_close:
                    self._closed = True

                yield event.to_sse_dict()

                if should_close:
                    break

            except asyncio.TimeoutError:
                # 发送 keepalive 心跳
                yield {
                    "event": "keepalive",
                    "data": {"trace_id": self.trace_id, "ts": time.time()},
                }

    def close(self) -> None:
        """手动关闭事件总线。"""
        if not self._closed:
            self._closed = True
            # 发送关闭标记
            try:
                self._queue.put_nowait(Event(
                    event_type="pipeline_complete",
                    data={"status": "closed"},
                    trace_id=self.trace_id,
                ))
            except asyncio.QueueFull:
                logger.warning("EventBus queue full on close, dropping close marker")

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def history(self) -> list[Event]:
        """返回事件历史（用于调试）。"""
        return list(self._history)

    @property
    def event_count(self) -> int:
        return len(self._history)
