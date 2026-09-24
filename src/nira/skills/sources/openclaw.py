"""OpenClawResolver — resolves skills from the OpenClaw skill catalogue.

Two layouts are accepted, because the catalogue uses the first and a registry
that groups submissions by their author uses the second:

    skills/<skill-name>/SKILL.md
    skills/<owner>/<skill-name>/SKILL.md

A directory directly under ``skills/`` that holds a ``SKILL.md`` is a skill; one
that does not is an owner, and its children are skills.  ``_meta.json`` beside a
``SKILL.md`` is optional sidecar registry data.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import List

import yaml

from nira.core.paths import get_config_dir
from nira.skills.sources.base import ResolvedSkill, SourceResolver

LOGGER = logging.getLogger(__name__)

OPENCLAW_REPO_URL = "https://github.com/openclaw/agent-skills.git"


class OpenClawResolver(SourceResolver):
    """Resolves skills from the OpenClaw skill catalogue."""

    name = "openclaw"

    def __init__(self, cache_root: Path | None = None) -> None:
        if cache_root is None:
            cache_root = get_config_dir() / "skill-cache" / "openclaw"
        self._cache_root = Path(cache_root)

    def cache_dir(self) -> Path:
        return self._cache_root

    def sync(self) -> None:
        self._sync_git_cache(OPENCLAW_REPO_URL)

    def list_skills(self) -> List[ResolvedSkill]:
        skills_root = self._cache_root / "skills"
        if not skills_root.exists():
            return []

        results: List[ResolvedSkill] = []
        commit = self._read_commit()

        for entry in sorted(skills_root.iterdir()):
            if not entry.is_dir():
                continue

            if (entry / "SKILL.md").exists():
                results.append(self._resolve(entry, category="", commit=commit))
                continue

            for skill_dir in sorted(entry.iterdir()):
                if not skill_dir.is_dir():
                    continue
                if not (skill_dir / "SKILL.md").exists():
                    continue
                results.append(
                    self._resolve(skill_dir, category=entry.name, commit=commit)
                )

        return results

    def _resolve(self, skill_dir: Path, category: str, commit: str) -> ResolvedSkill:
        name, description = self._read_preview(
            skill_dir / "SKILL.md", default_name=skill_dir.name
        )
        return ResolvedSkill(
            name=name,
            source=self.name,
            path=skill_dir,
            category=category,
            description=description,
            commit=commit,
            sidecar_data=self._read_sidecar(skill_dir / "_meta.json"),
        )

    def _read_preview(self, skill_md: Path, default_name: str) -> tuple[str, str]:
        try:
            raw = skill_md.read_text(encoding="utf-8")
        except Exception:
            return default_name, ""
        if not raw.startswith("---"):
            return default_name, ""
        rest = raw[3:].lstrip("\n")
        end = rest.find("\n---")
        if end == -1:
            return default_name, ""
        try:
            fm = yaml.safe_load(rest[:end])
        except yaml.YAMLError:
            return default_name, ""
        if not isinstance(fm, dict):
            return default_name, ""
        return str(fm.get("name", default_name)), str(fm.get("description", ""))

    def _read_sidecar(self, sidecar_path: Path) -> dict:
        if not sidecar_path.exists():
            return {}
        try:
            return json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _read_commit(self) -> str:
        if not (self._cache_root / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(self._cache_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""


__all__ = ["OpenClawResolver", "OPENCLAW_REPO_URL"]
