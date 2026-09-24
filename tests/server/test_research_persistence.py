"""A deep research run from the web UI is kept, like one from a channel.

`channel_agent` saved its reports and answered with a `nira://research/<id>`
link. The same run started from the web UI streamed to the browser and was
gone when the tab closed -- so that link resolved for half the product and
`ResearchStore` only ever held what a channel had produced.

Storage must not cost the user an answer they already have on screen, so the
save reports failure rather than raising, and the `done` frame carries an id
only when there is really something behind it.
"""

from __future__ import annotations

from typing import Any

from nira.server.research_router import _persist_report


class _Store:
    def __init__(self, explode: bool = False) -> None:
        self.saved: list[dict[str, Any]] = []
        self._explode = explode

    def save(self, query: str, report: str, **kwargs: Any) -> Any:
        if self._explode:
            raise RuntimeError("disk is full")
        self.saved.append({"query": query, "report": report, **kwargs})
        return None


class TestPersistReport:
    def test_it_saves_under_the_id_it_was_given(self) -> None:
        store = _Store()

        assert _persist_report(store, "abc123", "why", "the report", []) is True
        assert store.saved[0]["report_id"] == "abc123"
        assert store.saved[0]["query"] == "why"
        assert store.saved[0]["channel"] == "web"

    def test_sources_ride_along_in_metadata(self) -> None:
        store = _Store()
        sources = [{"title": "t", "url": "https://example.invalid"}]

        _persist_report(store, "abc123", "why", "the report", sources)

        assert store.saved[0]["metadata"] == {"sources": sources}

    def test_no_store_is_not_an_error(self) -> None:
        assert _persist_report(None, "abc123", "why", "the report", []) is False

    def test_an_empty_report_is_not_saved(self) -> None:
        store = _Store()
        assert _persist_report(store, "abc123", "why", "", []) is False
        assert store.saved == []

    def test_a_failing_store_does_not_raise(self) -> None:
        """The answer is already on the reader's screen. Losing it to a
        write error would be the worse failure."""
        assert _persist_report(_Store(explode=True), "id", "q", "r", []) is False


class TestTheEndpointPassesAStore:
    """The wiring, which is the part that was missing.

    `_persist_report` being correct buys nothing if the endpoint never hands
    the generator a store -- which is exactly the state this file fixes.
    """

    def test_research_hands_the_stream_a_store(self, monkeypatch) -> None:
        from types import SimpleNamespace

        from nira.server import research_router

        captured: dict[str, Any] = {}

        async def fake_stream(query: str, **kwargs: Any):  # noqa: ANN202
            captured.update(kwargs)
            captured["query"] = query
            yield "data: {}\n\n"

        sentinel = _Store()
        monkeypatch.setattr(research_router, "_stream_research", fake_stream)
        monkeypatch.setattr(research_router, "_store", lambda request: sentinel)

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        response = research_router.research(
            research_router.ResearchRequest(query="why"), request
        )
        import asyncio

        asyncio.run(_drain(response))

        assert captured["query"] == "why"
        assert captured["store"] is sentinel


async def _drain(coro) -> None:  # noqa: ANN001
    response = await coro
    async for _ in response.body_iterator:
        pass
