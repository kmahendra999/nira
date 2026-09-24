"""Producing the signatures the loader checks.

Phase 13 made verification reachable and left no way to make a signature for
it to check, so the feature was usable only by someone who already had signing
tooling of their own.

The manifest is edited surgically rather than re-serialised: a ``skill.toml``
is hand-written, with comments and ordering its author chose, and a round-trip
through a TOML writer would discard all of it to change one line.
"""

from __future__ import annotations

import pytest

from nira.skills.signing import (
    apply_signature,
    manifest_path_for,
    manifest_paths_under,
    sign_manifest_file,
)

MANIFEST = """# A skill someone wrote by hand.
[skill]
name = "greet"
version = "0.1.0"
description = "Say hello"   # why it exists

[[skill.steps]]
tool_name = "think"
arguments_template = '{"thought": "hello"}'
"""


class TestApplyingASignature:
    def test_the_signature_lands_inside_the_skill_table(self) -> None:
        updated = apply_signature(MANIFEST, "SIG")

        head = updated.split("[[skill.steps]]")[0]
        assert 'signature = "SIG"' in head

    def test_comments_and_formatting_survive(self) -> None:
        updated = apply_signature(MANIFEST, "SIG")

        # The whole reason for editing in place rather than re-serialising.
        assert "# A skill someone wrote by hand." in updated
        assert "# why it exists" in updated
        assert 'arguments_template = \'{"thought": "hello"}\'' in updated

    def test_resigning_replaces_rather_than_appends(self) -> None:
        once = apply_signature(MANIFEST, "FIRST")
        twice = apply_signature(once, "SECOND")

        # Two signatures in one table means the loader checks whichever TOML
        # happens to win, which is not a decision anyone made.
        assert twice.count("signature =") == 1
        assert "SECOND" in twice
        assert "FIRST" not in twice

    def test_a_manifest_with_no_steps_still_works(self) -> None:
        minimal = '[skill]\nname = "x"\nversion = "1"\ndescription = "d"\n'

        updated = apply_signature(minimal, "SIG")

        assert 'signature = "SIG"' in updated

    def test_a_file_without_a_skill_table_is_refused(self) -> None:
        # Writing a signature into some other TOML would produce a file that
        # looks signed and is not.
        with pytest.raises(ValueError, match="skill manifest"):
            apply_signature('[other]\nname = "x"\n', "SIG")

    def test_it_does_not_write_into_a_following_table(self) -> None:
        updated = apply_signature(MANIFEST, "SIG")

        tail = updated.split("[[skill.steps]]")[1]
        # A signature outside [skill] is not read, so it would silently do
        # nothing while looking like it had worked.
        assert "signature" not in tail


class TestFindingTheManifest:
    def test_a_directory_resolves_to_its_skill_toml(self, tmp_path) -> None:
        (tmp_path / "skill.toml").write_text(MANIFEST, encoding="utf-8")

        assert manifest_path_for(tmp_path) == tmp_path / "skill.toml"

    def test_a_toml_file_resolves_to_itself(self, tmp_path) -> None:
        path = tmp_path / "skill.toml"
        path.write_text(MANIFEST, encoding="utf-8")

        assert manifest_path_for(path) == path

    def test_a_markdown_only_skill_has_nowhere_to_put_a_signature(
        self, tmp_path
    ) -> None:
        (tmp_path / "SKILL.md").write_text("# greet\n", encoding="utf-8")

        # Silently signing a TOML beside it would sign something the user did
        # not point at.
        assert manifest_path_for(tmp_path) is None

    def test_an_empty_directory_resolves_to_nothing(self, tmp_path) -> None:
        assert manifest_path_for(tmp_path) is None


class TestSigningAFile:
    @pytest.fixture
    def keys(self):
        signing = pytest.importorskip("nira.security.signing")
        try:
            return signing.generate_keypair()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"cryptography unavailable: {exc}")

    def test_a_signed_manifest_verifies(self, tmp_path, keys) -> None:
        from nira.skills.loader import load_skill_directory

        path = tmp_path / "skill.toml"
        path.write_text(MANIFEST, encoding="utf-8")

        sign_manifest_file(path, keys.private_key)

        manifest = load_skill_directory(
            tmp_path, verify_signature=True, public_key=keys.public_key
        )
        assert manifest.name == "greet"

    def test_signing_is_idempotent(self, tmp_path, keys) -> None:
        path = tmp_path / "skill.toml"
        path.write_text(MANIFEST, encoding="utf-8")

        first = sign_manifest_file(path, keys.private_key)
        second = sign_manifest_file(path, keys.private_key)

        # The signature covers the manifest *without* it, so re-signing an
        # unchanged file must not sign the previous signature.
        assert first == second

    def test_editing_a_skill_invalidates_its_signature(self, tmp_path, keys) -> None:
        from nira.skills.loader import load_skill_directory

        path = tmp_path / "skill.toml"
        path.write_text(MANIFEST, encoding="utf-8")
        sign_manifest_file(path, keys.private_key)

        path.write_text(
            path.read_text(encoding="utf-8").replace('"hello"', '"rm -rf /"'),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid signature"):
            load_skill_directory(
                tmp_path, verify_signature=True, public_key=keys.public_key
            )

    def test_resigning_an_edited_skill_makes_it_valid_again(
        self, tmp_path, keys
    ) -> None:
        from nira.skills.loader import load_skill_directory

        path = tmp_path / "skill.toml"
        path.write_text(MANIFEST, encoding="utf-8")
        sign_manifest_file(path, keys.private_key)
        path.write_text(
            path.read_text(encoding="utf-8").replace('"hello"', '"goodbye"'),
            encoding="utf-8",
        )

        sign_manifest_file(path, keys.private_key)

        assert (
            load_skill_directory(
                tmp_path, verify_signature=True, public_key=keys.public_key
            ).name
            == "greet"
        )


class TestTheCommands:
    """`nira skill keygen` and `nira skill sign`.

    Without them, verification was only usable by someone who already had
    signing tooling of their own.
    """

    @pytest.fixture
    def run(self, tmp_path, monkeypatch):
        pytest.importorskip("nira.security.signing")
        from click.testing import CliRunner

        from nira.cli import skill_cmd

        monkeypatch.setattr(skill_cmd, "get_config_dir", lambda: tmp_path)
        runner = CliRunner()
        return lambda *args: runner.invoke(skill_cmd.skill, list(args))

    def test_keygen_writes_both_halves(self, run, tmp_path) -> None:
        result = run("keygen")

        assert result.exit_code == 0
        assert (tmp_path / "skill-signing.key").exists()
        assert (tmp_path / "skill-signing.pub").exists()

    def test_the_private_key_is_not_world_readable(self, run, tmp_path) -> None:
        run("keygen")

        mode = (tmp_path / "skill-signing.key").stat().st_mode & 0o777
        # It signs skills an agent will execute. Default file permissions on a
        # shared machine would leave it readable by every other account.
        assert mode == 0o600

    def test_the_private_key_is_never_printed(self, run, tmp_path) -> None:
        result = run("keygen")

        private = (tmp_path / "skill-signing.key").read_bytes()
        assert private.hex() not in result.output
        assert private.hex()[:16] not in result.output

    def test_keygen_refuses_to_overwrite_silently(self, run, tmp_path) -> None:
        run("keygen")
        first = (tmp_path / "skill-signing.key").read_bytes()

        result = run("keygen")

        # Overwriting is unrecoverable: every skill signed with the old key
        # stops verifying and there is no way back.
        assert result.exit_code != 0
        assert (tmp_path / "skill-signing.key").read_bytes() == first

    def test_force_replaces_the_keys(self, run, tmp_path) -> None:
        run("keygen")
        first = (tmp_path / "skill-signing.key").read_bytes()

        assert run("keygen", "--force").exit_code == 0
        assert (tmp_path / "skill-signing.key").read_bytes() != first

    def test_keygen_prints_a_usable_config_snippet(self, run, tmp_path) -> None:
        result = run("keygen")

        # Rich reads "[security]" as markup and drops it unless escaped,
        # leaving a snippet with no table header for the user to copy.
        assert "[security]" in result.output
        assert "signing_key_path" in result.output

    def test_sign_signs_a_skill_directory(self, run, tmp_path) -> None:
        run("keygen")
        skill_dir = tmp_path / "greet"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(MANIFEST, encoding="utf-8")

        result = run("sign", str(skill_dir))

        assert result.exit_code == 0
        assert "signature =" in (skill_dir / "skill.toml").read_text(encoding="utf-8")

    def test_sign_without_a_key_says_how_to_make_one(self, run, tmp_path) -> None:
        skill_dir = tmp_path / "greet"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(MANIFEST, encoding="utf-8")

        result = run("sign", str(skill_dir))

        assert result.exit_code != 0
        assert "keygen" in result.output

    def test_sign_on_something_that_is_not_a_skill_explains_itself(
        self, run, tmp_path
    ) -> None:
        run("keygen")
        empty = tmp_path / "not-a-skill"
        empty.mkdir()

        result = run("sign", str(empty))

        assert result.exit_code != 0
        assert "skill.toml" in result.output


class TestFindingEveryManifest:
    """`manifest_paths_under` -- what `nira skill sign --all` walks."""

    def test_finds_manifests_at_any_depth(self, tmp_path) -> None:
        for relative in ("a/skill.toml", "b/nested/skill.toml", "skill.toml"):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(MANIFEST, encoding="utf-8")

        found = manifest_paths_under(tmp_path)

        assert len(found) == 3
        # Stable order, so output and exit status do not depend on the
        # filesystem's iteration order.
        assert found == sorted(found)

    def test_ignores_markdown_only_skills(self, tmp_path) -> None:
        (tmp_path / "md-only").mkdir()
        (tmp_path / "md-only" / "SKILL.md").write_text("# x\n", encoding="utf-8")

        assert manifest_paths_under(tmp_path) == []

    def test_a_file_argument_comes_back_as_itself(self, tmp_path) -> None:
        path = tmp_path / "skill.toml"
        path.write_text(MANIFEST, encoding="utf-8")

        assert manifest_paths_under(path) == [path]

    def test_a_missing_path_is_empty_not_an_error(self, tmp_path) -> None:
        assert manifest_paths_under(tmp_path / "absent") == []


class TestSigningATree:
    """`nira skill sign --all`.

    Signing one skill at a time means the manifest that gets forgotten is the
    one that stops loading -- and it stops at the moment someone else uses it.
    """

    @pytest.fixture
    def run(self, tmp_path, monkeypatch):
        pytest.importorskip("nira.security.signing")
        from click.testing import CliRunner

        from nira.cli import skill_cmd

        monkeypatch.setattr(skill_cmd, "get_config_dir", lambda: tmp_path)
        runner = CliRunner()
        return lambda *args: runner.invoke(skill_cmd.skill, list(args))

    @pytest.fixture
    def tree(self, tmp_path):
        root = tmp_path / "skills"
        for name in ("alpha", "beta", "gamma"):
            directory = root / name
            directory.mkdir(parents=True)
            (directory / "skill.toml").write_text(
                MANIFEST.replace('name = "greet"', f'name = "{name}"'),
                encoding="utf-8",
            )
        return root

    def test_signs_every_manifest_in_the_tree(self, run, tree) -> None:
        run("keygen")

        result = run("sign", str(tree), "--all")

        assert result.exit_code == 0, result.output
        for name in ("alpha", "beta", "gamma"):
            text = (tree / name / "skill.toml").read_text(encoding="utf-8")
            assert "signature = " in text

    def test_the_signatures_actually_verify(self, run, tree, tmp_path) -> None:
        from nira.security.signing import verify_b64
        from nira.skills.loader import load_skill

        run("keygen")
        run("sign", str(tree), "--all")

        public_key = (tmp_path / "skill-signing.pub").read_bytes()
        for name in ("alpha", "beta", "gamma"):
            manifest = load_skill(tree / name / "skill.toml")
            assert verify_b64(manifest.manifest_bytes(), manifest.signature, public_key)

    def test_one_bad_manifest_does_not_abandon_the_rest(self, run, tree) -> None:
        run("keygen")
        broken = tree / "delta"
        broken.mkdir()
        (broken / "skill.toml").write_text("not a skill manifest\n", encoding="utf-8")

        result = run("sign", str(tree), "--all")

        # Non-zero, because something the user asked for did not happen...
        assert result.exit_code != 0
        # ...but the three that could be signed were, rather than leaving the
        # tree in whichever half-signed state the walk happened to reach.
        for name in ("alpha", "beta", "gamma"):
            text = (tree / name / "skill.toml").read_text(encoding="utf-8")
            assert "signature = " in text

    def test_a_tree_with_no_manifests_is_an_error(self, run, tmp_path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        run("keygen")

        result = run("sign", str(empty), "--all")

        assert result.exit_code != 0
        assert "No skill.toml" in result.output
