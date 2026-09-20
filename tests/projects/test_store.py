"""The project registry — the durable answer to "work on project X".

There was previously no notion of a project anywhere: ``workspace`` existed
only as a constructor string on individual agents, so a request naming a
project had nothing to resolve against and a coding agent started cold in
whatever directory the server happened to be running in.
"""

from __future__ import annotations

import pytest

from nira.projects import ProjectStore
from nira.projects.store import slugify


@pytest.fixture
def store(tmp_path):
    registry = ProjectStore(tmp_path / "projects.db")
    yield registry
    registry.close()


@pytest.fixture
def workdir(tmp_path):
    path = tmp_path / "myapp"
    path.mkdir()
    return path


class TestSlugify:
    def test_lowercases_and_hyphenates(self) -> None:
        assert slugify("My Cool App") == "my-cool-app"

    def test_collapses_punctuation(self) -> None:
        assert slugify("nira/back-end (v2)") == "nira-back-end-v2"

    def test_trims_leading_and_trailing_separators(self) -> None:
        assert slugify("  --API--  ") == "api"


class TestRegistering:
    def test_add_and_read_back(self, store, workdir) -> None:
        added = store.add("My App", workdir)

        assert added.id == "my-app"
        assert added.path == str(workdir.resolve())
        assert store.get("my-app").name == "My App"

    def test_path_is_resolved(self, store, workdir) -> None:
        """A relative or symlinked path must not create a second identity."""
        added = store.add("My App", workdir / ".." / workdir.name)

        assert added.path == str(workdir.resolve())

    def test_a_missing_directory_is_rejected_at_registration(
        self, store, tmp_path
    ) -> None:
        """Better to fail here than inside an agent run, where the cause is
        much harder to see."""
        with pytest.raises(ValueError, match="Not a directory"):
            store.add("Ghost", tmp_path / "does-not-exist")

    def test_a_file_is_not_a_project(self, store, tmp_path) -> None:
        target = tmp_path / "readme.md"
        target.write_text("x", encoding="utf-8")

        with pytest.raises(ValueError, match="Not a directory"):
            store.add("Readme", target)

    def test_a_nameless_project_is_rejected(self, store, workdir) -> None:
        with pytest.raises(ValueError, match="no usable characters"):
            store.add("!!!", workdir)

    def test_one_project_per_directory(self, store, workdir) -> None:
        """Two names for one codebase would give it two session histories,
        and whichever the user happened to say would forget the other."""
        store.add("Old Name", workdir)
        store.add("New Name", workdir)

        assert [p.name for p in store.list()] == ["New Name"]

    def test_re_adding_preserves_the_session(self, store, workdir) -> None:
        store.add("My App", workdir)
        store.remember_session("my-app", "sess-1")

        store.add("My App", workdir, default_agent="native_react")

        again = store.get("my-app")
        assert again.last_session_id == "sess-1"
        assert again.default_agent == "native_react"


class TestResolution:
    def test_resolves_by_id(self, store, workdir) -> None:
        store.add("My App", workdir)

        assert store.resolve("my-app").id == "my-app"

    def test_resolves_by_name(self, store, workdir) -> None:
        store.add("My App", workdir)

        assert store.resolve("My App").id == "my-app"

    def test_resolves_a_partial_name(self, store, workdir) -> None:
        """Spoken requests name projects loosely ("work on the api one")."""
        store.add("Payments API", workdir)

        assert store.resolve("payments").id == "payments-api"

    def test_an_ambiguous_partial_resolves_to_nothing(self, store, tmp_path) -> None:
        """Picking the wrong codebase is much worse than asking again."""
        for name in ("API Gateway", "API Client"):
            path = tmp_path / slugify(name)
            path.mkdir()
            store.add(name, path)

        assert store.resolve("api") is None

    def test_unknown_reference_resolves_to_nothing(self, store) -> None:
        assert store.resolve("nothing here") is None

    def test_empty_reference_resolves_to_nothing(self, store) -> None:
        assert store.resolve("   ") is None


class TestSessionMemory:
    def test_remembering_a_session_lets_the_next_run_continue(
        self, store, workdir
    ) -> None:
        store.add("My App", workdir)

        store.remember_session("my-app", "sdk-session-7")

        assert store.get("my-app").last_session_id == "sdk-session-7"

    def test_a_new_project_has_no_session(self, store, workdir) -> None:
        assert store.add("My App", workdir).last_session_id == ""


class TestLifecycle:
    def test_remove(self, store, workdir) -> None:
        store.add("My App", workdir)

        assert store.remove("my-app") is True
        assert store.get("my-app") is None

    def test_removing_an_unknown_project_reports_false(self, store) -> None:
        assert store.remove("never-existed") is False

    def test_list_is_most_recently_touched_first(self, store, tmp_path) -> None:
        for name in ("First", "Second"):
            path = tmp_path / name.lower()
            path.mkdir()
            store.add(name, path)
        store.remember_session("first", "s1")

        assert store.list()[0].name == "First"

    def test_exists_reports_a_directory_that_has_gone(self, store, workdir) -> None:
        """A path can move or be deleted after registration."""
        added = store.add("My App", workdir)
        assert added.exists is True

        workdir.rmdir()
        assert store.get("my-app").exists is False


class TestPersistence:
    def test_survives_a_reopen(self, tmp_path, workdir) -> None:
        db = tmp_path / "projects.db"
        first = ProjectStore(db)
        first.add("My App", workdir)
        first.remember_session("my-app", "sess-9")
        first.close()

        second = ProjectStore(db)
        try:
            restored = second.get("my-app")
        finally:
            second.close()

        assert restored.path == str(workdir.resolve())
        assert restored.last_session_id == "sess-9"
