"""Reading a stored report back, which is the other half of the link.

``nira://research/<id>`` is registered with the OS and parsed by the desktop
app. Without somewhere to read the report from, clicking it could only open
the app and apologise — which is what it did.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="nira[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nira.research import ResearchStore
from nira.server.research_router import router


@pytest.fixture
def store(tmp_path):
    research = ResearchStore(tmp_path / "research.db")
    yield research
    research.close()


@pytest.fixture
def client(store):
    app = FastAPI()
    app.state.research_store = store
    app.include_router(router)
    return TestClient(app)


class TestFetchingOne:
    def test_a_stored_report_comes_back_whole(self, client, store) -> None:
        store.save("what is x", "The full answer, at length.", report_id="sess_1")

        body = client.get("/api/research/sess_1").json()

        assert body["report"] == "The full answer, at length."
        assert body["query"] == "what is x"

    def test_an_unknown_id_is_a_404_that_explains_itself(self, client) -> None:
        response = client.get("/api/research/never-existed")

        assert response.status_code == 404
        # "Not found" alone reads as a broken link. The real reason is that
        # reports are pruned, and saying so tells the user it is not their
        # mistake.
        assert "kept" in response.json()["detail"].lower()

    def test_the_id_is_taken_literally(self, client, store) -> None:
        store.save("q", "r", report_id="sess_1")

        assert client.get("/api/research/sess_2").status_code == 404


class TestListing:
    def test_recent_reports_are_listed_newest_first(self, client, store) -> None:
        for index in range(3):
            store.save(f"q{index}", "r", report_id=f"a{index}")

        listed = client.get("/api/research").json()

        assert [r["id"] for r in listed["reports"]] == ["a2", "a1", "a0"]
        assert listed["count"] == 3

    def test_a_listing_carries_previews_not_bodies(self, client, store) -> None:
        store.save("q", "x" * 5000, report_id="a")

        listed = client.get("/api/research").json()["reports"][0]

        # Twenty reports at five thousand characters each is a hundred
        # thousand characters to render twenty one-line rows.
        assert listed["report"] == ""
        assert listed["preview"]

    def test_the_limit_is_honoured(self, client, store) -> None:
        for index in range(5):
            store.save("q", "r", report_id=f"a{index}")

        assert len(client.get("/api/research?limit=2").json()["reports"]) == 2

    def test_a_nonsense_limit_falls_back_rather_than_failing(
        self, client, store
    ) -> None:
        store.save("q", "r", report_id="a")

        # A malformed query string is not a reason to refuse to answer.
        assert client.get("/api/research?limit=banana").status_code == 200

    def test_an_absurd_limit_is_capped(self, client, store) -> None:
        store.save("q", "r", report_id="a")

        assert client.get("/api/research?limit=100000").status_code == 200

    def test_an_empty_store_lists_nothing(self, client) -> None:
        body = client.get("/api/research").json()

        assert body["reports"] == []
        assert body["count"] == 0
