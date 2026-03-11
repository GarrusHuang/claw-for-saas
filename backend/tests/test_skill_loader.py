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
