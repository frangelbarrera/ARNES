"""TaskRouter — classifies a natural-language request into a task domain.

Uses keyword heuristics (no LLM call) so it works offline and is
deterministic. The router returns a :class:`TaskDomain` enum member; the
:class:`PlaybookLibrary` maps that to a :class:`TaskTemplate`.

Design notes:

- Keyword lists are intentionally broad (multi-word phrases + single
  tokens) to catch common phrasings. False positives are acceptable — the
  planner still shows the user the selected template and lets them
  override with ``--template generic``.
- The router scores EVERY domain and returns the highest-scoring one, not
  the first match. This handles requests that mention multiple domains
  (e.g. "research the market for my Android app" — software + research).
- ``generic`` is the fallback when no domain scores above the threshold.
"""

from __future__ import annotations

import re
from collections import Counter

from arnes.playbooks.library.domains import TaskDomain

# Keyword weights per domain. Higher weight = stronger signal.
# Phrases (multi-word) get higher weights than single tokens because they
# are more specific.
_DOMAIN_KEYWORDS: dict[TaskDomain, dict[str, int]] = {
    TaskDomain.SOFTWARE_MOBILE: {
        "android": 5,
        "ios": 5,
        "mobile app": 6,
        "play store": 5,
        "app store": 5,
        "flutter": 4,
        "react native": 4,
        "kotlin": 3,
        "swift": 3,
        "mobile": 2,
        "apk": 3,
    },
    TaskDomain.SOFTWARE_WEB: {
        "web app": 5,
        "website": 4,
        "frontend": 4,
        "react": 3,
        "vue": 3,
        "next.js": 4,
        "django": 3,
        "flask": 3,
        "web page": 3,
        "landing page": 3,
        "dashboard": 2,
    },
    TaskDomain.SOFTWARE_CLI: {
        "cli": 5,
        "command line": 5,
        "terminal": 4,
        "script": 3,
        "shell script": 4,
        "automation": 3,
        "tool": 1,
    },
    TaskDomain.SOFTWARE_API: {
        "rest api": 6,
        "api": 3,
        "endpoint": 3,
        "graphql": 5,
        "microservice": 4,
        "webhook": 4,
        "openapi": 5,
        "swagger": 4,
        "backend": 2,
    },
    TaskDomain.OSINT: {
        "osint": 8,
        "investigate": 4,
        "investigation": 5,
        "reconnaissance": 5,
        "recon": 5,
        "background check": 5,
        "person": 1,
        "company research": 5,
        "threat intelligence": 5,
        "social media": 2,
        "public records": 5,
        "shodan": 6,
        "dox": 6,
    },
    TaskDomain.FINANCIAL_ANALYSIS: {
        "financial": 6,
        "finance": 5,
        "investment": 6,
        "stock": 5,
        "portfolio": 5,
        "valuation": 5,
        "roi": 4,
        "crypto": 4,
        "bitcoin": 4,
        "trading": 5,
        "market analysis": 3,
        "economic": 3,
        "revenue": 3,
        "profit": 2,
    },
    TaskDomain.SECURITY_AUDIT: {
        "security audit": 7,
        "vulnerability": 6,
        "pen test": 6,
        "penetration test": 7,
        "pentest": 6,
        "cve": 5,
        "exploit": 5,
        "secure code": 5,
        "compliance": 4,
        "gdpr": 4,
        "hipaa": 4,
        "pci-dss": 4,
        "soc 2": 4,
        "owasp": 5,
    },
    TaskDomain.DATA_ANALYSIS: {
        "data analysis": 6,
        "data science": 6,
        "machine learning": 5,
        "ml model": 5,
        "dataset": 5,
        "pandas": 4,
        "numpy": 3,
        "visualization": 4,
        "statistics": 4,
        "regression": 4,
        "classification": 3,
        "clustering": 4,
        "nlp": 4,
        "sentiment": 3,
    },
    TaskDomain.DEVOPS: {
        "devops": 6,
        "ci/cd": 6,
        "pipeline": 4,
        "docker": 4,
        "kubernetes": 5,
        "k8s": 5,
        "terraform": 5,
        "ansible": 5,
        "deployment": 4,
        "infrastructure": 4,
        "aws": 3,
        "gcp": 3,
        "azure": 3,
        "helm": 4,
        "monitoring": 3,
    },
    TaskDomain.DESIGN: {
        "graphic design": 7,
        "logo": 5,
        "poster": 5,
        "branding": 5,
        "ui design": 5,
        "ux design": 5,
        "figma": 4,
        "illustration": 4,
        "typography": 4,
        "color palette": 4,
        "design system": 4,
        "mockup": 4,
        "wireframe": 4,
        "icon": 3,
    },
    TaskDomain.CONTENT: {
        "blog post": 5,
        "article": 4,
        "write content": 4,
        "copywriting": 5,
        "documentation": 4,
        "docs": 3,
        "newsletter": 4,
        "social media post": 4,
        "seo": 3,
        "essay": 3,
        "whitepaper": 4,
        "ebook": 4,
    },
    TaskDomain.RESEARCH: {
        "academic research": 6,
        "literature review": 6,
        "paper": 3,
        "cite": 3,
        "bibliography": 5,
        "hypothesis": 4,
        "experiment": 4,
        "survey": 3,
        "study": 2,
        "systematic review": 6,
        "meta-analysis": 5,
    },
}

# Minimum score required to classify as a specific domain (vs. generic).
_MIN_SCORE = 4


class TaskRouter:
    """Classify a natural-language request into a :class:`TaskDomain`.

    Usage::

        router = TaskRouter()
        domain = router.classify("Build an Android app for dating")
        # → TaskDomain.SOFTWARE_MOBILE

        template = library.get(domain)
        if template:
            yaml = template.to_playbook_yaml()
    """

    def classify(self, request: str) -> TaskDomain:
        """Return the best-matching domain for ``request``.

        Returns :attr:`TaskDomain.GENERIC` when no domain scores above the
        threshold.
        """
        if not request or not request.strip():
            return TaskDomain.GENERIC

        text = request.lower()
        scores: Counter[TaskDomain] = Counter()

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            for phrase, weight in keywords.items():
                # Word-boundary match for single tokens; substring for phrases.
                if " " in phrase:
                    if phrase in text:
                        scores[domain] += weight
                else:
                    # \b ensures "ios" doesn't match inside "various".
                    pattern = r"\b" + re.escape(phrase) + r"\b"
                    if re.search(pattern, text):
                        scores[domain] += weight

        if not scores:
            return TaskDomain.GENERIC

        best_domain, best_score = scores.most_common(1)[0]
        if best_score < _MIN_SCORE:
            return TaskDomain.GENERIC
        return best_domain

    def classify_with_confidence(self, request: str) -> tuple[TaskDomain, float, dict[str, int]]:
        """Return ``(domain, confidence, all_scores)``.

        Confidence is the best score divided by the sum of all scores (0..1).
        ``all_scores`` is the raw per-domain score dict for debugging /
        display.
        """
        if not request or not request.strip():
            return TaskDomain.GENERIC, 0.0, {}

        text = request.lower()
        scores: Counter[TaskDomain] = Counter()

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            for phrase, weight in keywords.items():
                if " " in phrase:
                    if phrase in text:
                        scores[domain] += weight
                else:
                    pattern = r"\b" + re.escape(phrase) + r"\b"
                    if re.search(pattern, text):
                        scores[domain] += weight

        if not scores:
            return TaskDomain.GENERIC, 0.0, {}

        best_domain, best_score = scores.most_common(1)[0]
        total = sum(scores.values())
        confidence = best_score / total if total else 0.0
        if best_score < _MIN_SCORE:
            return TaskDomain.GENERIC, 0.0, {str(d): s for d, s in scores.items()}
        return best_domain, confidence, {str(d): s for d, s in scores.items()}
