"""Tests for incremental sentence segmentation.

Voice mode waited for a whole completion before synthesising any of it, so
time-to-first-audio was the cost of the entire reply. These cover the splitter
that lets synthesis start after the first sentence.

The failure mode that matters is a *premature* cut: once audio is playing it
cannot be taken back, and a clause spoken as if it were a sentence gets the
wrong intonation. So most of these pin the cases where a period does NOT end a
sentence.
"""

from __future__ import annotations

from nira.speech.segmentation import SentenceAccumulator


def _stream(text: str, **kwargs) -> list[str]:
    """Feed *text* one character at a time, as a token stream would arrive."""
    acc = SentenceAccumulator(**kwargs)
    out: list[str] = []
    for ch in text:
        out.extend(acc.push(ch))
    out.extend(acc.flush())
    return out


class TestSentenceBoundaries:
    def test_splits_on_terminal_punctuation(self) -> None:
        assert _stream("Hello there. How are you? Good!") == [
            "Hello there.",
            "How are you?",
            "Good!",
        ]

    def test_emits_as_soon_as_a_sentence_completes(self) -> None:
        """The whole point: do not wait for the rest of the reply."""
        acc = SentenceAccumulator()

        # The space after the period is what confirms the boundary; until it
        # arrives this could still be "42.5".
        assert acc.push("The answer is 42.") == []
        assert acc.push(" And") == ["The answer is 42."]
        assert acc.pending == "And"

    def test_keeps_trailing_quotes_and_brackets_with_the_sentence(self) -> None:
        assert _stream('He said "go." Then left.') == ['He said "go."', "Then left."]

    def test_paragraph_break_ends_an_utterance_without_punctuation(self) -> None:
        assert _stream("Results\n\nEverything passed.") == [
            "Results",
            "Everything passed.",
        ]

    def test_flush_returns_an_unterminated_tail(self) -> None:
        acc = SentenceAccumulator()
        acc.push("No terminator here")

        assert acc.flush() == ["No terminator here"]

    def test_flush_on_empty_buffer_returns_nothing(self) -> None:
        assert SentenceAccumulator().flush() == []


class TestFalseBoundaries:
    """A period is not always the end of a sentence."""

    def test_decimal_numbers_do_not_split(self) -> None:
        assert _stream("Pi is 3.14 exactly.") == ["Pi is 3.14 exactly."]

    def test_version_numbers_do_not_split(self) -> None:
        assert _stream("Needs Python 3.12 or newer.") == ["Needs Python 3.12 or newer."]

    def test_common_abbreviations_do_not_split(self) -> None:
        assert _stream("See e.g. the docs. Then continue.") == [
            "See e.g. the docs.",
            "Then continue.",
        ]

    def test_titles_do_not_split(self) -> None:
        assert _stream("Dr. Smith arrived. He was late.") == [
            "Dr. Smith arrived.",
            "He was late.",
        ]

    def test_list_enumerators_do_not_split(self) -> None:
        """ "1." starting a list item is not a one-character sentence."""
        chunks = _stream("1. Install it\n2. Run it\n")

        assert not any(chunk.strip() in {"1.", "2."} for chunk in chunks)

    def test_initials_do_not_split(self) -> None:
        assert _stream("J. R. Tolkien wrote it.") == ["J. R. Tolkien wrote it."]


class TestLatencyGuards:
    def test_first_chunk_may_break_at_a_clause(self) -> None:
        """Time-to-first-audio dominates the impression of responsiveness."""
        chunks = _stream(
            "Let me check the configuration, then I will report back.",
            first_chunk_chars=30,
        )

        assert chunks[0] == "Let me check the configuration,"

    def test_only_the_first_chunk_breaks_at_a_clause(self) -> None:
        """Later chunks wait for real sentence ends so prosody stays natural."""
        chunks = _stream(
            "First one done. Now a long second clause, which continues onward.",
            first_chunk_chars=10,
        )

        assert chunks[0] == "First one done."
        assert "Now a long second clause, which continues onward." in chunks

    def test_a_run_on_is_force_emitted_rather_than_stalling_audio(self) -> None:
        """A model writing an unpunctuated wall of text must not block playback."""
        text = "word " * 200

        chunks = _stream(text, max_chars=80, first_chunk_chars=0)

        assert len(chunks) > 1
        assert all(len(chunk) <= 80 for chunk in chunks)

    def test_force_emit_does_not_split_a_word(self) -> None:
        chunks = _stream(
            "alpha bravo charlie delta echo", max_chars=12, first_chunk_chars=0
        )

        for chunk in chunks:
            for word in chunk.split():
                assert word in {"alpha", "bravo", "charlie", "delta", "echo"}


class TestUnspeakableContent:
    def test_punctuation_only_chunks_are_dropped(self) -> None:
        """Nothing to pronounce, so do not hand it to a synthesiser."""
        assert _stream("...") == []

    def test_a_real_sentence_after_junk_still_arrives(self) -> None:
        assert _stream("--- \n\nReal content here.") == ["Real content here."]

    def test_empty_tokens_are_ignored(self) -> None:
        acc = SentenceAccumulator()

        assert acc.push("") == []
        assert acc.pending == ""


class TestTokenArrival:
    def test_result_is_independent_of_token_chunking(self) -> None:
        """The same text must segment identically however it is chopped up."""
        text = "One. Two. Three."

        one_shot = SentenceAccumulator()
        whole = one_shot.push(text) + one_shot.flush()

        assert whole == _stream(text)

    def test_a_boundary_split_across_tokens_is_still_found(self) -> None:
        acc = SentenceAccumulator()
        assert acc.push("Done") == []
        assert acc.push(".") == []  # the following space has not arrived yet
        out = acc.push(" Next") + acc.flush()

        assert out == ["Done.", "Next"]

    def test_a_trailing_period_is_not_cut_before_its_context_arrives(self) -> None:
        """The regression that motivated dropping the end-of-buffer anchor.

        Mid-stream the buffer ends wherever the last token landed. Treating
        that as a sentence end cut "3." out of "3.14" and '"go.' out of
        '"go."', and a spoken fragment cannot be taken back.
        """
        acc = SentenceAccumulator()

        assert acc.push("Pi is 3.") == []
        assert acc.push("14 exactly.") == []
        assert acc.flush() == ["Pi is 3.14 exactly."]
