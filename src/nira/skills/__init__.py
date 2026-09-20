"""Skill system — reusable multi-tool compositions."""

from nira.skills.dependency import (
    DependencyCycleError,
    DepthExceededError,
    build_dependency_graph,
    compute_capability_union,
    validate_dependencies,
)
from nira.skills.executor import SkillExecutor, SkillResult
from nira.skills.importer import ImportResult, SkillImporter
from nira.skills.loader import (
    discover_skills,
    load_skill,
    load_skill_directory,
    load_skill_markdown,
)
from nira.skills.manager import SkillManager
from nira.skills.parser import SkillParseError, SkillParser
from nira.skills.tool_adapter import SkillTool
from nira.skills.tool_translator import TOOL_TRANSLATION, ToolTranslator
from nira.skills.types import SkillManifest, SkillStep

__all__ = [
    "DependencyCycleError",
    "DepthExceededError",
    "ImportResult",
    "SkillExecutor",
    "SkillImporter",
    "SkillManager",
    "SkillManifest",
    "SkillParseError",
    "SkillParser",
    "SkillResult",
    "SkillStep",
    "SkillTool",
    "TOOL_TRANSLATION",
    "ToolTranslator",
    "build_dependency_graph",
    "compute_capability_union",
    "discover_skills",
    "load_skill",
    "load_skill_directory",
    "load_skill_markdown",
    "validate_dependencies",
]
