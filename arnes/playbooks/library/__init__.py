"""ARNES Playbook Library — a knowledge layer that maps natural-language
requests to domain-specific playbook templates.

The library has three parts:

1. :class:`TaskRouter` — classifies a free-text request into a task domain
   (``software_development``, ``osint``, ``financial_analysis``, ``design``,
   …) using keyword heuristics. Lightweight and deterministic; no LLM call
   needed so it works offline.

2. :class:`TaskTemplate` — a dataclass describing a domain: the specialists
   to invoke (in order), the tools each specialist needs, the clarifying
   questions to ask the user, domain context to inject into the system
   prompt, and the known risks.

3. :class:`PlaybookLibrary` — the catalogue of every shipped template. The
   proactive planner consults it to decide whether a request matches a known
   domain (in which case it uses the template's specialist sequence) or
   falls back to the generic single-shot planner.

This is the "neural network / knowledge base" layer: it gives the AI a
head start by encoding the institutional knowledge of *which specialist
does what, in what order, with which tools* for each common task type.
"""

from __future__ import annotations

from arnes.playbooks.library.catalog import PlaybookLibrary, get_default_library
from arnes.playbooks.library.domains import TaskDomain
from arnes.playbooks.library.router import TaskRouter
from arnes.playbooks.library.templates import TaskTemplate

__all__ = [
    "PlaybookLibrary",
    "TaskDomain",
    "TaskRouter",
    "TaskTemplate",
    "get_default_library",
]
