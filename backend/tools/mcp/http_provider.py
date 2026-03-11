"""
HttpMCPProvider — 基于 httpx 转发到宿主 REST API。

SaaS 宿主提供 REST 端点，HttpMCPProvider 将工具调用转发为 HTTP 请求。

端点映射:
  get_form_schema    → GET  {base_url}/forms/{form_type}/schema
  get_business_rules → GET  {base_url}/rules/{rule_type}
  get_candidate_types→ GET  {base_url}/candidates/{category}
  get_protected_values→GET  {base_url}/protected/{context}
  submit_form_data   → POST {base_url}/forms/{form_type}/submit
  query_data         → POST {base_url}/query/{query_type}
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class HttpMCPProvider:
    """HTTP 转发 MCP Provider — 代理到宿主 REST API。"""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_s,
            headers=headers or {},
        )

    async def get_form_schema(self, form_type: str) -> dict:
        return await self._get(f"/forms/{form_type}/schema")

    async def get_business_rules(self, rule_type: str) -> dict:
        return await self._get(f"/rules/{rule_type}")

    async def get_candidate_types(self, category: str) -> dict:
        return await self._get(f"/candidates/{category}")

    async def get_protected_values(self, context: str) -> dict:
        return await self._get(f"/protected/{context}")

    async def submit_form_data(self, form_type: str, data: dict) -> dict:
        return await self._post(f"/forms/{form_type}/submit", data)

    async def query_data(self, query_type: str, params: dict) -> dict:
        return await self._post(f"/query/{query_type}", params)

    # ── Internal ──

    async def _get(self, path: str) -> dict:
        try:
            resp = await self._client.get(path)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"MCP HTTP error: {e.response.status_code} {path}")
            return {"error": f"HTTP {e.response.status_code}", "path": path}
        except Exception as e:
            logger.warning(f"MCP request failed: {path} — {e}")
            return {"error": str(e), "path": path}

    async def _post(self, path: str, data: dict) -> dict:
        try:
            resp = await self._client.post(path, json=data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"MCP HTTP error: {e.response.status_code} {path}")
            return {"error": f"HTTP {e.response.status_code}", "path": path}
        except Exception as e:
            logger.warning(f"MCP request failed: {path} — {e}")
            return {"error": str(e), "path": path}

    async def close(self) -> None:
        await self._client.aclose()
