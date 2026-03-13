"""
A9: Webhook 分发器。

租户注册 Webhook URL 后，任务完成/失败时 POST 通知宿主系统。
- HMAC-SHA256 签名 (X-Claw-Signature)
- 指数退避重试 (1s → 2s → 4s, 最多 3 次)
- 事件过滤: 只发送 config.events 中订阅的事件
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import socket

import httpx

logger = logging.getLogger(__name__)


def _resolve_to_unsafe_ip(url: str) -> bool:
    """
    DNS rebinding 防护: 在实际请求前解析 hostname，检查 IP 是否为内网地址。

    即使注册时 URL 通过了 SSRF 检查，攻击者仍可在之后修改 DNS 记录
    将域名指向内网 IP。此函数在每次 dispatch 时做二次校验。
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        # 解析所有 A/AAAA 记录
        infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return True  # DNS 解析失败视为不安全

    # 检查每个解析出的 IP
    _UNSAFE_PREFIXES = (
        "127.", "10.", "192.168.", "169.254.",
        "0.", "::1", "fe80:", "fc", "fd",
    )
    _172_PRIVATE = range(16, 32)

    for family, _type, _proto, _canonname, sockaddr in infos:
        ip = sockaddr[0]
        if ip.startswith(_UNSAFE_PREFIXES):
            return True
        # 172.16-31.x.x
        if ip.startswith("172."):
            parts = ip.split(".")
            if len(parts) >= 2:
                try:
                    if int(parts[1]) in _172_PRIVATE:
                        return True
                except ValueError:
                    pass
        # IPv6 零地址
        if ip == "::":
            return True

    return False


@dataclass
class WebhookConfig:
    """单个租户的 Webhook 配置。"""
    url: str
    secret: str = ""
    events: list[str] = field(default_factory=lambda: ["task_completed", "task_failed"])
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WebhookConfig:
        return cls(
            url=data["url"],
            secret=data.get("secret", ""),
            events=data.get("events", ["task_completed", "task_failed"]),
            enabled=data.get("enabled", True),
        )


class WebhookStore:
    """JSON 持久化 — data/webhooks/{tenant_id}/config.json。"""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def _config_path(self, tenant_id: str) -> Path:
        return self.base_dir / tenant_id / "config.json"

    def get(self, tenant_id: str) -> WebhookConfig | None:
        path = self._config_path(tenant_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WebhookConfig.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load webhook config for {tenant_id}: {e}")
            return None

    def save(self, tenant_id: str, config: WebhookConfig) -> None:
        path = self._config_path(tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, tenant_id: str) -> bool:
        path = self._config_path(tenant_id)
        if path.exists():
            path.unlink()
            return True
        return False


class WebhookDispatcher:
    """
    Webhook POST 分发器。

    - HMAC-SHA256 签名
    - 指数退避重试
    - 事件过滤
    """

    def __init__(
        self,
        store: WebhookStore,
        timeout_s: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self.store = store
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def _sign(self, payload: bytes, secret: str) -> str:
        return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    async def dispatch(
        self,
        tenant_id: str,
        event: str,
        data: dict[str, Any],
    ) -> bool:
        """
        向租户的 Webhook URL 发送事件通知。

        Returns:
            True if delivered (2xx), False otherwise.
        """
        config = self.store.get(tenant_id)
        if not config or not config.enabled:
            return False

        if config.events and event not in config.events:
            logger.debug(f"Webhook event '{event}' not subscribed by tenant {tenant_id}")
            return False

        # DNS rebinding 防护: 请求前解析 IP 并检查是否为内网地址
        if _resolve_to_unsafe_ip(config.url):
            logger.error(
                f"Webhook URL resolves to private/internal IP, blocking: {config.url}"
            )
            return False

        payload = json.dumps({
            "event": event,
            "data": data,
            "timestamp": time.time(),
            "tenant_id": tenant_id,
        }, ensure_ascii=False).encode("utf-8")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if config.secret:
            headers["X-Claw-Signature"] = self._sign(payload, config.secret)

        # 指数退避重试
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            for attempt in range(self.max_retries):
                try:
                    resp = await client.post(config.url, content=payload, headers=headers)
                    if 200 <= resp.status_code < 300:
                        logger.info(f"Webhook delivered: {event} → {config.url} (status={resp.status_code})")
                        return True
                    # 4xx (非 429) 是永久错误，不重试
                    if 400 <= resp.status_code < 500 and resp.status_code != 429:
                        logger.error(f"Webhook permanent failure: {resp.status_code} from {config.url}")
                        return False
                    logger.warning(f"Webhook non-2xx: {resp.status_code} from {config.url}")
                except Exception as e:
                    logger.warning(f"Webhook attempt {attempt + 1} failed: {e}")

                if attempt < self.max_retries - 1:
                    import asyncio
                    delay = 2 ** attempt  # 1s → 2s → 4s
                    await asyncio.sleep(delay)

            logger.error(f"Webhook exhausted retries for {event} → {config.url}")
            return False
