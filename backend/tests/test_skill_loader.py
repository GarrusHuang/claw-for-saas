"""
Tests for skills/loader.py — SkillLoader and _parse_frontmatter.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from skills.loader import SkillLoader, _parse_frontmatter


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def skill_dir(tmp_path):
    """Create a test skill directory with a valid SKILL.md."""
    d = tmp_path / "test-skill"
    d.mkdir()
    (d / "SKILL.md").write_text('''---
name: test-skill
description: A test skill
type: domain
version: "1.0"
business_types: [reimbursement]
applies_to: [universal]
---

This is a test skill body with enough content to pass validation checks and provide meaningful test coverage for the skill loading system.
''')
    return tmp_path


@pytest.fixture
def multi_skill_dir(tmp_path):
    """Create multiple test skills for matching tests."""
    # Domain skill
    d1 = tmp_path / "domain-skill"
    d1.mkdir()
    (d1 / "SKILL.md").write_text('''---
name: domain-skill
description: A domain skill
type: domain
version: "1.0"
business_types: [reimbursement, travel]
applies_to: [universal]
---

Domain skill body content for testing domain matching logic in the skill loader system.
''')

    # Capability skill
    d2 = tmp_path / "cap-skill"
    d2.mkdir()
    (d2 / "SKILL.md").write_text('''---
name: cap-skill
description: A capability skill
type: capability
version: "1.0"
applies_to: [universal]
---

Capability skill body content for testing capability matching logic in the skill loader system.
''')

    # Scenario skill
    d3 = tmp_path / "reimbursement_create"
    d3.mkdir()
    (d3 / "SKILL.md").write_text('''---
name: reimbursement_create
description: Reimbursement creation scenario
type: scenario
version: "1.0"
---

Scenario skill body content for testing scenario matching logic in the skill loader system.
''')

    return tmp_path


# ──────────────────────────────────────────────
# Tests for _parse_frontmatter
# ──────────────────────────────────────────────

class TestParseFrontmatter:
    """Tests for the _parse_frontmatter function."""

    def test_valid_yaml_simple_key_value(self):
        """Valid YAML frontmatter with simple key-value pairs."""
        raw = """---
name: my-skill
description: A great skill
type: domain
---

Body text here."""
        metadata, body = _parse_frontmatter(raw)
        assert metadata["name"] == "my-skill"
        assert metadata["description"] == "A great skill"
        assert metadata["type"] == "domain"
        assert body == "Body text here."

    def test_list_values(self):
        """List values in [item1, item2] format."""
        raw = """---
name: list-skill
applies_to: [agent1, agent2]
business_types: [reimbursement, travel]
---

Body."""
        metadata, body = _parse_frontmatter(raw)
        assert metadata["applies_to"] == ["agent1", "agent2"]
        assert metadata["business_types"] == ["reimbursement", "travel"]

    def test_no_frontmatter(self):
        """No frontmatter returns empty dict, full text as body."""
        raw = "Just plain text without frontmatter."
        metadata, body = _parse_frontmatter(raw)
        assert metadata == {}
        assert body == raw

    def test_quoted_values(self):
        """Quoted values (single and double quotes) are unquoted."""
        raw = '''---
name: "quoted-skill"
version: '2.0'
---

Body.'''
        metadata, body = _parse_frontmatter(raw)
        assert metadata["name"] == "quoted-skill"
        assert metadata["version"] == "2.0"

    def test_integer_values(self):
        """Integer values are parsed as int."""
        raw = """---
name: int-skill
token_estimate: 500
priority: 10
---

Body."""
        metadata, body = _parse_frontmatter(raw)
        assert metadata["token_estimate"] == 500
        assert isinstance(metadata["token_estimate"], int)
        assert metadata["priority"] == 10
        assert isinstance(metadata["priority"], int)


# ──────────────────────────────────────────────
# Tests for SkillLoader
# ──────────────────────────────────────────────

class TestSkillLoader:
    """Tests for the SkillLoader class."""

    def test_init_nonexistent_dir(self, tmp_path):
        """Init with nonexistent dir causes no error, empty registry."""
        loader = SkillLoader(skills_dir=str(tmp_path / "nonexistent"))
        assert loader.list_skills() == []

    def test_init_with_valid_skills_dir(self, skill_dir):
        """Init with valid skills dir scans and registers."""
        loader = SkillLoader(skills_dir=str(skill_dir))
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill"

    def test_list_skills_excludes_internal_dir(self, skill_dir):
        """list_skills returns metadata without internal _dir."""
        loader = SkillLoader(skills_dir=str(skill_dir))
        skills = loader.list_skills()
        for s in skills:
            assert "_dir" not in s

    def test_load_for_pipeline_scenario_match(self, multi_skill_dir):
        """load_for_pipeline with scenario match."""
        loader = SkillLoader(skills_dir=str(multi_skill_dir))
        result = loader.load_for_pipeline(scenario="reimbursement_create")
        assert "Scenario skill body" in result

    def test_load_for_pipeline_domain_match(self, multi_skill_dir):
        """load_for_pipeline with domain match by business_type."""
        loader = SkillLoader(skills_dir=str(multi_skill_dir))
        result = loader.load_for_pipeline(business_type="reimbursement")
        assert "Domain skill body" in result

    def test_load_for_pipeline_capability_match(self, multi_skill_dir):
        """load_for_pipeline with capability match."""
        loader = SkillLoader(skills_dir=str(multi_skill_dir))
        result = loader.load_for_pipeline(agent_name="universal")
        assert "Capability skill body" in result

    def test_read_reference_path_traversal(self, skill_dir):
        """read_reference with path traversal returns error."""
        loader = SkillLoader(skills_dir=str(skill_dir))
        result = loader.read_reference("test-skill", "../../etc/passwd")
        assert "[ERROR]" in result

    def test_read_reference_nonexistent_skill(self, skill_dir):
        """read_reference with nonexistent skill returns error."""
        loader = SkillLoader(skills_dir=str(skill_dir))
        result = loader.read_reference("no-such-skill", "file.md")
        assert "[ERROR]" in result

    def test_create_skill(self, tmp_path):
        """create_skill creates dir + SKILL.md, appears in registry."""
        loader = SkillLoader(skills_dir=str(tmp_path))
        result = loader.create_skill(
            name="new-skill",
            metadata={"type": "domain", "description": "New skill"},
            body="This is the new skill body content for testing the create operation.",
        )
        assert result["ok"] is True
        assert result["name"] == "new-skill"
        # Verify it appears in registry
        skills = loader.list_skills()
        names = [s["name"] for s in skills]
        assert "new-skill" in names
        # Verify file exists
        assert (tmp_path / "new-skill" / "SKILL.md").exists()

    def test_update_skill(self, skill_dir):
        """update_skill updates content, clears cache."""
        loader = SkillLoader(skills_dir=str(skill_dir))
        # First load the body to populate cache
        loader.load_for_pipeline(business_type="reimbursement")
        # Now update
        result = loader.update_skill(
            name="test-skill",
            metadata={
                "type": "domain",
                "description": "Updated skill",
                "business_types": ["reimbursement"],
                "applies_to": ["universal"],
            },
            body="Updated body content for testing the update operation in the skill loader.",
        )
        assert result["ok"] is True
        # Verify updated content is loaded (cache cleared)
        text = loader.load_for_pipeline(business_type="reimbursement")
        assert "Updated body content" in text

    def test_delete_skill(self, skill_dir):
        """delete_skill removes dir and registry entry."""
        loader = SkillLoader(skills_dir=str(skill_dir))
        assert len(loader.list_skills()) == 1
        result = loader.delete_skill("test-skill")
        assert result["ok"] is True
        assert len(loader.list_skills()) == 0
        assert not (skill_dir / "test-skill").exists()

    def test_delete_skill_nonexistent(self, tmp_path):
        """delete_skill nonexistent returns error."""
        loader = SkillLoader(skills_dir=str(tmp_path))
        result = loader.delete_skill("no-such-skill")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_import_from_content_valid(self, tmp_path):
        """import_from_content with valid content."""
        loader = SkillLoader(skills_dir=str(tmp_path))
        raw = """---
name: imported-skill
description: An imported skill
type: capability
version: "1.0"
---

Imported skill body content for testing the import operation in the skill loader system.
"""
        result = loader.import_from_content(raw)
        assert result["ok"] is True
        assert result["name"] == "imported-skill"
        skills = loader.list_skills()
        names = [s["name"] for s in skills]
        assert "imported-skill" in names

    def test_import_from_content_without_name(self, tmp_path):
        """import_from_content without name returns error."""
        loader = SkillLoader(skills_dir=str(tmp_path))
        raw = """---
description: No name here
type: capability
---

Body without name in frontmatter for testing error handling.
"""
        result = loader.import_from_content(raw)
        assert result["ok"] is False
        assert "name" in result["error"].lower()


# ──────────────────────────────────────────────
# A7: 多源加载 + 优先级合并 + 大小预算
# ──────────────────────────────────────────────

class TestA7MultiSource:
    """Tests for A7 multi-source loading with priority merging."""

    def test_higher_priority_overrides_same_name(self, tmp_path):
        """Higher priority skill overrides lower priority same-name skill."""
        # Create builtin skill
        builtin_dir = tmp_path / "builtin"
        d1 = builtin_dir / "my-skill"
        d1.mkdir(parents=True)
        (d1 / "SKILL.md").write_text('''---
name: my-skill
type: capability
---

Builtin version of my-skill with lower priority content.
''')

        # Create tenant skill with same name
        tenant_dir = tmp_path / "tenant"
        d2 = tenant_dir / "my-skill"
        d2.mkdir(parents=True)
        (d2 / "SKILL.md").write_text('''---
name: my-skill
type: capability
---

Tenant version of my-skill with higher priority content.
''')

        loader = SkillLoader(skills_dir=str(builtin_dir))
        loader.load_tenant_skills(str(tenant_dir))

        # Tenant should override builtin
        result = loader.load_for_pipeline(agent_name="universal")
        assert "Tenant version" in result
        assert "Builtin version" not in result

    def test_lower_priority_does_not_override(self, tmp_path):
        """Lower priority skill does NOT override higher priority same-name skill."""
        # Create tenant skill first (priority 3)
        tenant_dir = tmp_path / "tenant"
        d1 = tenant_dir / "my-skill"
        d1.mkdir(parents=True)
        (d1 / "SKILL.md").write_text('''---
name: my-skill
type: capability
---

Tenant version with higher priority.
''')

        # Create builtin with same name (priority 1)
        builtin_dir = tmp_path / "builtin"
        d2 = builtin_dir / "my-skill"
        d2.mkdir(parents=True)
        (d2 / "SKILL.md").write_text('''---
name: my-skill
type: capability
---

Builtin version with lower priority.
''')

        loader = SkillLoader(skills_dir=str(builtin_dir))
        loader.load_tenant_skills(str(tenant_dir))

        # Now try to re-scan builtin — should NOT override tenant
        from skills.loader import PRIORITY_BUILTIN
        loader._scan_directory(str(builtin_dir), PRIORITY_BUILTIN)

        result = loader.load_for_pipeline(agent_name="universal")
        assert "Tenant version" in result

    def test_load_tenant_skills(self, tmp_path):
        """load_tenant_skills loads from tenant directory."""
        tenant_dir = tmp_path / "tenant"
        d = tenant_dir / "tenant-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text('''---
name: tenant-skill
type: capability
---

Tenant skill body content for testing tenant loading.
''')

        loader = SkillLoader(skills_dir=str(tmp_path / "empty"))
        count = loader.load_tenant_skills(str(tenant_dir))
        assert count == 1
        skills = loader.list_skills()
        assert any(s["name"] == "tenant-skill" for s in skills)

    def test_load_user_skills(self, tmp_path):
        """load_user_skills loads from user directory."""
        user_dir = tmp_path / "user"
        d = user_dir / "user-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text('''---
name: user-skill
type: capability
---

User skill body content for testing user loading.
''')

        loader = SkillLoader(skills_dir=str(tmp_path / "empty"))
        count = loader.load_user_skills(str(user_dir))
        assert count == 1
        skills = loader.list_skills()
        assert any(s["name"] == "user-skill" for s in skills)

    def test_register_plugin_skill(self, tmp_path):
        """register_plugin_skill adds skill with PRIORITY_PLUGIN."""
        loader = SkillLoader(skills_dir=str(tmp_path / "empty"))
        loader.register_plugin_skill(
            name="plugin-skill",
            metadata={"type": "capability", "description": "From plugin"},
            body="Plugin skill body content for testing plugin registration.",
        )
        skills = loader.list_skills()
        assert any(s["name"] == "plugin-skill" for s in skills)

    def test_list_skills_shows_priority(self, tmp_path):
        """list_skills includes priority field."""
        loader = SkillLoader(skills_dir=str(tmp_path / "empty"))
        loader.register_plugin_skill(
            name="p-skill",
            metadata={"type": "capability"},
            body="Body.",
        )
        skills = loader.list_skills()
        assert skills[0]["priority"] == 2  # PRIORITY_PLUGIN


class TestA7Budget:
    """Tests for A7 size budget control."""

    def test_single_skill_truncation(self, tmp_path):
        """Single skill exceeding max_single_chars is truncated."""
        d = tmp_path / "big-skill"
        d.mkdir()
        big_body = "x" * 15000
        (d / "SKILL.md").write_text(f'''---
name: big-skill
type: capability
---

{big_body}
''')

        loader = SkillLoader(skills_dir=str(tmp_path), max_single_chars=5000)
        result = loader.load_for_pipeline(agent_name="universal")
        assert len(result) < 15000
        assert "截断" in result

    def test_total_budget_drops_low_priority(self, tmp_path):
        """Skills exceeding total budget are dropped (low priority first)."""
        # Create two skills, each ~6000 chars
        for i, name in enumerate(["skill-a", "skill-b"]):
            d = tmp_path / name
            d.mkdir()
            body = f"Content for {name} " * 400  # ~6000 chars
            (d / "SKILL.md").write_text(f'''---
name: {name}
type: capability
---

{body}
''')

        loader = SkillLoader(skills_dir=str(tmp_path), max_prompt_chars=8000)
        result = loader.load_for_pipeline(agent_name="universal")
        # At least one skill should be loaded, one might be dropped
        assert len(result) <= 8000

    def test_budget_respects_max_prompt_chars(self, tmp_path):
        """Total output respects max_prompt_chars."""
        for name in ["s1", "s2", "s3"]:
            d = tmp_path / name
            d.mkdir()
            body = "y" * 5000
            (d / "SKILL.md").write_text(f'''---
name: {name}
type: capability
---

{body}
''')

        loader = SkillLoader(skills_dir=str(tmp_path), max_prompt_chars=7000)
        result = loader.load_for_pipeline(agent_name="universal")
        assert len(result) <= 7000


class TestA7DirectoryStructure:
    """Tests for A7 skills/builtin/ directory structure."""

    def test_builtin_subdir_scanned(self, tmp_path):
        """When skills/builtin/ exists, skills are scanned from there."""
        builtin = tmp_path / "builtin"
        d = builtin / "my-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text('''---
name: my-skill
type: capability
---

Skill from builtin subdirectory for testing directory structure.
''')

        loader = SkillLoader(skills_dir=str(tmp_path))
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "my-skill"

    def test_fallback_to_root_when_no_builtin(self, tmp_path):
        """When no builtin/ subdir exists, falls back to scanning root."""
        d = tmp_path / "root-skill"
        d.mkdir()
        (d / "SKILL.md").write_text('''---
name: root-skill
type: capability
---

Skill from root directory for testing fallback behavior.
''')

        loader = SkillLoader(skills_dir=str(tmp_path))
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "root-skill"

    def test_create_skill_goes_to_builtin(self, tmp_path):
        """create_skill puts new skills in builtin/ when it exists."""
        (tmp_path / "builtin").mkdir()
        loader = SkillLoader(skills_dir=str(tmp_path))
        result = loader.create_skill(
            name="new-skill",
            metadata={"type": "capability"},
            body="New skill body content for testing create location.",
        )
        assert result["ok"] is True
        assert (tmp_path / "builtin" / "new-skill" / "SKILL.md").exists()

    def test_import_goes_to_builtin(self, tmp_path):
        """import_from_content puts imported skills in builtin/ when it exists."""
        (tmp_path / "builtin").mkdir()
        loader = SkillLoader(skills_dir=str(tmp_path))
        raw = '''---
name: imported-skill
type: capability
---

Imported skill body for testing import location.
'''
        result = loader.import_from_content(raw)
        assert result["ok"] is True
        assert (tmp_path / "builtin" / "imported-skill" / "SKILL.md").exists()
