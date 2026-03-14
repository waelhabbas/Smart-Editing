"""Timecode parsing and frame conversion utilities."""

import re


def parse_timecode(tc: str) -> float:
    """
    Parse a timecode string to seconds.

    Supports formats: SS, M:SS, MM:SS, H:MM:SS, HH:MM:SS
    Examples: "5" -> 5.0, "0:05" -> 5.0, "1:30" -> 90.0, "1:02:30" -> 3750.0
    """
    if not tc or not tc.strip():
        return 0.0

    tc = tc.strip()
    parts = tc.split(":")

    if len(parts) == 1:
        return float(parts[0])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    else:
        raise ValueError(f"Invalid timecode format: {tc}")


def seconds_to_frames(seconds: float, timebase: int) -> int:
    """Convert seconds to frame count."""
    return round(seconds * timebase)


def frames_to_seconds(frames: int, timebase: int) -> float:
    """Convert frame count to seconds."""
    return frames / timebase


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timecode_frames(seconds: float, timebase: int = 30) -> str:
    """Convert seconds to timecode format: HH:MM:SS:FF"""
    total_frames = round(seconds * timebase)
    ff = total_frames % timebase
    total_secs = total_frames // timebase
    ss = total_secs % 60
    total_mins = total_secs // 60
    mm = total_mins % 60
    hh = total_mins // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
