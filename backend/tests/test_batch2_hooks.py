"""
Batch 2 tests: #35+36 新 Hook 事件, #37 inject action, #39 indent_block, #41 env_requires, #10 permissions
"""

import os
import pytest

from agent.hooks import HookRegistry, HookEvent, HookResult, KNOWN_EVENT_TYPES


# ── #35+36: 新 Hook 事件类型 ──

class TestNewHookEvents:

    def test_new_event_types_registered(self):
        assert "user_prompt_submit" in KNOWN_EVENT_TYPES
        assert "session_start" in KNOWN_EVENT_TYPES

    @pytest.mark.asyncio
    async def test_fire_user_prompt_submit(self):
        registry = HookRegistry()
        captured = []
        def handler(event):
            captured.append(event)
            return HookResult(action="allow")
        registry.register("user_prompt_submit", handler)
        await registry.fire(HookEvent(
            event_type="user_prompt_submit",
            user_id="U1", session_id="S1",
            context={"message": "hello"},
        ))
        assert len(captured) == 1
        assert captured[0].context["message"] == "hello"

    @pytest.mark.asyncio
    async def test_fire_session_start(self):
        registry = HookRegistry()
        captured = []
        def handler(event):
            captured.append(event)
            return HookResult(action="allow")
        registry.register("session_start", handler)
        await registry.fire(HookEvent(
            event_type="session_start",
            user_id="U1", session_id="S1",
            context={"tenant_id": "T1"},
        ))
        assert len(captured) == 1


# ── #37: inject action ──

class TestInjectAction:

    @pytest.mark.asyncio
    async def test_inject_returns_inject_result(self):
        registry = HookRegistry()
        def handler(event):
            return HookResult(action="inject", message="Use caution with this tool")
        registry.register("pre_tool_use", handler)
        result = await registry.fire(HookEvent(event_type="pre_tool_use", tool_name="run_command"))
        assert result.action == "inject"
        assert "caution" in result.message

    @pytest.mark.asyncio
    async def test_block_overrides_inject(self):
        registry = HookRegistry()
        def inject_handler(event):
            return HookResult(action="inject", message="instruction")
        def block_handler(event):
            return HookResult(action="block", message="blocked")
        registry.register("pre_tool_use", block_handler)
        registry.register("pre_tool_use", inject_handler)
        result = await registry.fire(HookEvent(event_type="pre_tool_use", tool_name="x"))
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_inject_overrides_modify(self):
        registry = HookRegistry()
        def modify_handler(event):
            return HookResult(action="modify", modified_input={"a": 1})
        def inject_handler(event):
            return HookResult(action="inject", message="instruction")
        registry.register("pre_tool_use", modify_handler)
        registry.register("pre_tool_use", inject_handler)
        result = await registry.fire(HookEvent(event_type="pre_tool_use", tool_name="x"))
        assert result.action == "inject"


# ── #39: read_source_file indent_block ──

class TestIndentBlock:

    def test_extract_function(self, tmp_path):
        code = (
            "import os\n"
            "\n"
            "def foo():\n"
            "    x = 1\n"
            "    return x\n"
            "\n"
            "def bar():\n"
            "    return 2\n"
        )
        f = tmp_path / "test.py"
        f.write_text(code)

        from tools.builtin.code_tools import _extract_indent_block
        lines = code.split("\n")
        block, start = _extract_indent_block(lines, "def foo")
        assert block is not None
        assert start == 2
        assert "def foo" in block[0]
        assert "return x" in block[-1]
        assert "def bar" not in "\n".join(block)

    def test_extract_class(self, tmp_path):
        code = (
            "class MyClass:\n"
            "    def __init__(self):\n"
            "        self.x = 1\n"
            "\n"
            "    def method(self):\n"
            "        return self.x\n"
            "\n"
            "other_var = 42\n"
        )
        from tools.builtin.code_tools import _extract_indent_block
        lines = code.split("\n")
        block, start = _extract_indent_block(lines, "class MyClass")
        assert block is not None
        assert start == 0
        assert len(block) >= 5
        assert "other_var" not in "\n".join(block)

    def test_pattern_not_found(self):
        from tools.builtin.code_tools import _extract_indent_block
        lines = ["def foo():", "    pass"]
        block, start = _extract_indent_block(lines, "class Bar")
        assert block is None
        assert start == -1


# ── #41 + #10: Skill env_requires + permissions ──

class TestSkillDeclarations:

    def _make_skill(self, skill_dir, name, meta_extra=""):
        d = os.path.join(skill_dir, "builtin", name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {name}\ntype: capability\ndescription: test skill\n{meta_extra}---\n\nBody content\n")

    def test_env_requires_missing_skips(self, tmp_path):
        """缺少 env_requires 声明的环境变量时，Skill 不被索引。"""
        from skills.loader import SkillLoader
        self._make_skill(str(tmp_path), "needs_key", "env_requires: [NONEXISTENT_VAR_123]\n")
        loader = SkillLoader(skills_dir=str(tmp_path))
        index, names = loader.build_skill_index()
        assert "needs_key" not in names

    def test_env_requires_present_includes(self, tmp_path):
        """env_requires 声明的变量存在时，Skill 正常加载。"""
        from skills.loader import SkillLoader
        os.environ["TEST_SKILL_VAR_XYZ"] = "1"
        try:
            self._make_skill(str(tmp_path), "has_key", "env_requires: [TEST_SKILL_VAR_XYZ]\n")
            loader = SkillLoader(skills_dir=str(tmp_path))
            index, names = loader.build_skill_index()
            assert "has_key" in names
        finally:
            del os.environ["TEST_SKILL_VAR_XYZ"]

    def test_permissions_shown_in_index(self, tmp_path):
        """permissions 声明显示在索引描述中。"""
        from skills.loader import SkillLoader
        self._make_skill(str(tmp_path), "file_skill", "permissions: [file, network]\n")
        loader = SkillLoader(skills_dir=str(tmp_path))
        index, names = loader.build_skill_index()
        assert "file_skill" in names
        assert "[需要: file, network]" in index

    def test_no_permissions_no_tag(self, tmp_path):
        from skills.loader import SkillLoader
        self._make_skill(str(tmp_path), "plain_skill", "")
        loader = SkillLoader(skills_dir=str(tmp_path))
        index, names = loader.build_skill_index()
        assert "[需要:" not in index
