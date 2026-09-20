"""Tests for preparing a markdown reply for speech.

chat_cmd rendered the reply as Markdown for the terminal and then handed the
*raw* markdown to the synthesiser, so a reply containing a code block had the
code read out character by character, links were read as their URLs, and every
``**`` and ``##`` was pronounced or mangled depending on the backend.
"""

from __future__ import annotations

from nira.speech.text_prep import has_speakable_content, strip_markdown_for_speech


class TestCodeIsNotReadAloud:
    def test_fenced_code_becomes_a_placeholder(self) -> None:
        text = "Try this:\n\n```python\nfor i in range(5):\n    print(i)\n```\n\nDone."

        spoken = strip_markdown_for_speech(text)

        assert "for i in range" not in spoken
        assert "code block omitted" in spoken
        assert spoken.startswith("Try this:")
        assert spoken.endswith("Done.")

    def test_unterminated_fence_is_still_handled(self) -> None:
        """A truncated reply can end mid-block; it must not leak the body."""
        spoken = strip_markdown_for_speech("Here:\n\n```sh\nrm -rf /tmp/x\n")

        assert "rm -rf" not in spoken

    def test_inline_code_keeps_its_content(self) -> None:
        """Short identifiers are worth hearing; only blocks are dropped."""
        spoken = strip_markdown_for_speech("The `timeout` is `30` seconds.")

        assert spoken == "The timeout is 30 seconds."


class TestLinksAndUrls:
    def test_link_text_is_kept_and_the_url_dropped(self) -> None:
        text = "See the [installation docs](https://example.com/install) for details."

        assert (
            strip_markdown_for_speech(text) == "See the installation docs for details."
        )

    def test_bare_urls_are_dropped(self) -> None:
        """A URL read character by character is noise, not information."""
        spoken = strip_markdown_for_speech("Visit https://example.com/a/b now.")

        assert "example.com" not in spoken
        assert spoken == "Visit now."

    def test_image_alt_text_survives(self) -> None:
        spoken = strip_markdown_for_speech("![a red chart](chart.png) shows growth.")

        assert spoken == "a red chart shows growth."


class TestStructuralMarkers:
    def test_headings_lose_their_hashes(self) -> None:
        assert strip_markdown_for_speech("## Results\n\nAll good.") == (
            "Results\n\nAll good."
        )

    def test_bullets_lose_their_markers(self) -> None:
        assert strip_markdown_for_speech("- one\n- two\n* three") == ("one\ntwo\nthree")

    def test_blockquotes_lose_their_carets(self) -> None:
        assert strip_markdown_for_speech("> quoted\n> lines") == "quoted\nlines"

    def test_horizontal_rules_are_removed_without_joining_paragraphs(self) -> None:
        """The rule goes; the paragraph break it separated must stay."""
        spoken = strip_markdown_for_speech("Above\n\n---\n\nBelow")

        assert spoken == "Above\n\nBelow"

    def test_table_rows_are_read_as_lists(self) -> None:
        text = "| Name | Value |\n|---|---|\n| timeout | 30 |\n| retries | 3 |"

        spoken = strip_markdown_for_speech(text)

        assert "|" not in spoken
        assert "Name, Value" in spoken
        assert "timeout, 30" in spoken
        # The divider row must not swallow the line breaks around it.
        assert "Valuetimeout" not in spoken


class TestEmphasis:
    def test_bold_and_italic_markers_are_removed(self) -> None:
        assert strip_markdown_for_speech("A *very* **important** note.") == (
            "A very important note."
        )

    def test_nested_emphasis_unwraps_fully(self) -> None:
        assert strip_markdown_for_speech("**bold _and_ italic**") == ("bold and italic")

    def test_strikethrough_keeps_the_words(self) -> None:
        assert strip_markdown_for_speech("~~old~~ new") == "old new"


class TestPassthrough:
    def test_plain_prose_is_unchanged(self) -> None:
        text = "Plain text with no markdown at all."

        assert strip_markdown_for_speech(text) == text

    def test_empty_input_is_empty_output(self) -> None:
        assert strip_markdown_for_speech("") == ""

    def test_result_is_stripped(self) -> None:
        assert strip_markdown_for_speech("\n\n  hello  \n\n") == "hello"


class TestHasSpeakableContent:
    def test_true_for_words(self) -> None:
        assert has_speakable_content("hello") is True

    def test_true_for_digits(self) -> None:
        assert has_speakable_content("42") is True

    def test_false_for_punctuation_only(self) -> None:
        assert has_speakable_content("...") is False
        assert has_speakable_content("---") is False

    def test_false_for_whitespace_only(self) -> None:
        assert has_speakable_content("   \n ") is False
