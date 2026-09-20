"""``nira project`` — registering the codebases Nira can work on."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nira.cli.project_cmd import project


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Keep the registry out of the developer's real ~/.nira."""
    monkeypatch.setattr(
        "nira.cli.project_cmd.get_config_dir", lambda: tmp_path / "home"
    )


@pytest.fixture
def workdir(tmp_path):
    path = tmp_path / "myapp"
    path.mkdir()
    return path


def _run(*args):
    return CliRunner().invoke(project, list(args))


class TestAdd:
    def test_registers_a_directory(self, workdir) -> None:
        result = _run("add", "My App", str(workdir))

        assert result.exit_code == 0
        assert "my-app" in result.output

    def test_rejects_a_path_that_is_not_a_directory(self, tmp_path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x", encoding="utf-8")

        result = _run("add", "Thing", str(target))

        assert result.exit_code != 0

    def test_reports_an_unusable_name_without_a_traceback(self, workdir) -> None:
        result = _run("add", "!!!", str(workdir))

        assert result.exit_code == 1
        assert "no usable characters" in result.output


class TestList:
    def test_empty_registry_says_so(self) -> None:
        result = _run("list")

        assert result.exit_code == 0
        assert "No projects registered" in result.output

    def test_shows_registered_projects(self, workdir) -> None:
        _run("add", "My App", str(workdir))

        result = _run("list")

        assert "my-app" in result.output

    def test_flags_a_directory_that_has_gone(self, workdir) -> None:
        """Otherwise the failure only surfaces inside an agent run."""
        _run("add", "My App", str(workdir))
        workdir.rmdir()

        result = _run("list")

        assert "missing" in result.output


class TestShow:
    def test_resolves_a_partial_name(self, workdir) -> None:
        _run("add", "Payments API", str(workdir))

        result = _run("show", "payments")

        assert result.exit_code == 0
        assert "Payments API" in result.output

    def test_unresolvable_reference_exits_nonzero(self) -> None:
        result = _run("show", "nothing")

        assert result.exit_code == 1
        assert "Could not resolve" in result.output


class TestRemove:
    def test_removes_a_project(self, workdir) -> None:
        _run("add", "My App", str(workdir))

        result = _run("remove", "my-app")

        assert result.exit_code == 0
        assert "No projects registered" in _run("list").output

    def test_removing_an_unknown_project_exits_nonzero(self) -> None:
        result = _run("remove", "never-existed")

        assert result.exit_code == 1
