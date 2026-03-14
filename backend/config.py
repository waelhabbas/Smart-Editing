"""Centralized configuration for Smart Editing backend."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
FRONTEND_DIR = BASE_DIR / "frontend"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Whisper / WhisperX
WHISPER_MODEL = "large-v3"
WHISPERX_BATCH_SIZE = 16              # reduce if low on GPU memory
WHISPERX_FALLBACK_TO_NATIVE = True    # fall back to native word timestamps if alignment fails

# Silence detection defaults
DEFAULT_SILENCE_MS = 500
DEFAULT_PADDING_MS = 150
DEFAULT_SILENCE_THRESH_DB = -40

# SRT
SRT_MAX_WORDS_PER_LINE = 6

# Timeline validation
MIN_CLIP_DURATION_SEC = 0.5

# Video defaults
DEFAULT_TIMEBASE = 30
