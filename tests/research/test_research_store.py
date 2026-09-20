"""A link that promises a report has to be able to produce one.

``channel_agent`` answers a long query over Telegram, Slack or iMessage with a
preview and ``nira://research/<id>``. The scheme is registered with the OS and
the desktop app parses the URL — and the report itself was never written down.
The full text went out of scope the moment the preview was cut from it, and the
id was a fresh uuid that referred to nothing.

A missing feature is a disappointment. A link that promises something already
thrown away is a bug report.
"""

from __future__ import annotations

import pytest

from nira.research import ResearchReport, ResearchStore


@pytest.fixture
def store(tmp_path):
    research = ResearchStore(tmp_path / "research.db")
    yield research
    research.close()


class TestSavingAndReading:
    def test_a_report_can_be_read_back(self, store) -> None:
        saved = store.save("what is quantum computing", "A long answer.")

        found = store.get(saved.id)

        assert found is not None
        assert found.report == "A long answer."
        assert found.query == "what is quantum computing"

    def test_the_caller_chooses_the_id(self, store) -> None:
        # The reply quoting that id is often already composed. Writing the
        # report under a different one would recreate the dangling link this
        # store exists to fix.
        store.save("q", "report", report_id="sess_abc")

        assert store.get("sess_abc") is not None

    def test_an_id_is_minted_when_none_is_given(self, store) -> None:
        saved = store.save("q", "report")

        assert saved.id
        assert store.get(saved.id) is not None

    def test_an_unknown_id_finds_nothing(self, store) -> None:
        assert store.get("never-existed") is None

    def test_the_channel_it_came_from_is_kept(self, store) -> None:
        store.save("q", "r", report_id="a", channel="telegram")

        assert store.get("a").channel == "telegram"

    def test_saving_the_same_id_replaces_rather_than_duplicates(self, store) -> None:
        store.save("q", "first", report_id="a")
        store.save("q", "second", report_id="a")

        # A retry must not leave two rows racing to answer one link.
        assert store.get("a").report == "second"
        assert store.count() == 1

    def test_a_report_survives_reopening_the_store(self, tmp_path) -> None:
        path = tmp_path / "research.db"
        first = ResearchStore(path)
        first.save("q", "durable", report_id="a")
        first.close()

        second = ResearchStore(path)
        try:
            # The link may be opened days later, from a desktop that has been
            # restarted since.
            assert second.get("a").report == "durable"
        finally:
            second.close()

    def test_an_empty_report_is_still_stored(self, store) -> None:
        # Better an empty report than a 404 that suggests the link was wrong.
        store.save("q", "", report_id="a")

        assert store.get("a") is not None


class TestListing:
    def test_recent_comes_back_newest_first(self, store) -> None:
        for index in range(3):
            store.save(f"q{index}", "r", report_id=f"a{index}")

        assert [r.id for r in store.recent()] == ["a2", "a1", "a0"]

    def test_the_limit_is_honoured(self, store) -> None:
        for index in range(5):
            store.save("q", "r", report_id=f"a{index}")

        assert len(store.recent(limit=2)) == 2

    def test_an_empty_store_lists_nothing(self, store) -> None:
        assert store.recent() == []


class TestPruning:
    def test_old_reports_are_dropped_beyond_the_limit(self, tmp_path) -> None:
        store = ResearchStore(tmp_path / "research.db", keep=3)
        try:
            for index in range(6):
                store.save("q", "r", report_id=f"a{index}")

            # Reports run to thousands of words and are read once. Keeping
            # every one forever grows a database nobody prunes.
            assert store.count() == 3
            assert store.get("a5") is not None
            assert store.get("a0") is None
        finally:
            store.close()

    def test_pruning_is_by_count_not_age(self, tmp_path) -> None:
        store = ResearchStore(tmp_path / "research.db", keep=2)
        try:
            store.save("q", "r", report_id="old")
            store.save("q", "r", report_id="new")

            # Someone who researches rarely should not lose their only report
            # to a clock.
            assert store.get("old") is not None
        finally:
            store.close()


class TestSerialising:
    def test_a_preview_stops_at_a_word(self, store) -> None:
        report = ResearchReport(id="a", query="q", report="alpha beta gamma delta")

        preview = report.preview(limit=12)

        # Cutting mid-token reads as corruption rather than as truncation.
        assert not preview.rstrip("…").endswith("gam")
        assert preview.endswith("…")

    def test_a_short_report_is_its_own_preview(self, store) -> None:
        report = ResearchReport(id="a", query="q", report="brief")

        assert report.preview() == "brief"


class TestPreviewsReadAsProse:
    """A preview is shown where there is least room, so syntax has to go.

    A report opens with a heading and is full of emphasis. Left as-is the
    preview reads ``# Title Running a model **trades** ...`` — the markup
    crowds out the words in exactly the place that has none to spare.
    """

    def preview(self, markdown: str, limit: int = 500) -> str:
        return ResearchReport(id="a", query="q", report=markdown).preview(limit)

    def test_headings_lose_their_hashes(self) -> None:
        assert self.preview("# Title\n\nBody.") == "Title Body."

    def test_emphasis_keeps_the_words(self) -> None:
        assert self.preview("A **bold** and *italic* claim.") == (
            "A bold and italic claim."
        )

    def test_links_keep_their_text_not_their_url(self) -> None:
        # A preview full of https:// is a preview of nothing.
        assert self.preview("See [the docs](https://example.com).") == ("See the docs.")

    def test_images_do_not_leave_syntax_behind(self) -> None:
        assert self.preview("![a chart](chart.png) follows.") == "a chart follows."

    def test_code_fences_are_dropped(self) -> None:
        # A preview that is entirely someone's Python is not a summary.
        assert self.preview("Before.\n\n```py\nx = 1\n```\n\nAfter.") == (
            "Before. After."
        )

    def test_inline_code_keeps_its_content(self) -> None:
        assert self.preview("Set `max_turns` higher.") == "Set max_turns higher."

    def test_bullets_become_separators_rather_than_vanishing(self) -> None:
        # Without a marker the items run together into one sentence that says
        # something different from the list.
        assert self.preview("Gains:\n- one\n- two") == "Gains: \u00b7 one \u00b7 two"

    def test_numbered_steps_stay_separated(self) -> None:
        assert self.preview("Steps:\n1. first\n2. second") == (
            "Steps: \u00b7 first \u00b7 second"
        )

    def test_blockquotes_lose_their_marker(self) -> None:
        assert self.preview("> quoted thought") == "quoted thought"

    def test_horizontal_rules_disappear(self) -> None:
        assert self.preview("Above.\n\n---\n\nBelow.") == "Above. Below."

    def test_whitespace_collapses_to_one_line(self) -> None:
        # The preview is rendered in a two-line clamp; newlines would spend
        # both of them on nothing.
        assert "\n" not in self.preview("One.\n\n\nTwo.\n\nThree.")

    def test_plain_text_passes_through_unharmed(self) -> None:
        assert self.preview("Nothing special here.") == "Nothing special here."

    def test_the_limit_still_applies_after_stripping(self) -> None:
        # Stripping shortens the text, so the cut has to happen afterwards or
        # a heavily marked-up report gets a much shorter preview than asked.
        preview = self.preview("# H\n\n" + "word " * 200, limit=50)

        assert len(preview) <= 51
        assert preview.endswith("\u2026")

    def test_a_listing_leaves_the_body_out(self, store) -> None:
        report = ResearchReport(id="a", query="q", report="x" * 5000)

        listed = report.to_dict(full=False)

        # Otherwise listing twenty reports ships a hundred thousand characters
        # to render twenty one-line rows.
        assert listed["report"] == ""
        assert listed["preview"]

    def test_asking_for_one_report_includes_it(self, store) -> None:
        report = ResearchReport(id="a", query="q", report="the whole thing")

        assert report.to_dict()["report"] == "the whole thing"
