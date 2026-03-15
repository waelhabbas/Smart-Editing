"""
Match CSV shot text against Whisper transcription to find timeline positions.
Uses sliding window fuzzy matching to locate where each shot's text was spoken.

Pipeline:
  1. Sliding window match (variable size) → find candidate takes
  2. Verify each take → compare actual Whisper words against script
  3. Pickup fallback → split incomplete takes into two parts from different takes
"""

import re
import logging
from rapidfuzz import fuzz, process
from backend.utils.text_normalize import normalize_arabic, normalize_text

log = logging.getLogger(__name__)

# Thresholds
VERIFY_THRESHOLD = 90       # Score above this = complete take, no pickup needed
PICKUP_MIN_SCORE = 65       # Minimum score for each pickup part
MIN_SPLIT_WORDS = 4         # Each part of a split must have at least this many words


def _build_word_list(segments: list[dict]) -> list[dict]:
    """Build a flat list of all words with their source timestamps."""
    all_words = []
    for seg in segments:
        for w in seg.get("words", []):
            all_words.append({
                "word": w["word"],
                "start": w["start"],
                "end": w["end"],
            })
    return all_words


def _detect_language(text: str) -> str:
    """Simple language detection based on character ranges."""
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    latin_chars = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    return "ar" if arabic_chars > latin_chars else "en"


def find_shot_on_timeline(
    shot_text: str,
    all_words: list[dict],
    min_score: int = 50,
) -> list[dict]:
    """
    Find all occurrences (takes) of a shot's text in the word list.

    Uses a sliding window approach where the window size matches
    the word count of the shot text.

    Args:
        shot_text: The text of the shot from CSV.
        all_words: Flat list of words with timestamps.
        min_score: Minimum fuzzy match score (0-100).

    Returns:
        List of take candidates: [{"start", "end", "score"}, ...]
        sorted by start time.
    """
    if not shot_text or not all_words:
        return []

    lang = _detect_language(shot_text)
    shot_words = shot_text.split()
    window_size = len(shot_words)

    if window_size == 0:
        return []

    # Normalize shot text
    normalized_shot = normalize_text(shot_text, lang)

    # Build sliding windows
    windows = []
    for i in range(len(all_words) - window_size + 1):
        window_words = all_words[i:i + window_size]
        phrase = " ".join(w["word"] for w in window_words)
        normalized_phrase = normalize_text(phrase, lang)
        windows.append({
            "text": normalized_phrase,
            "start": window_words[0]["start"],
            "end": window_words[-1]["end"],
            "idx": i,
        })

    if not windows:
        return []

    # Score all windows
    scored = []
    for w in windows:
        score = fuzz.token_set_ratio(normalized_shot, w["text"])
        if score >= min_score:
            scored.append({
                "start": w["start"],
                "end": w["end"],
                "score": score,
                "idx": w["idx"],
            })

    if not scored:
        return []

    # Group overlapping/adjacent high-scoring windows into take candidates
    scored.sort(key=lambda x: x["start"])
    takes = []
    current_take = None

    for s in scored:
        if current_take is None:
            current_take = {
                "start": s["start"],
                "end": s["end"],
                "score": s["score"],
            }
        elif s["start"] <= current_take["end"] + 2.0:
            # Overlapping or close - extend current take
            current_take["end"] = max(current_take["end"], s["end"])
            current_take["score"] = max(current_take["score"], s["score"])
        else:
            # Gap - new take
            takes.append(current_take)
            current_take = {
                "start": s["start"],
                "end": s["end"],
                "score": s["score"],
            }

    if current_take:
        takes.append(current_take)

    return takes


def match_shots_to_transcript(
    csv_shots: list[dict],
    segments: list[dict],
    min_score: int = 50,
) -> dict:
    """
    Match all CSV shots against Whisper transcript to find take candidates.

    Args:
        csv_shots: List of shot dicts from CSV parser.
        segments: Whisper transcription segments with word timestamps.
        min_score: Minimum fuzzy match score.

    Returns:
        Dict mapping shot_number to list of take candidates.
        {1: [{"start": 0.0, "end": 5.3, "score": 87}, ...], ...}
    """
    all_words = _build_word_list(segments)
    log.info("Built word list: %d words from %d segments", len(all_words), len(segments))

    shot_takes = {}
    for shot in csv_shots:
        shot_num = shot["shot_number"]
        text = shot.get("text", "")
        if not text:
            shot_takes[shot_num] = []
            continue

        takes = find_shot_on_timeline(text, all_words, min_score)
        shot_takes[shot_num] = takes
        log.info("Shot %d: found %d take(s) - %s",
                 shot_num, len(takes),
                 [(round(t["start"], 1), round(t["end"], 1), round(t["score"], 0)) for t in takes])

    return shot_takes


def _get_words_in_range(all_words: list[dict], start: float, end: float) -> str:
    """Get concatenated Whisper words within a time range."""
    return " ".join(
        w["word"] for w in all_words
        if w["start"] is not None and start - 0.05 <= w["start"] <= end + 0.05
    )


def _verify_clip(
    clip_start: float,
    clip_end: float,
    expected_text: str,
    all_words: list[dict],
    lang: str,
) -> float:
    """
    Verify a clip by comparing actual Whisper words in the clip range
    against the expected script text.

    Returns fuzz.ratio score (0-100).
    """
    actual = _get_words_in_range(all_words, clip_start, clip_end)
    if not actual:
        return 0.0
    norm_expected = normalize_text(expected_text, lang)
    norm_actual = normalize_text(actual, lang)
    return fuzz.ratio(norm_expected, norm_actual)


def _find_split_points(text: str) -> list[tuple[str, str]]:
    """
    Find natural sentence boundaries to split text into two parts.

    Tries multiple patterns:
    1. Period/question mark followed by space (sentence boundary)
    2. Comma + and/or (clause boundary)
    3. Quote + and (e.g., violence' and which)

    Returns list of (part1, part2) tuples, each part >= MIN_SPLIT_WORDS words.
    """
    splits = []

    # Pattern 1: Sentence boundaries (. ? !)
    for m in re.finditer(r'[.?!]\s+', text):
        _add_split(splits, text, m.end())

    # Pattern 2: ", and " or ", or " clause boundaries
    for m in re.finditer(r',\s+(?:and|or)\s+', text, re.IGNORECASE):
        _add_split(splits, text, m.start() + 1)  # split after comma

    # Pattern 3: Quote + and (e.g., violence' and)
    for m in re.finditer(r"['\u2019\u201D]\s+and\s+", text, re.IGNORECASE):
        _add_split(splits, text, m.end())

    # Pattern 4: Comma-separated clauses (split at comma + space)
    # More aggressive — tries every comma as a potential pickup point
    for m in re.finditer(r',\s+', text):
        _add_split(splits, text, m.end())

    return splits


def _add_split(splits: list, text: str, pos: int):
    """Helper to add a valid split point."""
    part1 = text[:pos].strip()
    part2 = text[pos:].strip()
    if part1 and part2:
        w1 = len(part1.split())
        w2 = len(part2.split())
        if w1 >= MIN_SPLIT_WORDS and w2 >= MIN_SPLIT_WORDS:
            splits.append((part1, part2))


def _find_best_match(
    text: str,
    all_words: list[dict],
    lang: str,
    min_score: int,
    max_gap_sec: float,
    search_after: float = 0.0,
) -> list[dict]:
    """
    Core sliding window matching with variable window sizes.

    Returns grouped peaks (one per distinct take), filtered to start
    after search_after, sorted by start time.
    """
    shot_words = text.split()
    base_size = len(shot_words)
    if base_size == 0:
        return []

    normalized_shot = normalize_text(text, lang)

    min_win = max(1, base_size - 2)
    max_win = base_size + 5
    candidates = []

    for window_size in range(min_win, max_win + 1):
        if window_size > len(all_words):
            break

        for i in range(len(all_words) - window_size + 1):
            window = all_words[i:i + window_size]

            # Skip windows that start before search_after
            if window[0]["start"] < search_after - 0.5:
                continue

            # Quality check: reject windows with any word gap > max_gap_sec
            has_long_gap = False
            for j in range(1, len(window)):
                gap = window[j]["start"] - window[j - 1]["end"]
                if gap > max_gap_sec:
                    has_long_gap = True
                    break
            if has_long_gap:
                continue

            phrase = " ".join(w["word"] for w in window)
            normalized_phrase = normalize_text(phrase, lang)
            score = fuzz.ratio(normalized_shot, normalized_phrase)

            if score >= min_score:
                candidates.append({
                    "start": window[0]["start"],
                    "end": window[-1]["end"],
                    "score": score,
                    "idx": i,
                    "window_size": window_size,
                })

    if not candidates:
        return []

    # Group nearby candidates and find the PEAK (best score) per group
    candidates.sort(key=lambda x: x["start"])
    peaks = []
    current_group = [candidates[0]]

    for c in candidates[1:]:
        if c["start"] <= current_group[-1]["end"] + 2.0:
            current_group.append(c)
        else:
            best = max(current_group, key=lambda x: x["score"])
            peaks.append(best)
            current_group = [c]

    best = max(current_group, key=lambda x: x["score"])
    peaks.append(best)

    return peaks


def _try_pickup(
    text: str,
    all_words: list[dict],
    lang: str,
    min_score: int,
    max_gap_sec: float,
    search_after: float,
) -> list[dict] | None:
    """
    Try to construct a complete reading from two separate parts (pickup).

    When the reporter didn't finish a shot in one take, they often
    re-read just the ending later. This function:
    1. Finds natural split points in the text
    2. Matches each part independently
    3. Returns two clips if a valid pickup is found

    Returns list of 2 clips if successful, None if no valid pickup found.
    """
    split_points = _find_split_points(text)
    if not split_points:
        return None

    best_pickup = None
    best_avg_score = 0.0

    for part1_text, part2_text in split_points:
        # Find best match for part 1
        part1_peaks = _find_best_match(
            part1_text, all_words, lang, PICKUP_MIN_SCORE, max_gap_sec,
            search_after=search_after,
        )
        if not part1_peaks:
            continue

        for p1 in part1_peaks:
            # Verify part 1
            p1_verify = _verify_clip(p1["start"], p1["end"], part1_text, all_words, lang)
            if p1_verify < PICKUP_MIN_SCORE:
                continue

            # Find best match for part 2, searching AFTER part 1
            part2_peaks = _find_best_match(
                part2_text, all_words, lang, PICKUP_MIN_SCORE, max_gap_sec,
                search_after=p1["end"] - 0.5,
            )
            if not part2_peaks:
                continue

            for p2 in part2_peaks:
                # Part 2 must start after part 1 ends
                if p2["start"] < p1["end"] - 0.5:
                    continue

                p2_verify = _verify_clip(p2["start"], p2["end"], part2_text, all_words, lang)
                if p2_verify < PICKUP_MIN_SCORE:
                    continue

                avg_score = (p1_verify + p2_verify) / 2.0

                if avg_score > best_avg_score:
                    best_avg_score = avg_score
                    best_pickup = (
                        {**p1, "score": p1_verify, "text_part": part1_text},
                        {**p2, "score": p2_verify, "text_part": part2_text},
                    )

    if best_pickup is None:
        return None

    p1, p2 = best_pickup
    log.info("  Pickup found: [%.2f-%.2f] score=%d + [%.2f-%.2f] score=%d (avg=%.0f)",
             p1["start"], p1["end"], p1["score"],
             p2["start"], p2["end"], p2["score"], best_avg_score)
    return [p1, p2]


def select_takes_by_text(
    csv_shots: list[dict],
    segments: list[dict],
    min_score: int = 60,
    max_gap_sec: float = 3.0,
) -> list[dict]:
    """
    Select the best take per shot using direct text matching with
    verification and pickup fallback.

    Pipeline for each shot:
      1. Find all candidate takes using sliding window (variable size)
      2. Select the last valid take (reporter improves over time)
      3. Verify: compare actual Whisper words in clip range vs script
      4. If verified (score >= 90): use as-is
      5. If incomplete (score < 90): try pickup (split into two parts)
      6. If pickup fails: fall back to best single take

    Args:
        csv_shots: Parsed CSV shots with shot_number and text.
        segments: WhisperX transcription segments with word timestamps.
        min_score: Minimum fuzzy match score for initial window matching.
        max_gap_sec: Maximum gap between consecutive words in a window.

    Returns:
        List of clips sorted by start time. Incomplete shots may produce
        two clips (pickup parts) with the same shot_number.
    """
    all_words = _build_word_list(segments)
    if not all_words:
        return []

    log.info("Text-based take selection: %d words from %d segments",
             len(all_words), len(segments))

    selected_clips = []
    last_end = 0.0

    for shot in csv_shots:
        text = shot.get("text", "").replace("\n", " ").strip()
        shot_num = shot["shot_number"]

        if not text:
            continue

        lang = _detect_language(text)

        if len(text.split()) == 0:
            continue

        # Step 1: Find all candidate takes (full text)
        peaks = _find_best_match(
            text, all_words, lang, min_score, max_gap_sec,
            search_after=0.0,
        )

        if not peaks:
            log.warning("Shot %d: no text match found (min_score=%d)", shot_num, min_score)
            continue

        # Step 2: Filter to takes after previous shot's end
        valid_takes = [t for t in peaks if t["start"] >= last_end - 0.5]
        if not valid_takes:
            valid_takes = peaks
            log.warning("Shot %d: no takes after %.2fs, using best available", shot_num, last_end)

        # Select the LAST valid take (reporter usually improves)
        selected = valid_takes[-1]

        # Step 3: Verify — compare actual Whisper words vs script
        verify_score = _verify_clip(
            selected["start"], selected["end"], text, all_words, lang,
        )

        # Step 4: If verified, use as-is
        if verify_score >= VERIFY_THRESHOLD:
            selected_clips.append({
                "start": selected["start"],
                "end": selected["end"],
                "shot_number": shot_num,
                "text": text,
                "score": verify_score,
            })
            last_end = selected["end"]
            log.info("Shot %d: VERIFIED [%.2f-%.2f] (%.1fs, score=%d, %d take(s))",
                     shot_num, selected["start"], selected["end"],
                     selected["end"] - selected["start"],
                     verify_score, len(peaks))
            continue

        # Step 5: Incomplete — try pickup (two-part split)
        log.info("Shot %d: verify_score=%d < %d, trying pickup...",
                 shot_num, verify_score, VERIFY_THRESHOLD)

        pickup = _try_pickup(
            text, all_words, lang, min_score, max_gap_sec,
            search_after=last_end - 0.5,
        )

        if pickup:
            for part in pickup:
                selected_clips.append({
                    "start": part["start"],
                    "end": part["end"],
                    "shot_number": shot_num,
                    "text": part.get("text_part", text),
                    "score": part["score"],
                })
            last_end = pickup[-1]["end"]
            log.info("Shot %d: PICKUP [%.2f-%.2f]+[%.2f-%.2f] (scores=%d+%d, %d take(s))",
                     shot_num, pickup[0]["start"], pickup[0]["end"],
                     pickup[1]["start"], pickup[1]["end"],
                     pickup[0]["score"], pickup[1]["score"], len(peaks))
        else:
            # Step 6: Pickup failed — fall back to best single take
            selected_clips.append({
                "start": selected["start"],
                "end": selected["end"],
                "shot_number": shot_num,
                "text": text,
                "score": verify_score,
            })
            last_end = selected["end"]
            log.info("Shot %d: FALLBACK [%.2f-%.2f] (%.1fs, score=%d, no valid pickup)",
                     shot_num, selected["start"], selected["end"],
                     selected["end"] - selected["start"],
                     verify_score, )

    return selected_clips


def find_word_on_timeline(
    target_word: str,
    segments: list[dict],
    final_clips: list[dict],
    min_score: int = 55,
) -> dict | None:
    """
    Find where a target word/phrase appears on the final timeline.

    Args:
        target_word: The word or phrase to search for.
        segments: Whisper segments with word-level timestamps.
        final_clips: Clips with timeline_start/timeline_end fields.
        min_score: Minimum fuzzy match score.

    Returns:
        {"timeline_position", "word_duration", "source_position", "matched_word", "confidence"}
        or None if not found.
    """
    all_words = _build_word_list(segments)
    if not all_words:
        return None

    lang = _detect_language(target_word)
    target_tokens = target_word.strip().split()

    if len(target_tokens) <= 1:
        # Single word matching
        normalized_target = normalize_text(target_word, lang)
        word_texts = [normalize_text(w["word"], lang) for w in all_words]
        matches = process.extract(
            normalized_target, word_texts,
            scorer=fuzz.ratio, limit=10, score_cutoff=min_score,
        )
        if not matches:
            return None

        for _, score, idx in matches:
            matched = all_words[idx]
            source_time = matched["start"]
            for clip in final_clips:
                if clip["start"] <= source_time <= clip["end"]:
                    offset = source_time - clip["start"]
                    return {
                        "timeline_position": clip["timeline_start"] + offset,
                        "word_duration": matched["end"] - matched["start"],
                        "source_position": source_time,
                        "matched_word": matched["word"],
                        "confidence": score,
                    }
    else:
        # Multi-word phrase - sliding window
        window_size = len(target_tokens)
        normalized_target = normalize_text(target_word, lang)

        for i in range(len(all_words) - window_size + 1):
            phrase_words = all_words[i:i + window_size]
            phrase_text = " ".join(w["word"] for w in phrase_words)
            normalized_phrase = normalize_text(phrase_text, lang)

            score = fuzz.token_set_ratio(normalized_target, normalized_phrase)
            if score >= min_score:
                source_time = phrase_words[0]["start"]
                for clip in final_clips:
                    if clip["start"] <= source_time <= clip["end"]:
                        offset = source_time - clip["start"]
                        return {
                            "timeline_position": clip["timeline_start"] + offset,
                            "word_duration": phrase_words[-1]["end"] - phrase_words[0]["start"],
                            "source_position": source_time,
                            "matched_word": phrase_text,
                            "confidence": score,
                        }

    return None


def find_shot_span(
    shot_number: int,
    final_clips: list[dict],
) -> dict | None:
    """
    Find the timeline span for a given shot number.

    Returns:
        {"timeline_start", "timeline_end", "duration",
         "timeline_start_frames", "timeline_end_frames"} or None.
    """
    start = None
    end = None
    start_frames = None
    end_frames = None
    for clip in final_clips:
        if clip.get("shot_number") == shot_number:
            if start is None:
                start = clip["timeline_start"]
                start_frames = clip.get("timeline_start_frames")
            end = clip["timeline_end"]
            end_frames = clip.get("timeline_end_frames")

    if start is None:
        return None

    result = {
        "timeline_start": start,
        "timeline_end": end,
        "duration": end - start,
    }
    if start_frames is not None:
        result["timeline_start_frames"] = start_frames
    if end_frames is not None:
        result["timeline_end_frames"] = end_frames
    return result
