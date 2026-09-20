"""Structural protocols for substituting fakes in place of NiraSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from nira.core.config import NiraConfig
    from nira.core.events import EventBus
    from nira.engine._stubs import InferenceEngine
    from nira.security.capabilities import CapabilityPolicy
    from nira.sessions.session import SessionStore
    from nira.tools._stubs import BaseTool
    from nira.tools.storage._stubs import MemoryBackend
    from nira.traces.collector import TraceCollector
    from nira.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of NiraSystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full NiraSystem dataclass or materialize every subsystem.
    """

    config: NiraConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    rate_limiter: Optional[Any]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]  # written by _run_agent

    # Optional attribute (getattr with default) — declared for type clarity.
    _skill_few_shot_examples: Any
