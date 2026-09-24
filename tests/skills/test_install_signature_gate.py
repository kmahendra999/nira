"""Signature verification at install time, not only at load time.

``nira skill install`` used to write a skill to disk without looking at its
signature: verification happened only when the skill was later loaded. An
unverifiable skill therefore installed cleanly and then failed to load, with
nothing connecting the failure to the install that produced it.

The gate is opt-in in exactly the way the loader's is -- it does nothing until
the user sets ``security.signing_key_path`` -- and it distinguishes a missing
signature from a bad one, because those are different facts about a skill.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nira.skills.importer import SkillImporter
from nira.skills.parser import SkillParser
from nira.skills.sources.base import ResolvedSkill
from nira.skills.tool_translator import ToolTranslator

signing = pytest.importorskip(
    "nira.security.signing", reason="requires the cryptography extra"
)


@pytest.fixture
def keys():
    try:
        return signing.generate_keypair()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cryptography unavailable: {exc}")


def _write(src_dir: Path, *, signature: str = "") -> None:
    frontmatter = "name: my-skill\ndescription: A test skill\n"
    if signature:
        frontmatter += f"signature: {signature}\n"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "SKILL.md").write_text(f"---\n{frontmatter}---\nBody")


def _resolved(tmp_path: Path, *, signature: str = "") -> ResolvedSkill:
    src_dir = tmp_path / "source" / "my-skill"
    _write(src_dir, signature=signature)
    return ResolvedSkill(
        name="my-skill",
        source="hermes",
        path=src_dir,
        category="testing",
        description="A test skill",
        commit="abc123",
    )


def _importer(tmp_path: Path) -> SkillImporter:
    return SkillImporter(
        parser=SkillParser(),
        tool_translator=ToolTranslator(),
        target_root=tmp_path / "installed",
    )


def _sign_in_place(tmp_path: Path, private_key: bytes) -> ResolvedSkill:
    """Sign what the parser will actually read back.

    ``manifest_bytes()`` excludes the signature, so writing it into the
    frontmatter afterwards does not invalidate it.
    """
    resolved = _resolved(tmp_path)
    frontmatter, body = _importer(tmp_path)._read_skill_md(resolved.path / "SKILL.md")
    manifest = SkillParser().parse_frontmatter(frontmatter, markdown_content=body)
    signature = signing.sign_b64(manifest.manifest_bytes(), private_key)
    _write(resolved.path, signature=signature)
    return resolved


class TestNoKeyConfigured:
    def test_unsigned_installs_when_the_user_never_opted_in(self, tmp_path):
        result = _importer(tmp_path).import_skill(_resolved(tmp_path))
        assert result.success is True


class TestKeyConfigured:
    def test_unsigned_is_refused(self, tmp_path, keys):
        result = _importer(tmp_path).import_skill(
            _resolved(tmp_path), public_key=keys.public_key
        )
        assert result.success is False
        assert "not signed" in " ".join(result.warnings)
        # Refused before anything was written, not cleaned up afterwards.
        assert not (tmp_path / "installed").exists()

    def test_allow_unsigned_installs_with_a_warning(self, tmp_path, keys):
        result = _importer(tmp_path).import_skill(
            _resolved(tmp_path), public_key=keys.public_key, allow_unsigned=True
        )
        assert result.success is True
        assert any("will not load until it is signed" in w for w in result.warnings)

    def test_a_valid_signature_installs(self, tmp_path, keys):
        resolved = _sign_in_place(tmp_path, keys.private_key)
        result = _importer(tmp_path).import_skill(resolved, public_key=keys.public_key)
        assert result.success is True, result.warnings

    def test_a_signature_from_another_key_is_refused(self, tmp_path, keys):
        other = signing.generate_keypair()
        resolved = _sign_in_place(tmp_path, other.private_key)
        result = _importer(tmp_path).import_skill(resolved, public_key=keys.public_key)
        assert result.success is False
        assert "does not verify" in " ".join(result.warnings)

    def test_allow_unsigned_does_not_excuse_a_bad_signature(self, tmp_path, keys):
        """A wrong signature is not a missing one.

        Something signed that manifest and the configured key does not match
        it, which is the case the flag must not wave through.
        """
        other = signing.generate_keypair()
        resolved = _sign_in_place(tmp_path, other.private_key)
        result = _importer(tmp_path).import_skill(
            resolved, public_key=keys.public_key, allow_unsigned=True
        )
        assert result.success is False
        assert not (tmp_path / "installed").exists()
