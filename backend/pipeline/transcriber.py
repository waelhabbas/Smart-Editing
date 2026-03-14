"""
Speech-to-text transcription using WhisperX.
Extracts audio from video and returns timestamped segments
with force-aligned word timestamps for precise SRT and timeline generation.
"""

import whisperx
from pathlib import Path
import subprocess
import tempfile
import logging
import os

import torch

from backend.config import (
    WHISPER_MODEL,
    WHISPERX_BATCH_SIZE,
    WHISPERX_FALLBACK_TO_NATIVE,
)

log = logging.getLogger(__name__)

# ── Model loading (once at startup) ──────────────────────────────

_device = "cuda" if torch.cuda.is_available() else "cpu"
_compute = "float16" if _device == "cuda" else "int8"

log.info("Loading WhisperX %s on %s (%s)...", WHISPER_MODEL, _device, _compute)
_asr_model = whisperx.load_model(
    WHISPER_MODEL,
    _device,
    compute_type=_compute,
)
log.info("WhisperX ASR model ready.")

# Cache alignment models per language to avoid reloading
_align_models: dict[str, tuple] = {}


def _get_align_model(language_code: str):
    """
    Load or retrieve cached alignment model for the given language.
    Returns (model_a, metadata) or (None, None) if unsupported.
    """
    if language_code in _align_models:
        return _align_models[language_code]

    try:
        log.info("Loading alignment model for '%s'...", language_code)
        model_a, metadata = whisperx.load_align_model(
            language_code=language_code,
            device=_device,
        )
        _align_models[language_code] = (model_a, metadata)
        log.info("Alignment model for '%s' ready.", language_code)
        return model_a, metadata
    except Exception as e:
        log.warning(
            "Failed to load alignment model for '%s': %s. "
            "Will use native Whisper word timestamps.",
            language_code, e,
        )
        _align_models[language_code] = (None, None)
        return None, None


# ── Audio extraction (unchanged) ─────────────────────────────────

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


# ── Format conversion helpers ────────────────────────────────────

def _convert_whisperx_segments(segments: list[dict]) -> list[dict]:
    """
    Convert WhisperX output to our canonical format.

    WhisperX words have: {"word": str, "start": float, "end": float, "score": float}
    We need:             {"word": str, "start": float, "end": float}

    Filters out words with missing timestamps (rare after interpolation).
    """
    result = []
    for seg in segments:
        words = []
        for w in seg.get("words", []):
            w_start = w.get("start")
            w_end = w.get("end")
            w_text = w.get("word", "").strip()

            if w_start is None or w_end is None or not w_text:
                continue

            words.append({
                "start": float(w_start),
                "end": float(w_end),
                "word": w_text,
            })

        result.append({
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "text": seg.get("text", "").strip(),
            "words": words,
        })
    return result


# ── Main transcription function ──────────────────────────────────

def transcribe(audio_path: str, language: str = None) -> list[dict]:
    """
    Transcribe an audio file and return timestamped segments
    with force-aligned word timestamps.

    Args:
        audio_path: Path to the WAV audio file.
        language: Language code ('ar', 'en', or None for auto-detect).

    Returns:
        List of dicts: [{"start": float, "end": float, "text": str,
                         "words": [{"start", "end", "word"}, ...]}, ...]
    """
    # Step 1: Load audio as numpy array
    audio = whisperx.load_audio(audio_path)

    # Step 2: Transcribe (batched, with VAD)
    result = _asr_model.transcribe(
        audio,
        batch_size=WHISPERX_BATCH_SIZE,
        language=language,
    )

    detected_language = result.get("language", language or "en")
    raw_segments = result.get("segments", [])

    if not raw_segments:
        return []

    log.info(
        "WhisperX transcription: %d segments, detected language='%s'",
        len(raw_segments), detected_language,
    )

    # Step 3: Forced alignment for precise word timestamps
    model_a, align_metadata = _get_align_model(detected_language)

    if model_a is not None:
        try:
            aligned = whisperx.align(
                raw_segments,
                model_a,
                align_metadata,
                audio,
                _device,
                return_char_alignments=False,
            )
            segments = _convert_whisperx_segments(aligned["segments"])
            log.info("WhisperX alignment successful: %d aligned segments", len(segments))
            return segments

        except Exception as e:
            log.warning(
                "WhisperX alignment failed: %s. Falling back to native timestamps.", e,
            )

    # Fallback: use transcription segments without forced alignment
    if WHISPERX_FALLBACK_TO_NATIVE:
        log.info("Using WhisperX transcription segments without forced alignment.")
        segments = _convert_whisperx_segments(raw_segments)
        return segments

    return _convert_whisperx_segments(raw_segments)
