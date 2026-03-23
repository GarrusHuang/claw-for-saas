"""
Batch 7 tests: #26 Dynamic Tools, #46 Session search
"""

import pytest
from core.tool_registry import ToolRegistry, ToolResult, RegisteredTool


# ── #26: Dynamic Tools ──

class TestDynamicTools:

    def test_register_dynamic(self):
        registry = ToolRegistry()
        schema = {"type": "function", "function": {"name": "dyn", "parameters": {}}}
        registry.register_dynamic(
            name="dyn",
            description="Dynamic tool",
            schema=schema,
            func=lambda: "ok",
            defer_loading=True,
        )
        tool = registry.get_tool("dyn")
        assert tool is not None
        assert tool.defer_loading
        assert tool.description == "Dynamic tool"

    def test_defer_loading_flag(self):
        tool = RegisteredTool(
            name="t", description="d", func=lambda: None, schema={},
            defer_loading=True,
        )
        assert tool.defer_loading


# ── #46: Session 搜索优化 ──

class TestSessionSearchOptimized:

    def test_build_search_index(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "财务报告分析"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "请分析这份报告"})
        sm.append_message("T1", "U1", sid, {"role": "assistant", "content": "好的"})

        index = sm._build_search_index("T1", "U1")
        assert len(index) == 1
        assert index[0]["title"] == "财务报告分析"
        assert "分析" in index[0].get("first_user_msg", "")

    def test_search_fast_path(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "财务报告"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "分析财务数据"})
        results = sm.search_sessions("T1", "U1", "财务")
        assert len(results) >= 1
        assert results[0]["title_match"] or results[0]["match_snippet"]

    def test_search_index_cached(self, tmp_path):
        """搜索索引应被缓存，二次调用不重建。"""
        from agent.session import SessionManager
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "test"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "hello"})
        # 首次建立索引
        idx1 = sm._build_search_index("T1", "U1")
        # 二次应从缓存返回（同一对象）
        idx2 = sm._build_search_index("T1", "U1")
        assert idx1 is idx2
