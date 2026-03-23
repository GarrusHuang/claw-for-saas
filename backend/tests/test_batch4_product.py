"""
Batch 4 tests: #15 Thread Rollback, #20 Undo, #48 Skill frontmatter, #30 Skill hot reload
"""

import json
import os
import pytest

from agent.session import SessionManager
from core.file_diff_tracker import TurnDiffTracker
from skills.loader import _parse_frontmatter, SkillLoader


# ── #15 Thread Rollback ──

class TestThreadRollback:

    def test_rollback_1_turn(self, tmp_path):
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "test"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "hello"})
        sm.append_message("T1", "U1", sid, {"role": "assistant", "content": "hi"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "bye"})
        sm.append_message("T1", "U1", sid, {"role": "assistant", "content": "see ya"})

        removed = sm.rollback_turns("T1", "U1", sid, n=1)
        assert removed == 2
        messages = sm.load_messages("T1", "U1", sid)
        assert len(messages) == 2
        assert messages[-1]["content"] == "hi"

    def test_rollback_2_turns(self, tmp_path):
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "test"})
        for i in range(4):
            role = "user" if i % 2 == 0 else "assistant"
            sm.append_message("T1", "U1", sid, {"role": role, "content": f"msg{i}"})

        removed = sm.rollback_turns("T1", "U1", sid, n=2)
        assert removed == 4
        messages = sm.load_messages("T1", "U1", sid)
        assert len(messages) == 0

    def test_rollback_0_noop(self, tmp_path):
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "test"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "hello"})
        removed = sm.rollback_turns("T1", "U1", sid, n=0)
        assert removed == 0

    def test_rollback_preserves_metadata(self, tmp_path):
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "test"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "hello"})
        sm.append_message("T1", "U1", sid, {"role": "assistant", "content": "hi"})
        sm.rollback_turns("T1", "U1", sid, n=1)
        # Session should still exist
        assert sm.session_exists("T1", "U1", sid)


# ── #20 Undo ──

class TestUndo:

    def test_undo_restores_modified_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("original")
        tracker = TurnDiffTracker(workspace=str(tmp_path))
        tracker.capture_baseline(str(f))
        f.write_text("modified")
        tracker.record_write(str(f), "modify")
        results = tracker.undo_all()
        assert len(results) == 1
        assert results[0]["restored"]
        assert f.read_text() == "original"

    def test_undo_deletes_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        tracker = TurnDiffTracker(workspace=str(tmp_path))
        tracker.capture_baseline(str(f))
        f.write_text("new content")
        tracker.record_write(str(f), "create")
        results = tracker.undo_all()
        assert results[0]["restored"]
        assert not f.exists()

    def test_undo_empty_tracker(self, tmp_path):
        tracker = TurnDiffTracker(workspace=str(tmp_path))
        results = tracker.undo_all()
        assert results == []


# ── #48 Skill frontmatter 增强 ──

class TestFrontmatterEnhanced:

    def test_comments_ignored(self):
        raw = "---\nname: test\n# This is a comment\ndescription: hello\n---\n\nBody"
        meta, body = _parse_frontmatter(raw)
        assert meta["name"] == "test"
        assert meta["description"] == "hello"
        assert "#" not in str(meta.values())

    def test_multiline_description(self):
        raw = "---\nname: test\ndescription: line1\n  line2 continued\ntype: capability\n---\n\nBody"
        meta, body = _parse_frontmatter(raw)
        assert "line1" in meta["description"]
        assert "line2" in meta["description"]
        assert meta["type"] == "capability"

    def test_basic_parsing_still_works(self):
        raw = "---\nname: my_skill\nversion: 1\ndescription: A test skill\ntype: domain\nbusiness_types: [reimbursement, travel]\n---\n\nSkill body here."
        meta, body = _parse_frontmatter(raw)
        assert meta["name"] == "my_skill"
        assert meta["version"] == 1
        assert meta["type"] == "domain"
        assert "reimbursement" in meta["business_types"]
        assert body == "Skill body here."

    def test_quoted_values(self):
        raw = '---\nname: "my skill"\ndescription: \'has: colons\'\n---\n\nBody'
        meta, body = _parse_frontmatter(raw)
        assert meta["name"] == "my skill"
        assert meta["description"] == "has: colons"

    def test_no_frontmatter(self):
        raw = "Just a plain markdown file."
        meta, body = _parse_frontmatter(raw)
        assert meta == {}
        assert body == raw


# ── #30 Skill 热重载 ──

class TestSkillHotReload:

    def _make_skill(self, skills_dir, name):
        d = os.path.join(skills_dir, "builtin", name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {name}\ntype: capability\ndescription: test\n---\n\nBody\n")

    def test_reload_all(self, tmp_path):
        skills_dir = str(tmp_path)
        self._make_skill(skills_dir, "skill_a")
        loader = SkillLoader(skills_dir=skills_dir)
        assert len(loader.list_skills()) == 1

        # Add a new skill
        self._make_skill(skills_dir, "skill_b")
        count = loader.reload_all()
        assert count == 2
        assert len(loader.list_skills()) == 2

    def test_invalidate_cache(self, tmp_path):
        skills_dir = str(tmp_path)
        self._make_skill(skills_dir, "cached_skill")
        loader = SkillLoader(skills_dir=skills_dir)
        # Load body to populate cache
        loader.get_skill_body("cached_skill")
        assert "cached_skill" in loader._body_cache
        # Invalidate
        loader.invalidate_cache("cached_skill")
        assert "cached_skill" not in loader._body_cache

    def test_invalidate_nonexistent(self, tmp_path):
        loader = SkillLoader(skills_dir=str(tmp_path))
        assert not loader.invalidate_cache("nope")
