"""Tests for speaking a reply while it is still generating.

A voice turn used to run strictly in series: record, transcribe, generate the
*entire* completion, synthesise all of it, then play. Silence therefore lasted
as long as the whole answer. ``speak_token_stream`` speaks each sentence as it
completes, so the first words arrive after roughly one sentence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nira.cli._voice_chat import speak_token_stream


def _tokens(text: str):
    """Yield *text* one character at a time, as a token stream would arrive."""
    yield from text


class TestIncrementalSpeech:
    def test_speaks_each_sentence_as_it_completes(self) -> None:
        with patch("nira.cli._voice_chat.speak") as speak:
            speak_token_stream(
                _tokens("First one. Second one. Third one."),
                MagicMock(),
                MagicMock(),
                echo=False,
            )

        spoken = [call.args[0] for call in speak.call_args_list]
        assert spoken == ["First one.", "Second one.", "Third one."]

    def test_does_not_wait_for_the_whole_reply(self) -> None:
        """The first utterance must be spoken before the stream ends."""
        seen_when_first_spoken = []

        def _tracking_tokens():
            for token in ["Ready. ", "Still", " going", " on."]:
                seen_when_first_spoken.append(("produced", token))
                yield token

        def _record_speak(text, *_args, **_kwargs):
            seen_when_first_spoken.append(("spoke", text))

        with patch("nira.cli._voice_chat.speak", side_effect=_record_speak):
            speak_token_stream(_tracking_tokens(), MagicMock(), MagicMock(), echo=False)

        first_speech = next(
            i for i, (kind, _) in enumerate(seen_when_first_spoken) if kind == "spoke"
        )
        remaining = seen_when_first_spoken[first_speech + 1 :]
        assert any(kind == "produced" for kind, _ in remaining), (
            "everything was generated before the first utterance was spoken"
        )

    def test_returns_the_full_text(self) -> None:
        text = "One. Two. Three."

        with patch("nira.cli._voice_chat.speak"):
            result = speak_token_stream(
                _tokens(text), MagicMock(), MagicMock(), echo=False
            )

        assert result == text

    def test_an_unterminated_tail_is_still_spoken(self) -> None:
        """A reply that ends without punctuation must not be swallowed."""
        with patch("nira.cli._voice_chat.speak") as speak:
            speak_token_stream(
                _tokens("Done. And a trailing thought"),
                MagicMock(),
                MagicMock(),
                echo=False,
            )

        assert [c.args[0] for c in speak.call_args_list] == [
            "Done.",
            "And a trailing thought",
        ]

    def test_empty_stream_speaks_nothing(self) -> None:
        with patch("nira.cli._voice_chat.speak") as speak:
            result = speak_token_stream(iter([]), MagicMock(), MagicMock(), echo=False)

        speak.assert_not_called()
        assert result == ""


class TestEcho:
    def test_echo_prints_tokens_as_they_arrive(self) -> None:
        """The terminal used to stay silent until the whole reply landed."""
        console = MagicMock()

        with patch("nira.cli._voice_chat.speak"):
            speak_token_stream(_tokens("Hi there."), console, MagicMock(), echo=True)

        printed = "".join(
            str(call.args[0]) for call in console.print.call_args_list if call.args
        )
        assert "Hi there." in printed

    def test_echo_off_prints_nothing(self) -> None:
        console = MagicMock()

        with patch("nira.cli._voice_chat.speak"):
            speak_token_stream(_tokens("Hi there."), console, MagicMock(), echo=False)

        console.print.assert_not_called()
