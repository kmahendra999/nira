"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from nira.evals.backends.external.hermes_agent import HermesBackend
from nira.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]
