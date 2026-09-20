"""Abstract base classes and data types for text-to-speech backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List


@dataclass
class TTSResult:
    """Result of a text-to-speech synthesis."""

    audio: bytes
    format: str = "mp3"
    duration_seconds: float = 0.0
    voice_id: str = ""
    sample_rate: int = 24000
    metadata: Dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> Path:
        """Write audio bytes to a file and return the path."""
        path.write_bytes(self.audio)
        return path


class TTSBackend(ABC):
    """Abstract base class for text-to-speech backends."""

    backend_id: str = ""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        """Synthesize text to audio."""

    def synthesize_stream(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> Iterator[TTSResult]:
        """Yield audio for *text* in pieces, as they become available.

        Not abstract: the default synthesises the whole utterance and yields
        one piece, so every existing backend keeps working unchanged. Backends
        whose engine produces audio incrementally should override this — until
        one does, nothing in the stack *can* stream, because the only entry
        point returned a finished blob.

        A caller must treat the pieces as a sequence to play in order; each one
        carries its own sample rate.
        """
        result = self.synthesize(
            text, voice_id=voice_id, speed=speed, output_format=output_format
        )
        if result.audio:
            yield result

    @abstractmethod
    def available_voices(self) -> List[str]:
        """Return list of available voice IDs."""

    @abstractmethod
    def health(self) -> bool:
        """Check if the backend is ready."""


__all__ = ["TTSBackend", "TTSResult"]
