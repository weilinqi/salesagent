"""Audio conversion and opt-in diagnostic retention, without model calls."""
import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

async def convert_audio_to_pcm(audio_bytes: bytes, mime: str) -> Optional[bytes]:
    """Convert to 24 kHz mono PCM; remove work files on every exit path."""
    if not audio_bytes:
        return None
    def convert():
        with tempfile.TemporaryDirectory(prefix="salesagent-audio-") as directory:
            source = Path(directory) / ("input.wav" if "wav" in mime else "input.webm")
            target = Path(directory) / "output.pcm"
            source.write_bytes(audio_bytes)
            result = subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
                "-ar", "24000", "-ac", "1", "-f", "s16le", str(target),
            ], capture_output=True, timeout=10)
            if result.returncode != 0 or not target.is_file():
                return None
            return target.read_bytes()
    try:
        return await asyncio.to_thread(convert)
    except (OSError, subprocess.SubprocessError):
        logger.warning("Audio conversion failed")
        return None

def retain_debug_audio(source: Path, *, enabled: bool, directory: Path,
                       retention_hours: int) -> Optional[Path]:
    """Keep diagnostic recordings only when enabled; prune expired files."""
    if not enabled:
        return None
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - retention_hours * 3600
    for recording in directory.glob("asr-*.wav"):
        if recording.is_file() and not recording.is_symlink() and recording.stat().st_mtime < cutoff:
            recording.unlink()
    target = directory / ("asr-" + uuid.uuid4().hex + ".wav")
    shutil.copyfile(source, target)
    return target

def purge_debug_audio(directory: Path, retention_hours: int) -> None:
    """Remove expired diagnostic files at startup and on scheduled cleanup."""
    if not directory.exists():
        return
    cutoff = time.time() - retention_hours * 3600
    for recording in directory.glob("asr-*.wav"):
        if recording.is_file() and not recording.is_symlink() and recording.stat().st_mtime < cutoff:
            recording.unlink()
