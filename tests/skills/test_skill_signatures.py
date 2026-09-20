"""Skill signatures are checked on the path skills are actually loaded from.

``load_skill`` has known how to verify a signature since signing existed. It
could not be asked to: ``load_skill_directory`` and ``discover_skills`` — the
only functions the skill manager calls — took no key, and
``security.signing_key_path`` was read by nothing. So a manifest could carry a
``signature`` and nobody ever looked at it.

Skills arrive from a remote index and define the steps an agent executes.
That is the case signing exists for.
"""

from __future__ import annotations

import pytest

from nira.skills.loader import discover_skills, load_skill, load_skill_directory

signing = pytest.importorskip(
    "nira.security.signing", reason="requires the cryptography extra"
)


@pytest.fixture
def keys():
    try:
        pair = signing.generate_keypair()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cryptography unavailable: {exc}")
    return pair


def write_skill(directory, name: str, *, signature: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    body = f'''[skill]
name = "{name}"
version = "0.1.0"
description = "A test skill"
'''
    if signature:
        body += f'signature = "{signature}"\n'
    # [[skill.steps]] with tool_name — the shape the loader actually parses.
    # A block it ignores leaves `steps: []`, and then a "tampered" skill signs
    # byte-for-byte the same as the original and the test proves nothing.
    body += """
[[skill.steps]]
tool_name = "calculator"
arguments_template = "1 + 1"
"""
    (directory / "skill.toml").write_text(body, encoding="utf-8")


def sign_existing(path, private_key: bytes) -> None:
    """Sign a skill already on disk, and write the signature back into it."""
    manifest = load_skill(path / "skill.toml")
    signature = signing.sign_b64(manifest.manifest_bytes(), private_key)
    text = (path / "skill.toml").read_text(encoding="utf-8")
    lines = text.splitlines()
    # Insert into the [skill] table, where the loader reads it from.
    for index, line in enumerate(lines):
        if line.startswith("description ="):
            lines.insert(index + 1, f'signature = "{signature}"')
            break
    (path / "skill.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestWithoutAKey:
    def test_skills_load_as_before(self, tmp_path) -> None:
        write_skill(tmp_path / "demo", "demo")

        manifest = load_skill_directory(tmp_path / "demo")

        # Nobody opted into signing, so nothing changes for them. Refusing
        # every unsigned skill by default would break working installs to
        # enforce a policy the user never chose.
        assert manifest.name == "demo"

    def test_discovery_loads_unsigned_skills(self, tmp_path) -> None:
        write_skill(tmp_path / "demo", "demo")

        assert [m.name for m in discover_skills(tmp_path)] == ["demo"]


class TestWithAKey:
    def test_a_correctly_signed_skill_loads(self, tmp_path, keys) -> None:
        path = tmp_path / "demo"
        write_skill(path, "demo")
        sign_existing(path, keys.private_key)

        manifest = load_skill_directory(
            path, verify_signature=True, public_key=keys.public_key
        )

        assert manifest.name == "demo"

    def test_a_tampered_skill_is_refused(self, tmp_path, keys) -> None:
        path = tmp_path / "demo"
        write_skill(path, "demo")
        sign_existing(path, keys.private_key)
        # Change what the agent will execute, after signing it.
        text = (path / "skill.toml").read_text(encoding="utf-8")
        (path / "skill.toml").write_text(
            text.replace(
                'arguments_template = "1 + 1"',
                'arguments_template = "9 * 9"',
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid signature"):
            load_skill_directory(
                path, verify_signature=True, public_key=keys.public_key
            )

    def test_a_signature_from_another_key_is_refused(self, tmp_path, keys) -> None:
        other = signing.generate_keypair()
        path = tmp_path / "demo"
        write_skill(path, "demo")
        sign_existing(path, other.private_key)

        with pytest.raises(ValueError, match="Invalid signature"):
            load_skill_directory(
                path, verify_signature=True, public_key=keys.public_key
            )

    def test_an_unsigned_skill_is_refused(self, tmp_path, keys) -> None:
        # The gate used to also require the manifest to *have* a signature,
        # which meant anyone wanting to bypass the check could delete the line
        # being checked. A verification its own subject can switch off is not
        # a verification.
        path = tmp_path / "demo"
        write_skill(path, "demo")

        with pytest.raises(ValueError, match="not signed"):
            load_skill_directory(
                path, verify_signature=True, public_key=keys.public_key
            )

    def test_the_refusal_says_how_to_proceed(self, tmp_path, keys) -> None:
        path = tmp_path / "demo"
        write_skill(path, "demo")

        with pytest.raises(ValueError) as caught:
            load_skill_directory(
                path, verify_signature=True, public_key=keys.public_key
            )

        # Someone who turned on signing and finds their skills gone needs to
        # know both ways out.
        message = str(caught.value)
        assert "Sign it" in message
        assert "signing_key_path" in message


class TestDiscovery:
    def test_discovery_passes_the_key_down(self, tmp_path, keys) -> None:
        write_skill(tmp_path / "unsigned", "unsigned")
        signed = tmp_path / "signed"
        write_skill(signed, "signed")
        sign_existing(signed, keys.private_key)

        found = discover_skills(
            tmp_path, verify_signature=True, public_key=keys.public_key
        )

        # The unsigned one is skipped and logged rather than taking the whole
        # discovery down with it — one bad skill must not cost you the rest.
        assert [m.name for m in found] == ["signed"]

    def test_a_flat_toml_is_verified_too(self, tmp_path, keys) -> None:
        # The three layouts discover_skills handles all have to be covered, or
        # the bypass is "put the skill in the other kind of directory".
        write_skill(tmp_path / "pkg", "pkg")
        (tmp_path / "loose.toml").write_text(
            '[skill]\nname = "loose"\nversion = "0.1.0"\ndescription = "d"\n',
            encoding="utf-8",
        )

        found = discover_skills(
            tmp_path, verify_signature=True, public_key=keys.public_key
        )

        assert found == []

    def test_a_nested_source_layout_is_verified_too(self, tmp_path, keys) -> None:
        write_skill(tmp_path / "some-source" / "nested", "nested")

        found = discover_skills(
            tmp_path, verify_signature=True, public_key=keys.public_key
        )

        assert found == []


class TestConfiguredKey:
    def test_no_key_configured_means_no_verification(self, monkeypatch) -> None:
        from nira.skills import manager

        monkeypatch.setattr(
            manager,
            "load_config",
            lambda: None,
            raising=False,
        )

        assert manager._configured_public_key() is None

    def test_an_unreadable_key_does_not_silently_pass(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        from types import SimpleNamespace

        from nira.skills import manager

        missing = tmp_path / "absent.pub"
        monkeypatch.setattr(
            "nira.core.config.load_config",
            lambda: SimpleNamespace(
                security=SimpleNamespace(signing_key_path=str(missing))
            ),
        )

        with caplog.at_level("ERROR"):
            assert manager._configured_public_key() is None

        # The user asked for verification and is not getting it. Saying so
        # loudly is the least this can do.
        assert any("will NOT be verified" in r.message for r in caplog.records)

    def test_a_readable_key_is_used(self, tmp_path, monkeypatch, keys) -> None:
        from types import SimpleNamespace

        from nira.skills import manager

        key_file = tmp_path / "skills.pub"
        key_file.write_bytes(keys.public_key)
        monkeypatch.setattr(
            "nira.core.config.load_config",
            lambda: SimpleNamespace(
                security=SimpleNamespace(signing_key_path=str(key_file))
            ),
        )

        assert manager._configured_public_key() == keys.public_key
