"""
Generate SRT subtitle file from clips.

Two modes:
- Without script: uses Whisper word timestamps for text and timing.
- With script: uses script-based clean text with proportional timing.

Each subtitle line contains 5-7 words synchronized with speech.
"""

WORDS_MIN = 5
WORDS_MAX = 7


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _chunk_words(words: list, min_size: int = WORDS_MIN,
                 max_size: int = WORDS_MAX) -> list[list]:
    """Split a list into chunks of min_size to max_size items."""
    if not words:
        return []

    n = len(words)
    if n <= max_size:
        return [words]

    # Calculate number of chunks so each is between min and max
    target = (min_size + max_size) / 2
    num_chunks = max(1, round(n / target))

    # Distribute evenly
    chunk_size = n // num_chunks
    remainder = n % num_chunks

    chunks = []
    i = 0
    for c in range(num_chunks):
        size = chunk_size + (1 if c < remainder else 0)
        chunks.append(words[i:i + size])
        i += size

    return chunks


def generate_srt(clips: list[dict], output_path: str,
                 segments: list[dict] = None,
                 use_script_text: bool = False) -> str:
    """
    Generate SRT subtitle file from timeline clips.

    Args:
        clips: List of clips [{"start", "end", "shot_number", "text"}, ...]
        output_path: Where to save the SRT file.
        segments: Whisper segments with word-level timestamps.
        use_script_text: If True, use clip's text (from script) instead of
                         Whisper output. Timing is distributed proportionally.

    Returns:
        Path to the generated SRT file.
    """
    entries = []
    timeline_pos = 0.0

    if use_script_text:
        # --- Case 2: Script provided ---
        # Use clip's text (clean_text from Gemini/script), proportional timing
        for clip in clips:
            clip_duration = clip["end"] - clip["start"]
            text = clip.get("text", "")

            if text:
                words = text.split()
                if words:
                    chunks = _chunk_words(words)
                    n_words = len(words)
                    word_idx = 0

                    for chunk in chunks:
                        start_ratio = word_idx / n_words
                        end_ratio = (word_idx + len(chunk)) / n_words

                        entries.append({
                            "start": timeline_pos + start_ratio * clip_duration,
                            "end": timeline_pos + end_ratio * clip_duration,
                            "text": " ".join(chunk),
                        })
                        word_idx += len(chunk)

            timeline_pos += clip_duration

    else:
        # --- Case 1: No script ---
        # Use Whisper word timestamps for text and accurate timing
        all_words = []
        if segments:
            for seg in segments:
                for w in seg.get("words", []):
                    all_words.append(w)

        for clip in clips:
            clip_duration = clip["end"] - clip["start"]

            # Find words whose midpoint falls in this clip's source range
            clip_words = []
            for w in all_words:
                w_mid = (w["start"] + w["end"]) / 2
                if clip["start"] <= w_mid <= clip["end"]:
                    clip_words.append(w)

            if clip_words:
                chunks = _chunk_words(clip_words)

                for chunk in chunks:
                    # Use actual word timestamps, offset to timeline position
                    entry_start = timeline_pos + (chunk[0]["start"] - clip["start"])
                    entry_end = timeline_pos + (chunk[-1]["end"] - clip["start"])

                    # Clamp to clip boundaries
                    entry_start = max(timeline_pos, entry_start)
                    entry_end = min(timeline_pos + clip_duration, entry_end)

                    text = " ".join(w["word"] for w in chunk)
                    entries.append({
                        "start": entry_start,
                        "end": entry_end,
                        "text": text.strip(),
                    })

            timeline_pos += clip_duration

    # Write SRT
    lines = []
    for i, entry in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(
            f"{_format_srt_time(entry['start'])} --> {_format_srt_time(entry['end'])}"
        )
        lines.append(entry["text"])
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_path
