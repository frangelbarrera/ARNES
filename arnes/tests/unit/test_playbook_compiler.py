"""Tests for arnes.playbooks.compiler."""

from __future__ import annotations

import pytest

from arnes.playbooks.compiler import PlaybookCompileError, PlaybookCompiler


class TestPlaybookCompiler:
    """Tests for playbook compilation."""

    def test_compile_minimal_playbook(self):
        yaml_str = """
name: test
objective: Test playbook
budget_usd: 0.10

steps:
  - id: step1
    specialist: "@planner"
    input:
      task: "Test"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.metadata.name == "test"
        assert len(playbook.steps) == 1
        assert playbook.steps[0].id == "step1"
        assert playbook.steps[0].specialist == "@planner"

    def test_compile_invalid_yaml(self):
        yaml_str = "this is not: valid: yaml: ["
        with pytest.raises(PlaybookCompileError, match="YAML parse"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_missing_name(self):
        yaml_str = """
objective: No name
steps:
  - id: s1
    specialist: "@planner"
"""
        with pytest.raises(PlaybookCompileError, match="name"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_duplicate_step_ids(self):
        yaml_str = """
name: test
objective: Test
steps:
  - id: dup
    specialist: "@planner"
  - id: dup
    specialist: "@coder"
"""
        with pytest.raises(PlaybookCompileError, match="Duplicate step IDs"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_specialist_must_start_with_at(self):
        yaml_str = """
name: test
objective: Test
steps:
  - id: s1
    specialist: planner
"""
        with pytest.raises(PlaybookCompileError, match="must start with '@'"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_parallel_steps(self):
        yaml_str = """
name: test
objective: Test
steps:
  - id: parallel_branch
    parallel:
      - id: sub1
        specialist: "@planner"
      - id: sub2
        specialist: "@coder"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.steps[0].parallel is not None
        assert len(playbook.steps[0].parallel) == 2

    def test_compile_conditional_branch(self):
        yaml_str = """
name: test
objective: Test
steps:
  - id: s1
    specialist: "@planner"
    if_not_met:
      action: terminate
      terminate: rejected
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.steps[0].if_not_met is not None
        assert playbook.steps[0].if_not_met.action == "terminate"
        assert playbook.steps[0].if_not_met.terminate == "rejected"

    def test_compile_with_variables(self):
        yaml_str = """
name: test
objective: Test
variables:
  pr_number: 1234
  repo: "org/repo"
steps:
  - id: s1
    specialist: "@planner"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.variables["pr_number"] == 1234
        assert playbook.variables["repo"] == "org/repo"

    def test_compile_legacy_spanish_keys_translated(self):
        """Legacy ES keys should be translated to canonical EN keys."""
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: s1
    especialista: "@planner"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.metadata.name == "test"
        assert playbook.steps[0].specialist == "@planner"

    def test_compile_from_file(self, tmp_path):
        yaml_str = """
name: from_file
objective: Test
steps:
  - id: s1
    specialist: "@planner"
"""
        path = tmp_path / "test.yaml"
        path.write_text(yaml_str)
        playbook = PlaybookCompiler.from_file(path)
        assert playbook.metadata.name == "from_file"

    def test_compile_file_not_found(self):
        with pytest.raises(PlaybookCompileError, match="File not found"):
            PlaybookCompiler.from_file("/nonexistent/path.yaml")

    def test_compile_step_must_have_action(self):
        """Step without specialist/tool/parallel should fail."""
        yaml_str = """
name: test
objective: Test
steps:
  - id: s1
"""
        with pytest.raises(PlaybookCompileError):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_step_with_multiple_actions_fails(self):
        yaml_str = """
name: test
objective: Test
steps:
  - id: s1
    specialist: "@planner"
    tool: shell
"""
        with pytest.raises(PlaybookCompileError):
            PlaybookCompiler.from_string(yaml_str)
