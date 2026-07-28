"""
ARNES — The Open Agent Harness.

Escribe el manual. ARNES lo compila en un equipo de especialistas que lo sigue
al pie de la letra.
"""

from arnes.thread import Thread, Event
from arnes.agent import Harness, HarnessConfig
from arnes.tools import Tool, ToolResult, ToolRegistry
from arnes.llm import LLMProvider, LLMMessage
from arnes.specialists import (
    Specialist,
    SpecialistRegistry,
    Planner,
    Coder,
    Reviewer,
    Tester,
    Debugger,
)
from arnes.playbooks import Playbook, PlaybookCompiler
from arnes.middleware import (
    TokenOptimizer,
    VerificationLayer,
    VerificationConfig,
    CostGuard,
    CostBudget,
)

__version__ = "0.1.0a1"
__all__ = [
    "Thread",
    "Event",
    "Harness",
    "HarnessConfig",
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "LLMProvider",
    "LLMMessage",
    "Specialist",
    "SpecialistRegistry",
    "Planner",
    "Coder",
    "Reviewer",
    "Tester",
    "Debugger",
    "Playbook",
    "PlaybookCompiler",
    "TokenOptimizer",
    "VerificationLayer",
    "VerificationConfig",
    "CostGuard",
    "CostBudget",
]
