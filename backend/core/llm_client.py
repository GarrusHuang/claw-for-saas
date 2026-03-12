"""
LLMGatewayClient: 异步 OpenAI 兼容 LLM 客户端。

借鉴 agent-engine 的 Gateway Client 模式：
- httpx.AsyncClient 连接池
- 指数退避重试（429/500/502/503/超时）
- Token 用量追踪
- 流式输出支持
- Qwen3 特定参数优化
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LLMClientConfig:
    """LLM 客户端配置"""
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5"
    api_key: str = "not-needed"
    timeout_s: float = 120.0
    max_retries: int = 3
    retry_delay_s: float = 2.0
    default_temperature: float = 0.7
    default_top_p: float = 0.8
    enable_thinking: bool = False


@dataclass
class TokenUsage:
    """Token 用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 响应封装"""
    content: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    latency_ms: float = 0.0
    raw_response: dict | None = None

    def to_message_dict(self) -> dict:
        """转换为 OpenAI message 格式 dict。"""
        msg: dict[str, Any] = {"role": "assistant"}
        if self.content:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


class LLMGatewayClient:
    """
    异步 OpenAI 兼容 LLM 客户端。

    Features:
    - httpx.AsyncClient with connection pooling
    - Retry with exponential backoff
    - Token usage tracking per call and cumulative
    - Streaming support (SSE pass-through)
    - Qwen3-specific parameter defaults
    """

    def __init__(self, config: LLMClientConfig | None = None) -> None:
        self.config = config or LLMClientConfig()
        self._client: httpx.AsyncClient | None = None
        self._cumulative_usage = TokenUsage()
        self._call_count = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx 客户端。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=self.config.timeout_s,
                    write=30.0,
                    pool=10.0,
                ),
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                ),
            )
        return self._client

    async def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        发送 Chat Completion 请求。

        Args:
            messages: OpenAI 格式的消息列表
            tools: OpenAI 格式的工具 schema 列表
            max_tokens: 最大生成 token 数
            temperature: 采样温度
            top_p: Top-P 采样
            stream: 是否流式
            **kwargs: 其他 OpenAI API 参数

        Returns:
            LLMResponse 包含 content、tool_calls、usage 等

        Raises:
            LLMClientError: 所有重试失败后抛出
        """
        payload = self._build_payload(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=stream,
            **kwargs,
        )

        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                start = time.monotonic()
                client = await self._get_client()

                headers = {"Content-Type": "application/json"}
                if self.config.api_key:
                    headers["Authorization"] = f"Bearer {self.config.api_key}"

                response = await client.post(
                    f"{self.config.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )

                latency_ms = (time.monotonic() - start) * 1000

                if response.status_code == 200:
                    data = response.json()
                    result = self._parse_response(data, latency_ms)
                    self._update_usage(result.usage)
                    self._call_count += 1

                    logger.info(
                        "LLM call success",
                        extra={
                            "model": self.config.model,
                            "latency_ms": f"{latency_ms:.0f}",
                            "tokens": result.usage.total_tokens,
                            "finish_reason": result.finish_reason,
                            "has_tool_calls": bool(result.tool_calls),
                        },
                    )
                    return result

                # 可重试的状态码
                if response.status_code in (429, 500, 502, 503):
                    last_error = LLMClientError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                    # Phase 8: Retry-After 解析 + 指数退避 + 抖动
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except (ValueError, TypeError):
                            delay = self.config.retry_delay_s * (2 ** attempt)
                    else:
                        import random
                        jitter = self.config.retry_delay_s * 0.5
                        delay = self.config.retry_delay_s * (2 ** attempt) + random.uniform(0, jitter)
                    logger.warning(
                        f"LLM call failed (attempt {attempt + 1}/{self.config.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {response.status_code}"
                    )
                    await asyncio.sleep(delay)
                    continue

                # 不可重试的错误
                raise LLMClientError(
                    f"LLM call failed with HTTP {response.status_code}: {response.text[:500]}"
                )

            except httpx.TimeoutException as e:
                last_error = LLMClientError(f"Timeout: {e}")
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_s * (2 ** attempt)
                    logger.warning(
                        f"LLM timeout (attempt {attempt + 1}), retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

            except httpx.ConnectError as e:
                last_error = LLMClientError(f"Connection error: {e}")
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_s * (2 ** attempt)
                    logger.warning(
                        f"LLM connection error (attempt {attempt + 1}), retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

        raise last_error or LLMClientError("All retries exhausted")

    async def chat_completion_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict]:
        """
        流式 Chat Completion (带连接级重试)。

        Yields:
            SSE chunk dicts with "choices[0].delta"

        连接错误 (ConnectError/ConnectTimeout) 最多重试 2 次。
        HTTP 错误 (4xx/5xx) 不重试，直接抛出。
        """
        max_stream_retries = 2
        last_error: Exception | None = None

        for attempt in range(max_stream_retries + 1):
            try:
                async for chunk in self._stream_inner(
                    messages=messages, tools=tools,
                    max_tokens=max_tokens, temperature=temperature,
                    **kwargs,
                ):
                    yield chunk
                return  # 成功完成
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_error = e
                if attempt < max_stream_retries:
                    delay = 1.0 * (attempt + 1)
                    logger.warning(
                        f"Stream connection error (attempt {attempt + 1}/{max_stream_retries + 1}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        if last_error:
            raise last_error

    async def _stream_inner(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict]:
        """流式请求内部实现。"""
        payload = self._build_payload(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            **kwargs,
        )

        client = await self._get_client()

        stream_headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            stream_headers["Authorization"] = f"Bearer {self.config.api_key}"

        async with client.stream(
            "POST",
            f"{self.config.base_url}/chat/completions",
            json=payload,
            headers=stream_headers,
        ) as response:
            # 检查 HTTP 状态码 — 非 2xx 时读取错误信息并抛出异常
            if response.status_code >= 400:
                error_body = ""
                async for line in response.aiter_lines():
                    error_body += line
                raise httpx.HTTPStatusError(
                    f"LLM API returned {response.status_code}: {error_body[:500]}",
                    request=response.request,
                    response=response,
                )

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        yield json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict:
        """构建 API 请求 payload。"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.default_temperature,
            "top_p": top_p if top_p is not None else self.config.default_top_p,
            "max_tokens": max_tokens or 4096,
            "stream": stream,
        }

        if self.config.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # 合并额外参数
        for k, v in kwargs.items():
            if v is not None:
                payload[k] = v

        return payload

    def _parse_response(self, data: dict, latency_ms: float) -> LLMResponse:
        """解析 API 响应。"""
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content="", latency_ms=latency_ms, raw_response=data)

        message = choices[0].get("message", {})
        usage_data = data.get("usage", {})

        return LLMResponse(
            content=message.get("content"),
            tool_calls=message.get("tool_calls"),
            finish_reason=choices[0].get("finish_reason"),
            usage=TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            model=data.get("model", self.config.model),
            latency_ms=latency_ms,
            raw_response=data,
        )

    def _update_usage(self, usage: TokenUsage) -> None:
        """更新累计 token 用量。"""
        self._cumulative_usage.prompt_tokens += usage.prompt_tokens
        self._cumulative_usage.completion_tokens += usage.completion_tokens
        self._cumulative_usage.total_tokens += usage.total_tokens

    @property
    def cumulative_usage(self) -> TokenUsage:
        return self._cumulative_usage

    @property
    def call_count(self) -> int:
        return self._call_count

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> LLMGatewayClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


class LLMClientError(Exception):
    """LLM 客户端错误"""
    pass
