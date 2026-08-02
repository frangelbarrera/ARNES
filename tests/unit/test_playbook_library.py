"""Tests for the playbook library (TaskRouter + PlaybookLibrary + templates)."""

from __future__ import annotations

import pytest

from arnes.playbooks.library import PlaybookLibrary, TaskDomain, TaskRouter, get_default_library
from arnes.playbooks.library.templates import SpecialistStep, TaskTemplate

# ============================================================
# TaskRouter
# ============================================================


class TestTaskRouter:
    @pytest.fixture
    def router(self) -> TaskRouter:
        return TaskRouter()

    @pytest.mark.parametrize(
        ("request_text", "expected_domain"),
        [
            ("Build an Android dating app for the Play Store", TaskDomain.SOFTWARE_MOBILE),
            ("Create an iOS app with React Native", TaskDomain.SOFTWARE_MOBILE),
            ("Build a web app with Next.js and a dashboard", TaskDomain.SOFTWARE_WEB),
            ("Write a CLI tool in Python for file conversion", TaskDomain.SOFTWARE_CLI),
            ("Design a REST API with OpenAPI documentation", TaskDomain.SOFTWARE_API),
            ("OSINT investigation on a company's background", TaskDomain.OSINT),
            ("Financial analysis of Apple stock for investment", TaskDomain.FINANCIAL_ANALYSIS),
            ("Security audit of our codebase for OWASP compliance", TaskDomain.SECURITY_AUDIT),
            ("Data analysis on our customer dataset with pandas", TaskDomain.DATA_ANALYSIS),
            ("Set up a CI/CD pipeline with Kubernetes and Terraform", TaskDomain.DEVOPS),
            ("Design a logo and brand identity for my startup", TaskDomain.DESIGN),
            ("Write a blog post about cooking recipes", TaskDomain.CONTENT),
            ("Academic research literature review on NLP", TaskDomain.RESEARCH),
        ],
    )
    def test_classify_known_domains(
        self, router: TaskRouter, request_text: str, expected_domain: TaskDomain
    ) -> None:
        domain = router.classify(request_text)
        assert domain == expected_domain, (
            f"Expected {expected_domain.value} for '{request_text}', got {domain.value}"
        )

    def test_classify_generic_fallback(self, router: TaskRouter) -> None:
        """Vague requests with no domain keywords return GENERIC."""
        assert router.classify("do something") == TaskDomain.GENERIC
        assert router.classify("") == TaskDomain.GENERIC
        assert router.classify("hello") == TaskDomain.GENERIC

    def test_classify_with_confidence_returns_scores(self, router: TaskRouter) -> None:
        domain, confidence, scores = router.classify_with_confidence("Build an Android app")
        assert domain == TaskDomain.SOFTWARE_MOBILE
        assert 0.0 < confidence <= 1.0
        assert TaskDomain.SOFTWARE_MOBILE in scores
        assert scores[TaskDomain.SOFTWARE_MOBILE] >= 4

    def test_word_boundary_matching(self, router: TaskRouter) -> None:
        """'ios' must not match inside 'various' — word boundaries are enforced."""
        # 'various' contains 'ios' as a substring but \b prevents the match.
        domain = router.classify("Summarise various topics briefly")
        assert domain == TaskDomain.GENERIC


# ============================================================
# PlaybookLibrary
# ============================================================


class TestPlaybookLibrary:
    @pytest.fixture
    def library(self) -> PlaybookLibrary:
        return get_default_library()

    def test_has_all_expected_templates(self, library: PlaybookLibrary) -> None:
        names = set(library.list_names())
        expected = {
            TaskDomain.SOFTWARE_MOBILE.value,
            TaskDomain.SOFTWARE_WEB.value,
            TaskDomain.SOFTWARE_CLI.value,
            TaskDomain.SOFTWARE_API.value,
            TaskDomain.OSINT.value,
            TaskDomain.FINANCIAL_ANALYSIS.value,
            TaskDomain.SECURITY_AUDIT.value,
            TaskDomain.DATA_ANALYSIS.value,
            TaskDomain.DEVOPS.value,
            TaskDomain.DESIGN.value,
            TaskDomain.CONTENT.value,
            TaskDomain.RESEARCH.value,
            TaskDomain.GENERIC.value,
        }
        assert names == expected, f"Missing templates: {expected - names}"

    def test_get_returns_template(self, library: PlaybookLibrary) -> None:
        t = library.get("osint")
        assert t is not None
        assert t.name == "osint"
        assert len(t.specialists) >= 3

    def test_get_unknown_returns_none(self, library: PlaybookLibrary) -> None:
        assert library.get("nonexistent") is None

    def test_match_returns_template(self, library: PlaybookLibrary) -> None:
        t = library.match("Build an Android app")
        assert t.name == TaskDomain.SOFTWARE_MOBILE.value

    def test_match_generic_fallback(self, library: PlaybookLibrary) -> None:
        t = library.match("do something vague")
        assert t.name == TaskDomain.GENERIC.value

    def test_every_template_has_at_least_one_specialist(self, library: PlaybookLibrary) -> None:
        for t in library.list_templates():
            assert len(t.specialists) >= 1, f"Template {t.name} has no specialists"

    def test_every_template_has_valid_specialist_names(self, library: PlaybookLibrary) -> None:
        for t in library.list_templates():
            for step in t.specialists:
                assert step.specialist.startswith("@"), (
                    f"Template {t.name} step specialist '{step.specialist}' must start with @"
                )

    def test_every_template_has_risks(self, library: PlaybookLibrary) -> None:
        for t in library.list_templates():
            if t.name == TaskDomain.GENERIC.value:
                continue
            assert len(t.risks) >= 3, (
                f"Template {t.name} should have at least 3 risks, got {len(t.risks)}"
            )

    def test_every_non_generic_template_has_clarifying_questions(
        self, library: PlaybookLibrary
    ) -> None:
        for t in library.list_templates():
            if t.name == TaskDomain.GENERIC.value:
                continue
            assert len(t.clarifying_questions) >= 3, (
                f"Template {t.name} should have at least 3 clarifying questions"
            )

    def test_every_non_generic_template_has_domain_context(self, library: PlaybookLibrary) -> None:
        for t in library.list_templates():
            if t.name == TaskDomain.GENERIC.value:
                continue
            assert len(t.domain_context) >= 50, (
                f"Template {t.name} domain_context too short ({len(t.domain_context)} chars)"
            )


# ============================================================
# TaskTemplate.to_playbook_yaml
# ============================================================


class TestTemplateToYaml:
    def test_to_playbook_yaml_produces_valid_yaml(self) -> None:
        template = TaskTemplate(
            name="test",
            title="Test Template",
            description="A test.",
            specialists=[
                SpecialistStep(specialist="@planner", purpose="Plan", input_hint="Plan it"),
                SpecialistStep(specialist="@coder", purpose="Code", input_hint="Code it"),
            ],
        )
        yaml_str = template.to_playbook_yaml(name="test-pb", objective="Test objective")
        assert "name: test-pb" in yaml_str
        assert 'specialist: "@planner"' in yaml_str
        assert 'specialist: "@coder"' in yaml_str
        assert "objective: Test objective" in yaml_str

    def test_to_summary_dict(self) -> None:
        template = TaskTemplate(
            name="test",
            title="Test",
            description="Desc",
            specialists=[SpecialistStep(specialist="@planner", purpose="Plan")],
            clarifying_questions=["Q1?"],
            risks=["R1"],
        )
        d = template.to_summary_dict()
        assert d["name"] == "test"
        assert d["title"] == "Test"
        assert d["specialists"] == ["@planner"]
        assert d["clarifying_questions"] == ["Q1?"]
        assert d["risks"] == ["R1"]
