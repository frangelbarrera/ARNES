"""
ARNES — The Open Agent Harness.

Write the manual. ARNES compiles it into a team of specialists that follows it
to the letter.
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
from arnes.proactive import ProactivePlan, ProactivePlanner
from arnes.specialists import (
    Coder,
    CostEstimator,
    DataScientist,
    Debugger,
    DevOpsEngineer,
    MarketAnalyst,
    Planner,
    ProductManager,
    Researcher,
    Reviewer,
    SecurityAuditor,
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
    "CostEstimator",
    "CostGuard",
    "DataScientist",
    "Debugger",
    "DevOpsEngineer",
    "Event",
    "Harness",
    "HarnessConfig",
    "LLMMessage",
    "LLMProvider",
    "MarketAnalyst",
    "Planner",
    "Playbook",
    "PlaybookCompiler",
    "ProactivePlan",
    "ProactivePlanner",
    "ProductManager",
    "Researcher",
    "Reviewer",
    "SecurityAuditor",
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
