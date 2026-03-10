"""
Detect and remove silence periods from audio/video segments.
Uses pydub for audio analysis.
"""

from pydub import AudioSegment
from pydub.silence import detect_silence


def detect_silences(
    audio_path: str,
    min_silence_ms: int = 500,
    silence_thresh_db: int = -40,
) -> list[dict]:
    """
    Detect silence periods in an audio file.

    Args:
        audio_path: Path to audio file (wav/mp3).
        min_silence_ms: Minimum silence duration in milliseconds to detect.
        silence_thresh_db: Silence threshold in dBFS.

    Returns:
        List of dicts: [{"start": float, "end": float}, ...] in seconds.
    """
    audio = AudioSegment.from_file(audio_path)

    # detect_silence returns list of [start_ms, end_ms]
    silent_ranges = detect_silence(
        audio,
        min_silence_len=min_silence_ms,
        silence_thresh=silence_thresh_db,
    )

    return [
        {"start": start / 1000.0, "end": end / 1000.0}
        for start, end in silent_ranges
    ]


def remove_silences_from_segments(
    segments: list[dict],
    silences: list[dict],
    padding_ms: int = 150,
) -> list[dict]:
    """
    Remove silence periods from a list of timeline segments.

    Each segment has {"start": float, "end": float} in seconds.
    Silences are subtracted from segments, splitting them if needed.

    Args:
        segments: List of clip segments on the timeline.
        silences: List of detected silence periods.
        padding_ms: Keep this much silence at edges (milliseconds).

    Returns:
        New list of segments with silences removed.
    """
    padding = padding_ms / 1000.0
    result = []

    for seg in segments:
        # Collect silences that overlap with this segment
        relevant_silences = []
        for sil in silences:
            # Add padding: shrink silence boundaries
            sil_start = sil["start"] + padding
            sil_end = sil["end"] - padding
            if sil_start >= sil_end:
                continue  # padding eliminated this silence

            # Check overlap with segment
            if sil_start < seg["end"] and sil_end > seg["start"]:
                relevant_silences.append({
                    "start": max(sil_start, seg["start"]),
                    "end": min(sil_end, seg["end"]),
                })

        if not relevant_silences:
            result.append(seg.copy())
            continue

        # Sort silences by start time
        relevant_silences.sort(key=lambda s: s["start"])

        # Split segment around silences
        current_start = seg["start"]
        for sil in relevant_silences:
            if current_start < sil["start"]:
                result.append({
                    "start": current_start,
                    "end": sil["start"],
                    "shot_number": seg.get("shot_number"),
                    "text": seg.get("text"),
                })
            current_start = sil["end"]

        # Remaining part after last silence
        if current_start < seg["end"]:
            result.append({
                "start": current_start,
                "end": seg["end"],
                "shot_number": seg.get("shot_number"),
                "text": seg.get("text"),
            })

    return result
