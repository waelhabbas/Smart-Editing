"""
Match target Arabic words from B-Roll instructions against Whisper
word-level timestamps to find exact timeline positions.
"""

import re
import logging
from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for fuzzy matching."""
    # Remove diacritics (tashkeel)
    text = re.sub(
        r'[\u0610-\u061A\u064B-\u065F\u0670'
        r'\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]',
        '', text,
    )
    # Normalize alef variants to plain alef
    text = re.sub(r'[إأآا]', 'ا', text)
    # Normalize taa marbuta to haa
    text = text.replace('ة', 'ه')
    # Normalize yaa variants
    text = text.replace('ى', 'ي')
    # Remove tatweel (kashida)
    text = text.replace('\u0640', '')
    return text.strip()


def _build_word_list(segments: list[dict]) -> list[dict]:
    """Build a flat list of all words with their source timestamps."""
    all_words = []
    for seg in segments:
        for w in seg.get("words", []):
            all_words.append({
                "word": w["word"],
                "normalized": normalize_arabic(w["word"]),
                "start": w["start"],
                "end": w["end"],
            })
    return all_words


def find_word_on_timeline(
    target_word: str,
    segments: list[dict],
    final_clips: list[dict],
    min_score: int = 55,
) -> dict | None:
    """
    Find where a target word appears on the final TIMELINE.

    Maps the word's source timestamp to the accumulated timeline position
    by checking which final_clip contains it.

    Args:
        target_word: The Arabic word to search for.
        segments: Whisper segments with word-level timestamps.
        final_clips: Clips with timeline_start/timeline_end fields.
        min_score: Minimum fuzzy match score (0-100).

    Returns:
        {
            "timeline_position": float,
            "word_duration": float,
            "source_position": float,
            "matched_word": str,
            "confidence": float,
        }
        or None if not found.
    """
    normalized_target = normalize_arabic(target_word)
    all_words = _build_word_list(segments)

    log.info("Looking for word '%s' (normalized: '%s') in %d words from %d segments",
             target_word, normalized_target, len(all_words), len(segments))

    if not all_words:
        log.warning("No words found in segments")
        return None

    word_texts = [w["normalized"] for w in all_words]
    matches = process.extract(
        normalized_target,
        word_texts,
        scorer=fuzz.ratio,
        limit=10,
        score_cutoff=min_score,
    )

    if not matches:
        # Show best matches even below threshold for debugging
        debug_matches = process.extract(normalized_target, word_texts, scorer=fuzz.ratio, limit=3)
        log.warning("No fuzzy match found for '%s' (threshold=%d). Best matches: %s",
                     target_word, min_score,
                     [(all_words[idx]["word"], score) for _, score, idx in debug_matches])
        return None

    log.info("Fuzzy matches for '%s': %s",
             target_word,
             [(all_words[idx]["word"], round(score, 1), round(all_words[idx]["start"], 2))
              for _, score, idx in matches])

    # Try each match in order of score until one falls within a selected clip
    for matched_text, score, idx in matches:
        matched = all_words[idx]
        source_time = matched["start"]

        for clip in final_clips:
            if clip["start"] <= source_time <= clip["end"]:
                offset = source_time - clip["start"]
                result = {
                    "timeline_position": clip["timeline_start"] + offset,
                    "word_duration": matched["end"] - matched["start"],
                    "source_position": source_time,
                    "matched_word": matched["word"],
                    "confidence": score,
                }
                log.info("MATCH FOUND: '%s' -> '%s' at timeline %.2fs (source %.2fs, clip %.2f-%.2f)",
                         target_word, matched["word"], result["timeline_position"],
                         source_time, clip["start"], clip["end"])
                return result

        log.debug("Word '%s' at source %.2fs not in any final clip", matched["word"], source_time)

    # Log why no clip contained the matched words
    log.warning("Word '%s' matched in segments but NOT in any final_clip. "
                "Matched timestamps: %s. Clip ranges: %s",
                target_word,
                [round(all_words[idx]["start"], 2) for _, _, idx in matches],
                [(round(c["start"], 2), round(c["end"], 2)) for c in final_clips])
    return None


def find_paragraph_span(
    target_word: str,
    segments: list[dict],
    final_clips: list[dict],
    min_score: int = 55,
) -> dict | None:
    """
    Find the full paragraph/shot span for a target word on the timeline.

    Used for "full" mode where B-Roll covers the entire paragraph.

    Returns:
        {
            "timeline_start": float,
            "timeline_end": float,
            "duration": float,
            "shot_number": int,
            "word_match": dict,
        }
        or None if not found.
    """
    word_match = find_word_on_timeline(target_word, segments, final_clips, min_score)
    if not word_match:
        return None

    source_time = word_match["source_position"]

    # Find the shot_number of the clip containing this word
    target_shot = None
    for clip in final_clips:
        if clip["start"] <= source_time <= clip["end"]:
            target_shot = clip.get("shot_number")
            break

    if target_shot is None:
        return None

    # Find all clips belonging to this shot and compute their timeline span
    para_start = None
    para_end = None
    for clip in final_clips:
        if clip.get("shot_number") == target_shot:
            if para_start is None:
                para_start = clip["timeline_start"]
            para_end = clip["timeline_end"]

    if para_start is None:
        return None

    return {
        "timeline_start": para_start,
        "timeline_end": para_end,
        "duration": para_end - para_start,
        "shot_number": target_shot,
        "word_match": word_match,
    }
