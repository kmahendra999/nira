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


class TestWarmUp:
    """The first spoken turn should not pay the model load.

    Backend resolution is lazy, so without warm-up the first utterance loads
    Whisper and Kokoro on top of its own latency — several seconds, exactly
    once, at the worst possible moment.
    """

    def test_loads_both_backends_off_the_critical_path(self) -> None:
        from nira.cli._voice_chat import VoiceSession

        stt = MagicMock()
        session = VoiceSession(MagicMock())

        with (
            patch.object(VoiceSession, "get_stt_backend", return_value=stt) as get_stt,
            patch.object(VoiceSession, "get_tts_backend") as get_tts,
        ):
            session.warm_up().join(timeout=5)

        get_stt.assert_called_once()
        get_tts.assert_called_once()
        # Resolving the backend is not enough; the weights have to be loaded.
        stt._ensure_model.assert_called_once()

    def test_runs_on_a_background_thread(self) -> None:
        """It must not block the banner, let alone the first prompt."""
        import threading

        from nira.cli._voice_chat import VoiceSession

        observed = {}

        def _slow():
            observed["thread"] = threading.current_thread().name
            return MagicMock()

        session = VoiceSession(MagicMock())
        with (
            patch.object(VoiceSession, "get_stt_backend", side_effect=_slow),
            patch.object(VoiceSession, "get_tts_backend"),
        ):
            thread = session.warm_up()
            thread.join(timeout=5)

        assert observed["thread"] != threading.main_thread().name
        assert thread.daemon, "a wedged model load must not keep the CLI alive"

    def test_a_failure_is_swallowed(self) -> None:
        """A head start, not a health check.

        Both resolvers run again on the real turn, where their errors are
        reported to the user with something actionable.
        """
        from nira.cli._voice_chat import VoiceSession

        session = VoiceSession(MagicMock())
        with (
            patch.object(
                VoiceSession, "get_stt_backend", side_effect=RuntimeError("no mic")
            ),
            patch.object(
                VoiceSession, "get_tts_backend", side_effect=RuntimeError("no kokoro")
            ),
        ):
            session.warm_up().join(timeout=5)  # must not raise


class TestBargeIn:
    """Interrupting a spoken reply.

    Playback was sd.play() + sd.wait(): a long answer had to be sat through,
    and Ctrl-C did not reach it. Barge-in stays off by default because there
    is no acoustic echo cancellation — on open speakers the microphone hears
    the reply and Nira interrupts itself.
    """

    def _session(self, *, barge_in: bool):
        from nira.cli._voice_chat import VoiceSession

        session = VoiceSession(MagicMock())
        session._barge_in = barge_in
        return session

    def test_disabled_by_default(self) -> None:
        from nira.core.config import SpeechConfig

        assert SpeechConfig().barge_in is False

    def test_no_listener_is_started_when_disabled(self) -> None:
        session = self._session(barge_in=False)

        with (
            patch("nira.speech.voice_io.SpeechInterrupter") as interrupter,
            patch("nira.cli._voice_chat.speak", return_value=True),
        ):
            speak_token_stream(_tokens("Hello."), MagicMock(), session, echo=False)

        interrupter.assert_not_called()

    def test_an_interruption_stops_speaking_the_rest(self) -> None:
        session = self._session(barge_in=False)
        spoken = []

        def _speak(text, *_args, **_kwargs):
            spoken.append(text)
            return len(spoken) < 2  # the second utterance is cut short

        with patch("nira.cli._voice_chat.speak", side_effect=_speak):
            speak_token_stream(
                _tokens("One. Two. Three. Four."), MagicMock(), session, echo=False
            )

        assert spoken == ["One.", "Two."], "kept speaking after the interruption"

    def test_the_transcript_stays_complete_after_an_interruption(self) -> None:
        """Speech stops; the reply itself is still recorded in history."""
        session = self._session(barge_in=False)
        text = "One. Two. Three. Four."

        with patch("nira.cli._voice_chat.speak", return_value=False):
            result = speak_token_stream(_tokens(text), MagicMock(), session, echo=False)

        assert result == text

    def test_a_listener_failure_does_not_cost_the_reply(self) -> None:
        session = self._session(barge_in=True)

        with (
            patch(
                "nira.speech.voice_io.SpeechInterrupter",
                side_effect=RuntimeError("no microphone"),
            ),
            patch("nira.cli._voice_chat.speak", return_value=True) as speak,
        ):
            speak_token_stream(_tokens("Hello."), MagicMock(), session, echo=False)

        speak.assert_called_once()
