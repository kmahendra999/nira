"""External anonymous usage analytics.

Sends anonymized events to PostHog so the Nira team can measure
setup success, retention, feature usage, and churn — without ever
collecting chat content, prompts, file paths, emails, IPs, or hardware
identifiers.

Distinct from :mod:`nira.telemetry`, which stores local FLOPs and
energy metrics in a SQLite DB and never leaves the machine.

Disable: set ``[analytics] enabled = false`` in ``~/.nira/config.toml``.
"""

from nira.analytics.aggregator import SessionAggregator
from nira.analytics.bridge import EventBridge
from nira.analytics.client import AnalyticsClient
from nira.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
    reset_anon_id,
)
from nira.analytics.redaction import hash_id, redact

__all__ = [
    "AnalyticsClient",
    "EventBridge",
    "SessionAggregator",
    "get_or_create_anon_id",
    "is_analytics_enabled",
    "reset_anon_id",
    "redact",
    "hash_id",
]
