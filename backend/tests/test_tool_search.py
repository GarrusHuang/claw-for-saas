"""Tests for 2.3 Tool Search — 延迟工具加载。"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_registry import ToolRegistry, RegisteredTool


# ─── ToolRegistry.search_tools ───


class TestSearchTools:
    def _make_registry(self) -> ToolRegistry:
        reg = ToolRegistry()

        @reg.tool(description="读取上传的文件内容", read_only=True)
        def read_uploaded_file(file_id: str) -> dict:
            return {}

        @reg.tool(description="保存用户记忆", read_only=False)
        def save_memory(content: str) -> dict:
            return {}

        @reg.tool(description="浏览器打开网页", read_only=True)
        def open_url(url: str) -> dict:
            return {}

        @reg.tool(description="数值比较", read_only=True)
        def numeric_compare(a: float, b: float) -> dict:
            return {}

        return reg

    def test_search_by_keyword(self):
        reg = self._make_registry()
        results = reg.search_tools("文件")
        assert len(results) == 1
        assert results[0].name == "read_uploaded_file"

    def test_search_by_name(self):
        reg = self._make_registry()
        results = reg.search_tools("memory")
        assert len(results) == 1
        assert results[0].name == "save_memory"

    def test_search_multiple_keywords(self):
        reg = self._make_registry()
        # "浏览器" + "网页" both match open_url
        results = reg.search_tools("浏览器 网页")
        assert len(results) >= 1
        assert results[0].name == "open_url"

    def test_search_no_match(self):
        reg = self._make_registry()
        results = reg.search_tools("zzzznotexist")
        assert results == []

    def test_search_limit(self):
        reg = self._make_registry()
        # All tools match "read" or partial
        results = reg.search_tools("r", limit=2)
        assert len(results) <= 2

    def test_search_ranking(self):
        """多关键词命中更多的工具排在前面。"""
        reg = self._make_registry()
        results = reg.search_tools("read file uploaded")
        # read_uploaded_file matches 3 keywords, should be first
        assert results[0].name == "read_uploaded_file"


# ─── ToolRegistry.subset ───


class TestSubset:
    def test_subset_returns_only_specified(self):
        reg = ToolRegistry()

        @reg.tool(description="tool a", read_only=True)
        def tool_a() -> dict:
            return {}

        @reg.tool(description="tool b", read_only=False)
        def tool_b() -> dict:
            return {}

        @reg.tool(description="tool c", read_only=True)
        def tool_c() -> dict:
            return {}

        sub = reg.subset({"tool_a", "tool_c"})
        assert len(sub) == 2
        assert "tool_a" in sub
        assert "tool_c" in sub
        assert "tool_b" not in sub

    def test_subset_ignores_missing(self):
        reg = ToolRegistry()

        @reg.tool(description="tool a", read_only=True)
        def tool_a() -> dict:
            return {}

        sub = reg.subset({"tool_a", "nonexistent"})
        assert len(sub) == 1
        assert "tool_a" in sub

    def test_subset_empty(self):
        reg = ToolRegistry()

        @reg.tool(description="tool a", read_only=True)
        def tool_a() -> dict:
            return {}

        sub = reg.subset(set())
        assert len(sub) == 0


# ─── tool_search 工具函数 ───


class TestToolSearchFunction:
    def test_no_deferred_tools(self):
        """没有延迟工具时返回空结果。"""
        from unittest.mock import patch, MagicMock
        from core.context import RequestContext

        ctx = RequestContext()
        ctx.deferred_tools = []

        with patch("tools.builtin.tool_search.get_request_context", return_value=ctx):
            from tools.builtin.tool_search import tool_search as ts_fn
            result = ts_fn(query="file")

        assert result["results"] == []
        assert result["message"] == "当前没有延迟加载的工具"

    def test_with_deferred_tools(self):
        """有延迟工具时能搜索到匹配结果。"""
        from unittest.mock import patch

        from core.context import RequestContext
        from core.tool_registry import RegisteredTool

        deferred = [
            RegisteredTool(
                name="browser_screenshot",
                description="截取网页截图",
                func=lambda: None,
                schema={},
                read_only=True,
            ),
            RegisteredTool(
                name="submit_form",
                description="提交表单数据",
                func=lambda: None,
                schema={},
                read_only=False,
            ),
        ]

        ctx = RequestContext()
        ctx.deferred_tools = deferred

        with patch("tools.builtin.tool_search.get_request_context", return_value=ctx):
            from tools.builtin.tool_search import tool_search as ts_fn
            result = ts_fn(query="表单")

        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "submit_form"
        assert result["total_deferred"] == 2


# ─── Config threshold ───


class TestDeferredThresholdConfig:
    def test_default_threshold(self):
        from config import Settings
        s = Settings(llm_model="test")
        assert s.agent_tool_deferred_threshold == 30
