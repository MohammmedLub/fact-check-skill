"""Video Agent: get the video's audio and subtitles from a link or a local file.

Links (TikTok, Instagram, YouTube, ...) go through yt-dlp. If a link is
blocked, download/record the video yourself and pass the file path instead.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class VideoError(RuntimeError):
    pass


@dataclass
class VideoSource:
    source: str               # the link or file path the user gave
    title: str
    audio_path: Path | None   # 16 kHz mono wav, ready for speech-to-text
    subtitles_path: Path | None
    language: str | None      # language reported by the platform, if any


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _yt_dlp() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise VideoError(
            "yt-dlp is not installed. Run: pip install 'hayat-ai[video]' "
            "- or download the video yourself and pass the file path."
        ) from None
    return [sys.executable, "-m", "yt_dlp"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoError(f"{cmd[0]} failed:\n{proc.stderr.strip()[-1500:]}")
    return proc


def extract_audio(video_path: Path, out_dir: Path) -> Path:
    if not shutil.which("ffmpeg"):
        raise VideoError("ffmpeg is required to extract audio (https://ffmpeg.org/download.html).")
    wav = out_dir / (video_path.stem + ".wav")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
          "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    return wav


def fetch(source: str, work_dir: Path, want_audio: bool = True) -> VideoSource:
    work_dir.mkdir(parents=True, exist_ok=True)

    if not is_url(source):
        path = Path(source).expanduser()
        if not path.exists():
            raise VideoError(f"File not found: {path}")
        audio = extract_audio(path, work_dir) if want_audio else None
        return VideoSource(source, path.stem, audio, None, None)

    base = _yt_dlp()
    info = json.loads(_run(base + ["--dump-single-json", "--no-playlist", source]).stdout)
    title = info.get("title") or info.get("id") or source
    vid = info.get("id", "video")

    # Subtitles first: free, fast and exact when the creator added them.
    _run(base + ["--skip-download", "--no-playlist", "--write-subs", "--write-auto-subs",
                 "--sub-format", "vtt", "--sub-langs", "all,-live_chat",
                 "-o", str(work_dir / f"{vid}.%(ext)s"), source])
    subs = sorted(work_dir.glob(f"{vid}*.vtt"))
    subtitles = _pick_original_subs(subs, info.get("language"))

    audio = None
    if want_audio and subtitles is None:
        _run(base + ["-x", "--audio-format", "wav", "--no-playlist",
                     "-o", str(work_dir / f"{vid}.%(ext)s"), source])
        downloaded = work_dir / f"{vid}.wav"
        audio = extract_audio(downloaded, work_dir / "mono") if downloaded.exists() else None
    return VideoSource(source, title, audio, subtitles, info.get("language"))


def _pick_original_subs(subs: list[Path], language: str | None) -> Path | None:
    if not subs:
        return None
    # Files look like "<id>.<lang>.vtt"; match the spoken language when known.
    if language:
        for s in subs:
            if s.suffixes[-2:-1] in ([f".{language}"], [f".{language}-orig"]):
                return s
    for s in subs:
        if "-orig" in s.name:
            return s
    return subs[0]
