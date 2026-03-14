"""
Generate SRT subtitle file with shift awareness.

- Presenter shots: CSV text with Whisper timing (max 6 words/block, 2 lines)
- Soundbite shots: Whisper transcription of soundbite audio
- Accounts for soundbite timeline shifts
- British English spelling rules for English content
"""

import re
import logging
from backend.utils.timecode import format_srt_time
from backend.utils.spelling import apply_british_spelling
from backend.config import SRT_MAX_WORDS_PER_LINE

log = logging.getLogger(__name__)

WORDS_MAX = SRT_MAX_WORDS_PER_LINE


def _clean_text(text: str) -> str:
    """Remove punctuation symbols except period at end of sentences."""
    # Remove all symbols except period and alphanumeric/spaces
    text = re.sub(r'[,;:!?\-\-\"\'\(\)\[\]\{\}#@&\*\+=/\\<>«»""''–—…]', '', text)
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _format_two_lines(words: list[str]) -> str:
    """Format a word list into 2 lines, split at midpoint."""
    if len(words) <= 1:
        return " ".join(words)
    mid = (len(words) + 1) // 2
    line1 = " ".join(words[:mid])
    line2 = " ".join(words[mid:])
    return f"{line1}\n{line2}"


def _chunk_text(text: str, max_words: int = WORDS_MAX) -> list[str]:
    """Split text into subtitle chunks.

    Rules:
    - Max 6 words per chunk, displayed on 2 lines
    - Period ends the current chunk (new chunk starts after)
    - Text is cleaned of symbols (except period)
    """
    text = _clean_text(text)
    if not text:
        return []

    # Split into sentences on period
    sentences = [s.strip() for s in text.split('.') if s.strip()]

    chunks = []
    for i, sentence in enumerate(sentences):
        words = sentence.split()
        if not words:
            continue
        # Add period back to last word of sentence (except if it's the last sentence
        # and original text didn't end with period)
        add_period = text.rstrip().endswith('.') or i < len(sentences) - 1

        for j in range(0, len(words), max_words):
            group = words[j:j + max_words]
            # Add period to the last group of this sentence
            is_last_group = (j + max_words >= len(words))
            if is_last_group and add_period:
                group[-1] = group[-1] + '.'
            chunks.append(_format_two_lines(group))

    return chunks


def _find_words_in_range(segments: list[dict], start: float, end: float) -> list[dict]:
    """Find all Whisper words whose midpoint falls within [start, end]."""
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            mid = (w["start"] + w["end"]) / 2
            if start <= mid <= end:
                words.append(w)
    return words


def _is_english(text: str) -> bool:
    """Check if text is primarily English."""
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return latin > arabic


def generate_srt(
    final_clips: list[dict],
    csv_shots: list[dict],
    segments: list[dict],
    sb_shifts: list[dict],
    sb_transcriptions: dict | None,
    output_path: str,
    language: str | None = None,
) -> str:
    """
    Generate SRT subtitle file accounting for soundbite shifts.

    Args:
        final_clips: Timeline clips with positions.
        csv_shots: CSV shot data (text source for presenter shots).
        segments: Whisper segments with word timestamps.
        sb_shifts: Soundbite shift records [{insertion_point, duration, after_shot, source_in, source_out}].
        sb_transcriptions: {shot_number: [whisper_segments]} for soundbites.
        output_path: Where to save the SRT file.
        language: Language hint.

    Returns:
        Path to the generated SRT file.
    """
    if sb_shifts is None:
        sb_shifts = []
    if sb_transcriptions is None:
        sb_transcriptions = {}

    # Build CSV text lookup
    csv_text_map = {s["shot_number"]: s["text"] for s in csv_shots}
    csv_type_map = {s["shot_number"]: s.get("type", "None") for s in csv_shots}

    entries = []

    # 1. BUILD PRESENTER SUBTITLES - grouped by shot_number to avoid duplicates
    # Include ALL shots (even soundbite-type): the presenter still says the text,
    # the soundbite audio is inserted AFTER on separate tracks.
    shot_clips = {}
    for clip in final_clips:
        shot_num = clip.get("shot_number")
        if shot_num is None:
            continue
        if shot_num not in shot_clips:
            shot_clips[shot_num] = []
        shot_clips[shot_num].append(clip)

    for shot_num, clips in shot_clips.items():
        text = csv_text_map.get(shot_num, "")
        if not text:
            continue

        # Use the full span of all clips for this shot
        tl_start = min(c["timeline_start"] for c in clips)
        tl_end = max(c["timeline_start"] + (c["end"] - c["start"]) for c in clips)
        shot_duration = tl_end - tl_start

        # Collect all Whisper words across all clips, mapped to timeline positions
        all_words = []
        for clip in clips:
            clip_words = _find_words_in_range(segments, clip["start"], clip["end"])
            for w in clip_words:
                tl_word_start = clip["timeline_start"] + (w["start"] - clip["start"])
                tl_word_end = clip["timeline_start"] + (w["end"] - clip["start"])
                all_words.append({"start": tl_word_start, "end": tl_word_end})

        all_words.sort(key=lambda w: w["start"])

        # Split text into chunks of max words, cleaned and formatted
        chunks = _chunk_text(text)
        if not chunks:
            continue

        total_words_in_text = len(_clean_text(text).split())
        word_idx = 0

        for chunk in chunks:
            chunk_word_count = len(chunk.split())

            if all_words and total_words_in_text > 0:
                start_ratio = word_idx / total_words_in_text
                end_ratio = (word_idx + chunk_word_count) / total_words_in_text

                w_start_idx = min(int(start_ratio * len(all_words)), len(all_words) - 1)
                w_end_idx = min(int(end_ratio * len(all_words)), len(all_words) - 1)
                w_end_idx = max(w_end_idx, w_start_idx)

                entry_start = all_words[w_start_idx]["start"]
                entry_end = all_words[w_end_idx]["end"]

                entry_start = max(tl_start, min(entry_start, tl_end))
                entry_end = max(entry_start + 0.1, min(entry_end, tl_end))
            else:
                start_ratio = word_idx / total_words_in_text if total_words_in_text else 0
                end_ratio = (word_idx + chunk_word_count) / total_words_in_text if total_words_in_text else 1
                entry_start = tl_start + start_ratio * shot_duration
                entry_end = tl_start + end_ratio * shot_duration

            entries.append({
                "start": entry_start,
                "end": entry_end,
                "text": chunk,
                "type": "presenter",
            })
            word_idx += chunk_word_count

    # 2. BUILD SOUNDBITE SUBTITLES
    sorted_shifts = sorted(sb_shifts, key=lambda s: s["insertion_point"])

    cumulative_shift = 0.0
    for shift in sorted_shifts:
        shot_num = shift["after_shot"]
        insertion_point = shift["insertion_point"] + cumulative_shift
        sb_duration = shift["duration"]
        source_in = shift.get("source_in", 0.0)
        source_out = shift.get("source_out", source_in + sb_duration)

        sb_segs = sb_transcriptions.get(shot_num, [])
        if sb_segs:
            # Filter words to only those within the cut range [source_in, source_out]
            sb_words = []
            for seg in sb_segs:
                for w in seg.get("words", []):
                    w_mid = (w["start"] + w["end"]) / 2
                    if source_in <= w_mid <= source_out:
                        sb_words.append(w)

            sb_words.sort(key=lambda w: w["start"])

            if sb_words:
                sb_text = " ".join(w["word"].strip() for w in sb_words)
                chunks = _chunk_text(sb_text)

                total_sb_words = len(sb_words)
                w_idx = 0

                for chunk in chunks:
                    chunk_wc = len(chunk.split())

                    # Use actual word timestamps mapped to timeline
                    first_idx = min(w_idx, total_sb_words - 1)
                    last_idx = min(w_idx + chunk_wc - 1, total_sb_words - 1)

                    entry_start = insertion_point + (sb_words[first_idx]["start"] - source_in)
                    entry_end = insertion_point + (sb_words[last_idx]["end"] - source_in)

                    # Clamp to soundbite boundaries
                    entry_start = max(insertion_point, min(entry_start, insertion_point + sb_duration))
                    entry_end = max(entry_start + 0.1, min(entry_end, insertion_point + sb_duration))

                    entries.append({
                        "start": entry_start,
                        "end": entry_end,
                        "text": chunk,
                        "type": "soundbite",
                    })
                    w_idx += chunk_wc

        cumulative_shift += sb_duration

    # 3. APPLY SOUNDBITE SHIFTS to presenter entries
    for entry in entries:
        if entry["type"] == "presenter":
            total_shift = sum(
                s["duration"] for s in sb_shifts
                if s["insertion_point"] <= entry["start"]
            )
            entry["start"] += total_shift
            entry["end"] += total_shift

    # 4. SORT all entries by start time
    entries.sort(key=lambda e: e["start"])

    # 4b. FIX OVERLAPPING TIMESTAMPS - prevent multiple subtitles showing at once
    for i in range(len(entries) - 1):
        if entries[i]["end"] > entries[i + 1]["start"]:
            entries[i]["end"] = entries[i + 1]["start"] - 0.001

    # 4c. Remove entries with invalid timestamps (end <= start)
    entries = [e for e in entries if e["end"] > e["start"]]

    # 5. APPLY BRITISH ENGLISH SPELLING (for English content)
    use_british = (language == "en") if language else (
        any(_is_english(e["text"]) for e in entries[:5]) if entries else False
    )

    if use_british:
        for entry in entries:
            entry["text"] = apply_british_spelling(entry["text"])

    # 6. WRITE SRT
    lines = []
    for i, entry in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{format_srt_time(entry['start'])} --> {format_srt_time(entry['end'])}")
        lines.append(entry["text"])
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info("Generated SRT: %d entries (%d presenter, %d soundbite)",
             len(entries),
             sum(1 for e in entries if e["type"] == "presenter"),
             sum(1 for e in entries if e["type"] == "soundbite"))

    return output_path
