"""
#22 Batch Jobs — 批量输入处理服务。

批量输入 → 每条一个 agent 任务 → 并发执行 → 汇总输出。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BatchItem:
    index: int
    input_text: str
    status: str = "pending"
    result: str = ""
    duration_ms: float = 0.0


@dataclass
class BatchJob:
    job_id: str
    items: list[BatchItem] = field(default_factory=list)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


class BatchService:
    def __init__(self, max_concurrent: int = 5) -> None:
        self._max_concurrent = max_concurrent
        self._jobs: dict[str, BatchJob] = {}

    async def submit(
        self, job_id: str, inputs: list[str], gateway: Any,
        tenant_id: str, user_id: str, business_type: str = "batch",
    ) -> BatchJob:
        items = [BatchItem(index=i, input_text=text) for i, text in enumerate(inputs)]
        job = BatchJob(job_id=job_id, items=items, status="running")
        self._jobs[job_id] = job

        sem = asyncio.Semaphore(self._max_concurrent)

        async def _run_item(item: BatchItem) -> None:
            async with sem:
                item.status = "running"
                start = time.monotonic()
                try:
                    result = await gateway.chat(
                        tenant_id=tenant_id, user_id=user_id,
                        message=item.input_text, business_type=business_type,
                    )
                    item.result = result.get("answer", "")
                    item.status = "completed"
                except Exception as e:
                    item.result = f"Error: {e}"
                    item.status = "failed"
                item.duration_ms = (time.monotonic() - start) * 1000

        await asyncio.gather(*[_run_item(item) for item in items])
        job.status = "completed"
        return job

    def get_job(self, job_id: str) -> BatchJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        return [
            {
                "job_id": j.job_id, "status": j.status,
                "total": len(j.items),
                "completed": sum(1 for i in j.items if i.status == "completed"),
                "failed": sum(1 for i in j.items if i.status == "failed"),
            }
            for j in self._jobs.values()
        ]
