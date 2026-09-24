"""Two hundred reports is a scroll, not a corpus.

`ResearchStore` could fetch one by id or list the newest, and nothing else,
so finding a report you half-remembered meant paging through previews.

A scan rather than an index: `_prune` caps the table at a couple of hundred
rows, and an FTS5 virtual table would mean triggers to keep in step, a
migration for every existing install, and tokeniser rules to explain, to
search a corpus that fits in memory several times over.
"""

from __future__ import annotations

import pytest

from nira.research import ResearchStore


@pytest.fixture
def store(tmp_path):
    st = ResearchStore(str(tmp_path / "research.db"))
    st.save(query="rust memory model", report="ownership and borrowing explained")
    st.save(query="python gil", report="the global interpreter lock, in detail")
    st.save(query="sqlite wal mode", report="write-ahead logging and its tradeoffs")
    yield st
    st.close()


class TestSearch:
    def test_it_matches_the_query(self, store) -> None:
        assert [r.query for r in store.search("gil")] == ["python gil"]

    def test_it_matches_the_body(self, store) -> None:
        """The thing you remember is usually a phrase from the report."""
        assert [r.query for r in store.search("borrowing")] == ["rust memory model"]

    def test_it_is_case_insensitive(self, store) -> None:
        # SQLite's LIKE is ASCII-case-insensitive by default; pin it, because
        # a reader does not capitalise their search the way they wrote it.
        assert len(store.search("GIL")) == 1

    def test_no_match_is_empty_not_everything(self, store) -> None:
        assert store.search("kubernetes") == []

    def test_an_empty_term_lists_the_recent(self, store) -> None:
        """A cleared search box should show the listing, not nothing."""
        assert len(store.search("")) == 3
        assert len(store.search("   ")) == 3

    def test_newest_first(self, store) -> None:
        store.save(query="rust async", report="futures and pinning")
        assert store.search("rust")[0].query == "rust async"

    def test_limit_is_honoured(self, store) -> None:
        assert len(store.search("", limit=2)) == 2


class TestWildcardsAreNotOperators:
    """A reader's search term is text, not a LIKE pattern."""

    def test_percent_does_not_match_everything(self, tmp_path) -> None:
        st = ResearchStore(str(tmp_path / "w.db"))
        st.save(query="100% coverage", report="a report about tests")
        st.save(query="unrelated", report="nothing in common")

        # Unescaped, `%` is LIKE's match-anything and would return both.
        assert [r.query for r in st.search("%")] == ["100% coverage"]
        st.close()

    def test_underscore_is_literal(self, tmp_path) -> None:
        st = ResearchStore(str(tmp_path / "u.db"))
        st.save(query="report_id handling", report="ids")
        st.save(query="reportXid", report="not a match")

        # Unescaped, `_` matches any single character and would return both.
        assert [r.query for r in st.search("report_id")] == ["report_id handling"]
        st.close()
