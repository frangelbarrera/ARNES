"""
ARNES — The Open Agent Harness.

Escribe el manual. ARNES lo compila en un equipo de especialistas que lo sigue
al pie de la letra.
"""

from arnes.agent import Harness, HarnessConfig
from arnes.llm import LLMMessage, LLMProvider
from arnes.middleware import (
    CostBudget,
    CostGuard,
    TokenOptimizer,
    VerificationConfig,
    VerificationLayer,
)
from arnes.playbooks import Playbook, PlaybookCompiler
from arnes.specialists import (
    Coder,
    Debugger,
    Planner,
    Reviewer,
    Specialist,
    SpecialistRegistry,
    Tester,
)
from arnes.thread import Event, Thread
from arnes.tools import Tool, ToolRegistry, ToolResult

__version__ = "0.1.0a1"
__all__ = [
    "Coder",
    "CostBudget",
    "CostGuard",
    "Debugger",
    "Event",
    "Harness",
    "HarnessConfig",
    "LLMMessage",
    "LLMProvider",
    "Planner",
    "Playbook",
    "PlaybookCompiler",
    "Reviewer",
    "Specialist",
    "SpecialistRegistry",
    "Tester",
    "Thread",
    "TokenOptimizer",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "VerificationConfig",
    "VerificationLayer",
]
