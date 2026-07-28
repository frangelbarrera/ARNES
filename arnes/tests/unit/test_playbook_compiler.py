"""Tests for arnes.playbooks.compiler."""
from __future__ import annotations

import pytest

from arnes.playbooks.compiler import PlaybookCompiler, PlaybookCompileError


class TestPlaybookCompiler:
    """Tests for playbook compilation."""

    def test_compile_minimal_playbook(self):
        yaml_str = """
nombre: test
objetivo: Test playbook
budget_usd: 0.10

pasos:
  - id: step1
    especialista: "@planner"
    input:
      task: "Test"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.metadata.nombre == "test"
        assert len(playbook.pasos) == 1
        assert playbook.pasos[0].id == "step1"
        assert playbook.pasos[0].especialista == "@planner"

    def test_compile_invalid_yaml(self):
        yaml_str = "this is not: valid: yaml: ["
        with pytest.raises(PlaybookCompileError, match="YAML parse"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_missing_nombre(self):
        yaml_str = """
objetivo: No name
pasos:
  - id: s1
    especialista: "@planner"
"""
        with pytest.raises(PlaybookCompileError, match="nombre"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_duplicate_step_ids(self):
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: dup
    especialista: "@planner"
  - id: dup
    especialista: "@coder"
"""
        with pytest.raises(PlaybookCompileError, match="Duplicate step IDs"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_specialist_must_start_with_at(self):
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: s1
    especialista: planner
"""
        with pytest.raises(PlaybookCompileError, match="must start with '@'"):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_parallel_steps(self):
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: parallel_branch
    paralelo:
      - id: sub1
        especialista: "@planner"
      - id: sub2
        especialista: "@coder"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.pasos[0].paralelo is not None
        assert len(playbook.pasos[0].paralelo) == 2

    def test_compile_conditional_branch(self):
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: s1
    especialista: "@planner"
    si_no_se_cumple:
      accion: terminar
      terminar: rechazado
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.pasos[0].si_no_se_cumple is not None
        assert playbook.pasos[0].si_no_se_cumple.accion == "terminar"
        assert playbook.pasos[0].si_no_se_cumple.terminar == "rechazado"

    def test_compile_with_variables(self):
        yaml_str = """
nombre: test
objetivo: Test
variables:
  pr_number: 1234
  repo: "org/repo"
pasos:
  - id: s1
    especialista: "@planner"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.variables["pr_number"] == 1234
        assert playbook.variables["repo"] == "org/repo"

    def test_compile_bilingual_keys(self):
        """English keys should be translated to canonical Spanish."""
        yaml_str = """
name: test
steps:
  - id: s1
    specialist: "@planner"
"""
        playbook = PlaybookCompiler.from_string(yaml_str)
        assert playbook.metadata.nombre == "test"
        assert playbook.pasos[0].especialista == "@planner"

    def test_compile_from_file(self, tmp_path):
        yaml_str = """
nombre: from_file
objetivo: Test
pasos:
  - id: s1
    especialista: "@planner"
"""
        path = tmp_path / "test.yaml"
        path.write_text(yaml_str)
        playbook = PlaybookCompiler.from_file(path)
        assert playbook.metadata.nombre == "from_file"

    def test_compile_file_not_found(self):
        with pytest.raises(PlaybookCompileError, match="File not found"):
            PlaybookCompiler.from_file("/nonexistent/path.yaml")

    def test_compile_step_must_have_action(self):
        """Step without especialista/herramienta/paralelo should fail."""
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: s1
"""
        with pytest.raises(PlaybookCompileError):
            PlaybookCompiler.from_string(yaml_str)

    def test_compile_step_with_multiple_actions_fails(self):
        yaml_str = """
nombre: test
objetivo: Test
pasos:
  - id: s1
    especialista: "@planner"
    herramienta: shell
"""
        with pytest.raises(PlaybookCompileError):
            PlaybookCompiler.from_string(yaml_str)
