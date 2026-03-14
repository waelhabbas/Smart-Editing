"""
Split clips at word gaps using WhisperX word-level timestamps.
Replaces pydub-based silence detection with precise word boundary analysis.
"""

import logging

log = logging.getLogger(__name__)


def _collect_words_in_range(
    segments: list[dict],
    start: float,
    end: float,
    seg_start_idx: int | None = None,
    seg_end_idx: int | None = None,
) -> list[dict]:
    """
    Collect all words from segments whose midpoint falls within [start, end].

    If seg_start_idx and seg_end_idx are provided, only search those segments.
    """
    words = []

    if seg_start_idx is not None and seg_end_idx is not None:
        search_segments = segments[seg_start_idx:seg_end_idx + 1]
    else:
        search_segments = segments

    for seg in search_segments:
        for w in seg.get("words", []):
            w_start = w.get("start")
            w_end = w.get("end")
            if w_start is None or w_end is None:
                continue
            mid = (w_start + w_end) / 2.0
            if start <= mid <= end:
                words.append(w)

    words.sort(key=lambda w: w["start"])
    return words


def split_clips_on_word_gaps(
    clips: list[dict],
    segments: list[dict],
    gap_threshold_ms: int = 500,
    pad_before_ms: int = 50,
    pad_after_ms: int = 50,
) -> list[dict]:
    """
    Split clips at large gaps between words.

    Uses WhisperX word-level timestamps to identify pauses/hesitations
    within each clip and splits the clip into sub-clips around them.

    Args:
        clips: Selected take clips with start, end, shot_number, text.
        segments: Full WhisperX transcription segments with words[].
        gap_threshold_ms: Minimum gap between consecutive words (ms)
            to trigger a split. Default 500ms.
        pad_before_ms: Padding before first word of each sub-clip (ms).
        pad_after_ms: Padding after last word of each sub-clip (ms).

    Returns:
        New list of clips with gaps removed.
    """
    gap_threshold = gap_threshold_ms / 1000.0
    pad_before = pad_before_ms / 1000.0
    pad_after = pad_after_ms / 1000.0

    result = []

    for clip in clips:
        words = _collect_words_in_range(
            segments,
            clip["start"],
            clip["end"],
            clip.get("start_segment_index"),
            clip.get("end_segment_index"),
        )

        if not words:
            result.append(clip.copy())
            log.warning(
                "Shot %s: no words in [%.2f, %.2f], keeping original clip",
                clip.get("shot_number"), clip["start"], clip["end"],
            )
            continue

        # Group words by detecting gaps > threshold
        groups = []
        current_group = [words[0]]

        for i in range(1, len(words)):
            gap = words[i]["start"] - words[i - 1]["end"]
            if gap > gap_threshold:
                groups.append(current_group)
                current_group = [words[i]]
            else:
                current_group.append(words[i])

        groups.append(current_group)

        # Convert word groups to sub-clips
        for group in groups:
            sub_start = max(clip["start"], group[0]["start"] - pad_before)
            sub_end = min(clip["end"], group[-1]["end"] + pad_after)

            if sub_end - sub_start < 0.1:
                continue

            result.append({
                "start": sub_start,
                "end": sub_end,
                "shot_number": clip.get("shot_number"),
                "text": clip.get("text"),
            })

        if len(groups) > 1:
            log.info(
                "Shot %s: split into %d sub-clips (removed %d gap(s) > %dms)",
                clip.get("shot_number"), len(groups),
                len(groups) - 1, gap_threshold_ms,
            )

    return result
