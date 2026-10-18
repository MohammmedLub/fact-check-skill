"""Transcription Agent: produce the transcript in the video's original language."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .video import VideoSource


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    language: str | None
    method: str  # "file" | "subtitles" | "whisper"


_TIMING = re.compile(r"^\d{2}:\d{2}(:\d{2})?[.,]\d{3} -->")
_TAG = re.compile(r"<[^>]+>")


def parse_vtt(content: str) -> str:
    """Plain text from WebVTT/SRT, without timings, tags or rolling duplicates."""
    lines: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if (not line or line == "WEBVTT" or line.isdigit() or _TIMING.match(line)
                or line.startswith(("Kind:", "Language:", "NOTE", "STYLE"))):
            continue
        line = _TAG.sub("", line).strip()
        # Auto-captions repeat each line while it scrolls - keep it once.
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def transcribe(video: VideoSource | None, transcript_file: Path | None = None,
               language: str | None = None, whisper_model: str = "small") -> Transcript:
    if transcript_file:
        text = Path(transcript_file).read_text(encoding="utf-8")
        if transcript_file.suffix.lower() in (".vtt", ".srt"):
            text = parse_vtt(text)
        return Transcript(text.strip(), language, "file")

    if video is None:
        raise TranscriptionError("Nothing to transcribe.")

    if video.subtitles_path:
        text = parse_vtt(video.subtitles_path.read_text(encoding="utf-8"))
        if text.strip():
            return Transcript(text, language or video.language, "subtitles")

    if video.audio_path is None:
        raise TranscriptionError("The video has no subtitles and no audio could be extracted.")
    return _whisper(video.audio_path, language, whisper_model)


def _whisper(audio: Path, language: str | None, model_size: str) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise TranscriptionError(
            "This video has no subtitles. Install local speech-to-text with "
            "pip install 'hayat-ai[whisper]', or pass --transcript with the text."
        ) from None
    model = WhisperModel(model_size, compute_type="int8")
    segments, info = model.transcribe(str(audio), language=language, vad_filter=True)
    text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip())
    if not text:
        raise TranscriptionError("No speech was detected in the audio.")
    return Transcript(text, info.language, "whisper")
