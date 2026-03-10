"""
Speech-to-text transcription using faster-whisper.
Extracts audio from video and returns timestamped segments.
"""

from faster_whisper import WhisperModel
from pathlib import Path
import subprocess
import tempfile
import logging
import os

import torch

log = logging.getLogger(__name__)

# Load model once at startup
_device = "cuda" if torch.cuda.is_available() else "cpu"
_compute = "float16" if _device == "cuda" else "int8"
log.info("Loading Whisper large-v3 on %s (%s)...", _device, _compute)
model = WhisperModel("large-v3", device=_device, compute_type=_compute)
log.info("Whisper model ready.")


def extract_audio(video_path: str, output_path: str = None) -> str:
    """Extract audio from video file using FFmpeg."""
    if output_path is None:
        output_path = tempfile.mktemp(suffix=".wav")

    subprocess.run(
        [
            "ffmpeg", "-i", video_path,
            "-vn",                # no video
            "-acodec", "pcm_s16le",  # PCM 16-bit
            "-ar", "16000",       # 16kHz sample rate (optimal for Whisper)
            "-ac", "1",           # mono
            "-y",                 # overwrite
            output_path,
        ],
        capture_output=True,
        check=True,
    )
    return output_path


def transcribe(audio_path: str, language: str = None) -> list[dict]:
    """
    Transcribe an audio file and return timestamped segments.

    Args:
        audio_path: Path to the WAV audio file.
        language: Language code ('ar', 'en', or None for auto-detect).

    Returns:
        List of dicts: [{"start": float, "end": float, "text": str}, ...]
    """
    kwargs = {}
    if language:
        kwargs["language"] = language

    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=300,
        ),
        **kwargs,
    )

    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({
                    "start": w.start,
                    "end": w.end,
                    "word": w.word.strip(),
                })
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": words,
        })

    return segments
