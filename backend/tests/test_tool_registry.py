"""Tests for core/tool_registry.py — ToolRegistry, ToolResult, RegisteredTool."""
import asyncio
import json
import sys
import os
from typing import Literal, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tool_registry import ToolRegistry, ToolResult, RegisteredTool


# ── ToolResult ──


class TestToolResult:
    def test_success_to_json(self):
        r = ToolResult(success=True, data={"key": "value"})
        j = r.to_json()
        assert json.loads(j) == {"key": "value"}

    def test_error_to_json(self):
        r = ToolResult(success=False, error="something broke")
        j = r.to_json()
        assert json.loads(j) == {"error": "something broke"}

    def test_to_json_truncation(self):
        r = ToolResult(success=True, data="a" * 1000)
        j = r.to_json(max_chars=50)
        assert len(j) == 50 + len("...[truncated]")
        assert j.endswith("...[truncated]")

    def test_to_json_no_truncation_when_zero(self):
        r = ToolResult(success=True, data="a" * 1000)
        j = r.to_json(max_chars=0)
        assert "...[truncated]" not in j

    def test_to_json_chinese(self):
        r = ToolResult(success=True, data={"msg": "你好世界"})
        j = r.to_json()
        assert "你好世界" in j  # ensure_ascii=False


# ── ToolRegistry: Registration ──


class TestToolRegistryRegistration:
    def test_decorator_registration(self):
        reg = ToolRegistry()

        @reg.tool(description="Add two numbers", read_only=True)
        def add(a: int, b: int) -> int:
            return a + b

        assert "add" in reg
        assert len(reg) == 1
        assert reg.get_tool("add").read_only is True

    def test_custom_name(self):
        reg = ToolRegistry()

        @reg.tool(description="my tool", name="custom_name")
        def foo():
            pass

        assert "custom_name" in reg
        assert "foo" not in reg

    def test_imperative_register(self):
        reg = ToolRegistry()

        def bar(x: str) -> str:
            return x

        reg.register(bar, description="bar tool")
        assert "bar" in reg

    def test_schema_extraction_basic_types(self):
        reg = ToolRegistry()

        @reg.tool(description="test")
        def func(a: str, b: int, c: float, d: bool) -> dict:
            return {}

        schema = reg.get_tool("func").schema
        params = schema["function"]["parameters"]
        assert params["properties"]["a"]["type"] == "string"
        assert params["properties"]["b"]["type"] == "integer"
        assert params["properties"]["c"]["type"] == "number"
        assert params["properties"]["d"]["type"] == "boolean"
        assert set(params["required"]) == {"a", "b", "c", "d"}

    def test_schema_extraction_optional(self):
        reg = ToolRegistry()

        @reg.tool(description="test")
        def func(a: str, b: Optional[int] = None) -> dict:
            return {}

        params = reg.get_tool("func").schema["function"]["parameters"]
        assert params["required"] == ["a"]
        assert "b" in params["properties"]

    def test_schema_extraction_literal(self):
        reg = ToolRegistry()

        @reg.tool(description="test")
        def func(op: Literal["add", "sub", "mul"]) -> dict:
            return {}

        prop = reg.get_tool("func").schema["function"]["parameters"]["properties"]["op"]
        assert prop["type"] == "string"
        assert prop["enum"] == ["add", "sub", "mul"]

    def test_schema_extraction_list(self):
        reg = ToolRegistry()

        @reg.tool(description="test")
        def func(items: list[int]) -> dict:
            return {}

        prop = reg.get_tool("func").schema["function"]["parameters"]["properties"]["items"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "integer"

    def test_schema_extraction_dict(self):
        reg = ToolRegistry()

        @reg.tool(description="test")
        def func(data: dict) -> dict:
            return {}

        prop = reg.get_tool("func").schema["function"]["parameters"]["properties"]["data"]
        assert prop["type"] == "object"

    def test_default_value_in_schema(self):
        reg = ToolRegistry()

        @reg.tool(description="test")
        def func(a: str, b: int = 42) -> dict:
            return {}

        prop = reg.get_tool("func").schema["function"]["parameters"]["properties"]["b"]
        assert prop.get("default") == 42


# ── ToolRegistry: Execution ──


class TestToolRegistryExecution:
    @pytest.mark.asyncio
    async def test_execute_sync_tool(self):
        reg = ToolRegistry()

        @reg.tool(description="add")
        def add(a: int, b: int) -> int:
            return a + b

        result = await reg.execute("add", {"a": 3, "b": 4})
        assert result.success is True
        assert result.data == 7

    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        reg = ToolRegistry()

        @reg.tool(description="async add")
        async def add_async(a: int, b: int) -> int:
            return a + b

        result = await reg.execute("add_async", {"a": 5, "b": 6})
        assert result.success is True
        assert result.data == 11

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        result = await reg.execute("nonexistent", {})
        assert result.success is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_execute_bad_arguments(self):
        reg = ToolRegistry()

        @reg.tool(description="needs args")
        def func(required_arg: str) -> str:
            return required_arg

        result = await reg.execute("func", {})
        assert result.success is False
        assert "Invalid arguments" in result.error

    @pytest.mark.asyncio
    async def test_execute_tool_exception(self):
        reg = ToolRegistry()

        @reg.tool(description="fails")
        def fail_tool() -> None:
            raise ValueError("boom")

        result = await reg.execute("fail_tool", {})
        assert result.success is False
        assert "boom" in result.error


# ── ToolRegistry: Merge & Utility ──


class TestToolRegistryMerge:
    def test_merge(self):
        reg1 = ToolRegistry()
        reg2 = ToolRegistry()

        @reg1.tool(description="tool1")
        def tool_a():
            pass

        @reg2.tool(description="tool2")
        def tool_b():
            pass

        merged = reg1.merge(reg2)
        assert "tool_a" in merged
        assert "tool_b" in merged
        assert len(merged) == 2

    def test_merge_override(self):
        reg1 = ToolRegistry()
        reg2 = ToolRegistry()

        @reg1.tool(description="original")
        def shared():
            return "v1"

        @reg2.tool(description="override")
        def shared():
            return "v2"

        merged = reg1.merge(reg2)
        assert merged.get_tool("shared").description == "override"

    def test_get_schemas(self):
        reg = ToolRegistry()

        @reg.tool(description="t1")
        def a():
            pass

        @reg.tool(description="t2")
        def b():
            pass

        schemas = reg.get_schemas()
        assert len(schemas) == 2
        assert all(s["type"] == "function" for s in schemas)

    def test_get_tool_names(self):
        reg = ToolRegistry()

        @reg.tool(description="t")
        def x():
            pass

        @reg.tool(description="t")
        def y():
            pass

        assert set(reg.get_tool_names()) == {"x", "y"}

    def test_is_read_only(self):
        reg = ToolRegistry()

        @reg.tool(description="ro", read_only=True)
        def ro_tool():
            pass

        @reg.tool(description="rw", read_only=False)
        def rw_tool():
            pass

        assert reg.is_read_only("ro_tool") is True
        assert reg.is_read_only("rw_tool") is False
        assert reg.is_read_only("nonexistent") is False

    def test_repr(self):
        reg = ToolRegistry()

        @reg.tool(description="t")
        def my_tool():
            pass

        assert "my_tool" in repr(reg)
