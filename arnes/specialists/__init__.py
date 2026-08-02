"""ARNES specialists — pre-built role-based agents."""

from arnes.specialists.base import Specialist, SpecialistConfig, SpecialistRegistry
from arnes.specialists.coder import Coder
from arnes.specialists.cost_estimator import CostEstimator
from arnes.specialists.data_scientist import DataScientist
from arnes.specialists.debugger import Debugger
from arnes.specialists.devops_engineer import DevOpsEngineer
from arnes.specialists.market_analyst import MarketAnalyst
from arnes.specialists.planner import Planner
from arnes.specialists.product_manager import ProductManager
from arnes.specialists.researcher import Researcher
from arnes.specialists.reviewer import Reviewer
from arnes.specialists.security_auditor import SecurityAuditor
from arnes.specialists.tester import Tester

__all__ = [
    "Coder",
    "CostEstimator",
    "DataScientist",
    "Debugger",
    "DevOpsEngineer",
    "MarketAnalyst",
    "Planner",
    "ProductManager",
    "Researcher",
    "Reviewer",
    "SecurityAuditor",
    "Specialist",
    "SpecialistConfig",
    "SpecialistRegistry",
    "Tester",
]
