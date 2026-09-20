"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from nira.skills.sources.base import ResolvedSkill, SourceResolver
from nira.skills.sources.github import GitHubResolver
from nira.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from nira.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
