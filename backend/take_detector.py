"""
Detect and select takes by matching transcription segments to script shots.
Uses rapidfuzz for fuzzy text matching with sequential-aware matching.

The reporter reads shots in order (1→2→3...→N) and may repeat the full
sequence multiple times (takes). The algorithm respects this order.
"""

import logging
from rapidfuzz import fuzz

log = logging.getLogger(__name__)


def _score_matrix(segments, shots):
    """Build NxM score matrix: score[i][shot_number] = similarity."""
    shot_texts = {s["shot_number"]: s["text"] for s in shots}
    matrix = []
    for seg in segments:
        scores = {}
        for sn, text in shot_texts.items():
            scores[sn] = fuzz.token_set_ratio(seg["text"], text)
        matrix.append(scores)
    return matrix


def match_segments_sequential(
    segments: list[dict],
    shots: list[dict],
    min_similarity: float = 40.0,
) -> list[dict]:
    """
    Match segments to shots respecting sequential reading order.

    Algorithm:
    - Maintain a cursor for the expected next shot
    - For each segment, find the best match within a forward window
    - If no window match, check for a pass restart (back to shot 1)
    - If neither, leave unmatched
    """
    if not segments or not shots:
        return segments

    shot_numbers = sorted(s["shot_number"] for s in shots)
    num_shots = len(shot_numbers)
    shot_pos = {sn: i for i, sn in enumerate(shot_numbers)}

    # Score all segments against all shots
    scores = _score_matrix(segments, shots)

    WINDOW = max(4, num_shots // 3)  # look-ahead window
    cursor = 0  # current position in shot_numbers (index)

    for i, seg in enumerate(segments):
        seg_scores = scores[i]

        # Find best match within forward window from cursor
        best_shot = None
        best_score = 0

        for offset in range(WINDOW):
            pos = cursor + offset
            if pos >= num_shots:
                break
            sn = shot_numbers[pos]
            sc = seg_scores[sn]
            if sc > best_score:
                best_score = sc
                best_shot = sn

        # Check for new pass restart when past halfway or no good match
        if best_score < min_similarity or cursor > num_shots // 2:
            for restart_pos in range(min(3, num_shots)):
                sn = shot_numbers[restart_pos]
                sc = seg_scores[sn]
                if sc >= 65 and sc > best_score:
                    best_score = sc
                    best_shot = sn
                    log.info("Pass restart at segment %d (%.1fs) -> shot %d (score=%d)",
                             i, seg["start"], sn, sc)

        # Assign
        if best_shot is not None and best_score >= min_similarity:
            seg["matched_shot"] = best_shot
            seg["match_score"] = best_score
            cursor = shot_pos[best_shot] + 1
            if cursor >= num_shots:
                cursor = num_shots  # past end, will trigger restart check
        else:
            seg["matched_shot"] = None
            seg["match_score"] = max(seg_scores.values()) if seg_scores else 0

    return segments


def group_into_takes(segments: list[dict], gap_threshold: float = 2.0) -> list[dict]:
    """
    Group consecutive segments matching the same shot into takes.
    """
    if not segments:
        return []

    takes = []
    current_shot = segments[0].get("matched_shot")
    current_start = segments[0]["start"]
    current_end = segments[0]["end"]
    current_segments = [segments[0]]

    def save_current():
        if current_shot is not None:
            takes.append({
                "shot_number": current_shot,
                "start": current_start,
                "end": current_end,
                "segments": list(current_segments),
            })

    for seg in segments[1:]:
        shot = seg.get("matched_shot")
        gap = seg["start"] - current_end

        if shot == current_shot and shot is not None and gap < gap_threshold:
            current_end = seg["end"]
            current_segments.append(seg)
        else:
            save_current()
            current_shot = shot
            current_start = seg["start"]
            current_end = seg["end"]
            current_segments = [seg]

    save_current()
    return takes


def select_last_takes(takes: list[dict]) -> list[dict]:
    """
    For each shot, select the last take (final attempt).
    Returns list ordered by shot number.
    """
    last_takes = {}
    take_counts = {}

    for take in takes:
        shot_num = take["shot_number"]
        last_takes[shot_num] = take
        take_counts[shot_num] = take_counts.get(shot_num, 0) + 1

    result = []
    for shot_num in sorted(last_takes.keys()):
        take = last_takes[shot_num]
        take["total_takes"] = take_counts[shot_num]
        result.append(take)

    return result


def detect_takes(
    segments: list[dict],
    shots: list[dict],
    min_similarity: float = 40.0,
) -> dict:
    """
    Full pipeline: match segments to shots, group into takes, select last takes.
    """
    matched = match_segments_sequential(segments, shots, min_similarity)

    matched_count = sum(1 for s in matched if s.get("matched_shot") is not None)
    log.info("Matching: %d/%d segments matched", matched_count, len(matched))

    all_takes = group_into_takes(matched)
    log.info("Grouped into %d takes", len(all_takes))

    selected = select_last_takes(all_takes)
    log.info("Selected %d final takes (from %d shots)", len(selected), len(shots))

    summary = {}
    for take in all_takes:
        shot_num = take["shot_number"]
        if shot_num not in summary:
            summary[shot_num] = {"total_takes": 0, "selected_start": 0, "selected_end": 0}
        summary[shot_num]["total_takes"] += 1

    for take in selected:
        shot_num = take["shot_number"]
        summary[shot_num]["selected_start"] = take["start"]
        summary[shot_num]["selected_end"] = take["end"]

    return {
        "selected_takes": selected,
        "all_takes": all_takes,
        "summary": summary,
    }
