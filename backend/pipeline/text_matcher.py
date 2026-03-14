"""
Match CSV shot text against Whisper transcription to find timeline positions.
Uses sliding window fuzzy matching to locate where each shot's text was spoken.
"""

import logging
from rapidfuzz import fuzz, process
from backend.utils.text_normalize import normalize_arabic, normalize_text

log = logging.getLogger(__name__)


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
