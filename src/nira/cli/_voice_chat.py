"""Voice input/output helpers for the interactive chat session."""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterable, Optional

from rich.markup import escape

from nira.speech.text_prep import (
    has_speakable_content,
    strip_markdown_for_speech,
)

logger = logging.getLogger(__name__)

VOICE_EXIT = object()
_TTS_BACKEND_ORDER = ("kokoro", "openai_tts", "cartesia")
# Voice IDs are backend-specific and NOT portable. ``speech.voice_id`` applies
# only to ``speech.tts_backend``; if synthesis falls back to another backend we
# use that backend's own default rather than passing an unrecognized ID through.
_BACKEND_DEFAULT_VOICE = {
    "kokoro": "bm_george",  # British male
    "openai_tts": "onyx",  # deepest OpenAI preset
    "cartesia": "",  # no safe static default; let Cartesia choose
}


def _terminal_safe_text(value: object) -> str:
    """Remove terminal controls and escape Rich markup from dynamic text."""
    printable = "".join(
        char for char in str(value) if char in ("\n", "\t") or char.isprintable()
    )
    return escape(printable)


class VoiceSession:
    """Cache healthy speech backends for one interactive chat session."""

    def __init__(self, config: object | None = None) -> None:
        self._config = config
        self._language: Optional[str] = None
        self._stt_resolved = False
        self._stt_backend: Any = None
        self._tts_backend: Any = None
        self._tts_attempted: set[str] = set()
        self._voice_prefs: tuple[str, str, float] | None = None
        self._voice_warned: set[str] = set()

    def get_stt_backend(self) -> Any:
        """Resolve and health-check STT once, then reuse the loaded backend."""
        if not self._stt_resolved:
            from nira.core.config import load_config
            from nira.speech._discovery import get_speech_backend

            config = self._config if self._config is not None else load_config()
            self._stt_backend = get_speech_backend(config)
            self._stt_resolved = True
        return self._stt_backend

    def get_tts_backend(self) -> Any:
        """Return a cached healthy TTS backend, falling through once per key."""
        if self._tts_backend is not None:
            return self._tts_backend

        # Import triggers built-in backend registration only when voice output
        # is actually requested.
        import nira.speech  # noqa: F401
        from nira.core.registry import TTSRegistry

        preferred, _, _ = self.get_voice_preferences()
        backend_order = dict.fromkeys((preferred, *_TTS_BACKEND_ORDER))
        for key in backend_order:
            if key in self._tts_attempted:
                continue
            self._tts_attempted.add(key)
            if not TTSRegistry.contains(key):
                continue
            try:
                candidate = TTSRegistry.get(key)()
                if candidate.health():
                    self._tts_backend = candidate
                    return candidate
            except Exception:
                continue
        return None

    def get_voice_preferences(self) -> tuple[str, str, float]:
        """Resolve configured (tts_backend, voice_id, speed), cached per session."""
        if self._voice_prefs is None:
            from nira.core.config import load_config

            config = self._config if self._config is not None else load_config()
            speech = getattr(config, "speech", None)
            self._voice_prefs = (
                getattr(speech, "tts_backend", "kokoro") or "kokoro",
                getattr(speech, "voice_id", "") or "",
                float(getattr(speech, "voice_speed", 1.0)),
            )
        return self._voice_prefs

    def get_language(self) -> Optional[str]:
        """Resolve ``speech.language``, cached per session.

        Empty means auto-detect. Passing it matters for latency as well as
        accuracy: without a language Whisper runs a detection pass over every
        single utterance, which is pure overhead for a user who always speaks
        the same language. The setting was declared in SpeechConfig but read
        nowhere, so configuring it did nothing.
        """
        if self._language is None:
            from nira.core.config import load_config

            config = self._config if self._config is not None else load_config()
            speech = getattr(config, "speech", None)
            self._language = (getattr(speech, "language", "") or "").strip()
        return self._language or None

    def voice_for_backend(self, backend: Any, console: Any = None) -> tuple[str, float]:
        """Return the voice ID valid for ``backend``, plus the configured speed.

        Voice IDs are not portable across backends, so the configured
        ``speech.voice_id`` is honored only when ``backend`` is the configured
        ``speech.tts_backend``. Otherwise the fallback backend's own default is
        used and the substitution is reported once per session.
        """
        want_backend, voice_id, speed = self.get_voice_preferences()
        active = getattr(backend, "backend_id", "") or ""
        if active == want_backend:
            return voice_id, speed

        substitute = _BACKEND_DEFAULT_VOICE.get(active, "")
        if console is not None and active not in self._voice_warned:
            self._voice_warned.add(active)
            console.print(
                f"[dim yellow]Voice: {want_backend!r} unavailable — using "
                f"{active!r} with its default voice "
                f"({substitute or 'backend default'}).[/dim yellow]"
            )
        return substitute, speed

    def warm_up(self) -> threading.Thread:
        """Resolve and load both backends in the background.

        Everything here is lazy, so without this the *first* spoken turn pays
        the full Whisper and Kokoro model load on top of its own latency —
        several seconds, exactly once, at the worst possible moment. The user
        has already told us they want voice by passing --voice, so the load can
        start while they are still reading the banner.

        Failures are swallowed: this is a head start, not a health check. Both
        resolvers are called again on the real turn, where their errors are
        reported to the user with something actionable.
        """

        def _load() -> None:
            try:
                backend = self.get_stt_backend()
                ensure = getattr(backend, "_ensure_model", None)
                if callable(ensure):
                    ensure()
            except Exception:
                logger.debug("STT warm-up failed", exc_info=True)
            try:
                self.get_tts_backend()
            except Exception:
                logger.debug("TTS warm-up failed", exc_info=True)

        thread = threading.Thread(target=_load, name="nira-voice-warmup", daemon=True)
        thread.start()
        return thread

    def discard_tts_backend(self) -> None:
        """Forget a backend that failed synthesis and allow the next fallback."""
        self._tts_backend = None


def read_voice_input(console: Any, session: VoiceSession) -> Optional[str] | object:
    """Accept a typed command/message, or record after an empty submission."""
    try:
        typed = input("You> [type, or press Enter to speak] ")
    except (EOFError, KeyboardInterrupt):
        return VOICE_EXIT
    typed = typed.strip()
    return typed if typed else record_voice(console, session)


def record_voice(
    console: Any,
    session: VoiceSession | None = None,
) -> Optional[str] | object:
    """Record from mic, transcribe, and return text or a loop sentinel."""
    from nira.speech.voice_io import record_until_silence

    active_session = session or VoiceSession()
    backend = active_session.get_stt_backend()
    if backend is None:
        console.print(
            "[red]No speech-to-text backend available. "
            "Install the voice dependencies with: "
            "pip install 'Nira[voice]', or configure a healthy "
            "OpenAI/Deepgram backend.[/red]"
        )
        return VOICE_EXIT

    console.print("[dim cyan]Listening… (speak now, stops on silence)[/dim cyan]")
    try:
        recording = record_until_silence()
    except KeyboardInterrupt:
        return VOICE_EXIT
    except Exception as exc:
        # PortAudio failures are regular Exceptions (and can surface as
        # OSError), so report them without letting terminal control sequences
        # through. SystemExit deliberately continues to propagate, while
        # Ctrl-C maps to the chat loop's graceful-exit sentinel above.
        console.print(f"[red]Mic error: {_terminal_safe_text(exc)}[/red]")
        return VOICE_EXIT

    if not recording.had_speech:
        # The gate never opened, so this is the startup timeout's worth of
        # room tone. Transcribing it costs a full decode and reliably
        # hallucinates a stock phrase out of the noise.
        console.print("[dim]Nothing heard — try again.[/dim]")
        return None

    console.print("[dim]Transcribing…[/dim]")
    try:
        result = backend.transcribe(
            recording.audio, format="wav", language=active_session.get_language()
        )
        text = result.text.strip()
        if text:
            console.print(f"[bold]You (voice):[/bold] {_terminal_safe_text(text)}")
            return text
        console.print("[dim]Nothing heard — try again.[/dim]")
        return None
    except Exception as exc:
        console.print(f"[red]Transcription error: {_terminal_safe_text(exc)}[/red]")
        return None


def speak(text: str, console: Any, session: VoiceSession | None = None) -> None:
    """Synthesize and play text, reusing a healthy backend for the session."""
    from nira.speech.voice_io import play_wav

    active_session = session or VoiceSession()

    # Resolved before the loop: a bad config value must surface as a config
    # error, not be swallowed by the per-backend fallback handler below.
    try:
        active_session.get_voice_preferences()
    except Exception as exc:
        console.print(f"[red]Invalid speech config: {_terminal_safe_text(exc)}[/red]")
        return

    spoken = strip_markdown_for_speech(text)
    if not has_speakable_content(spoken):
        # Markdown that reduces to nothing — a bare code fence, a rule. There
        # is no audio to produce, and handing it to a backend just produces an
        # error the user cannot act on.
        return

    while (backend := active_session.get_tts_backend()) is not None:
        played_any = False
        try:
            voice_id, speed = active_session.voice_for_backend(backend, console)
            synth_kwargs: dict[str, Any] = {"output_format": "wav", "speed": speed}
            if voice_id:
                synth_kwargs["voice_id"] = voice_id
            # TTSBackend supplies a default synthesize_stream, but the registry
            # holds whatever was registered — a duck-typed object implementing
            # only synthesize is legitimate, and an interface addition must not
            # break it.
            stream = getattr(backend, "synthesize_stream", None)
            if callable(stream):
                pieces = stream(spoken, **synth_kwargs)
            else:
                pieces = [backend.synthesize(spoken, **synth_kwargs)]

            for piece in pieces:
                if not piece.audio:
                    continue
                play_wav(piece.audio, sample_rate=piece.sample_rate)
                played_any = True
            return
        except Exception as exc:
            console.print(
                f"[dim yellow]Voice backend "
                f"{getattr(backend, 'backend_id', '?')!r} failed: "
                f"{_terminal_safe_text(exc)}[/dim yellow]"
            )
            if played_any:
                # Part of this utterance is already audible. Falling back now
                # would synthesise the same text on another backend and repeat
                # what the user just heard, in a different voice.
                return
            active_session.discard_tts_backend()

    console.print(
        "[dim yellow]No text-to-speech backend available. Install the voice "
        "dependencies with: pip install 'Nira[voice]', or configure a healthy "
        "OpenAI/Cartesia backend.[/dim yellow]"
    )


def speak_token_stream(
    tokens: "Iterable[str]",
    console: Any,
    session: VoiceSession | None = None,
    *,
    echo: bool = True,
) -> str:
    """Speak a reply as it generates, and return the full text.

    This is the whole point of the voice pipeline. Previously a turn ran
    strictly in series — record, transcribe, generate the *entire* completion,
    synthesise all of it, then play — so time-to-first-audio was the cost of
    the whole reply and a long answer meant a long silence.

    Here each sentence is spoken as soon as it is complete. Because playback
    blocks while the producer thread keeps pulling tokens (see
    ``speech.pipeline``), generation of the next sentence overlaps with speech
    of the current one, and the user hears the first words after roughly one
    sentence rather than after the last token.

    With ``echo`` the text is also printed as it arrives, so the terminal is no
    longer silent until the reply completes.
    """
    from nira.speech.segmentation import SentenceAccumulator

    accumulator = SentenceAccumulator()
    full: list[str] = []

    for token in tokens:
        full.append(token)
        if echo:
            console.print(_terminal_safe_text(token), end="", markup=False)
        for sentence in accumulator.push(token):
            speak(sentence, console, session)

    for sentence in accumulator.flush():
        speak(sentence, console, session)

    if echo:
        console.print()
    return "".join(full)


__all__ = [
    "VOICE_EXIT",
    "VoiceSession",
    "read_voice_input",
    "record_voice",
    "speak",
    "speak_token_stream",
]
