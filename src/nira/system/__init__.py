"""Top-level system composition: NiraSystem, SystemBuilder, and helpers."""

from nira.system.builder import SystemBuilder
from nira.system.bundles import (
    AgentRuntime,
    Observability,
    Scheduling,
    SecurityContext,
)
from nira.system.core import NiraSystem
from nira.system.orchestrator import QueryOrchestrator
from nira.system.protocols import OrchestratorDeps

__all__ = [
    "AgentRuntime",
    "NiraSystem",
    "Observability",
    "OrchestratorDeps",
    "QueryOrchestrator",
    "Scheduling",
    "SecurityContext",
    "SystemBuilder",
]
