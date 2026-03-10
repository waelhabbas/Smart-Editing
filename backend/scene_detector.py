"""
Auto-detect scenes and takes from transcription segments and silence gaps.
No script needed - detects repeated readings by comparing text similarity.

The reporter reads each paragraph multiple times consecutively (takes),
then moves to the next paragraph. Scenes are separated by longer silence gaps.
"""

import logging
from rapidfuzz import fuzz

log = logging.getLogger(__name__)


def _group_into_readings(segments: list[dict], silences: list[dict], gap: float = 3.0) -> list[dict]:
    """
    Group transcription segments into "readings" separated by silence gaps.

    A reading = one continuous speech block (one take of one paragraph).
    Readings are separated by silence periods longer than `gap` seconds.

    Returns:
        List of readings: [{"start": float, "end": float, "text": str, "segments": [...]}]
    """
    if not segments:
        return []

    # Build a set of silence boundaries for quick lookup
    silence_gaps = []
    for sil in silences:
        duration = sil["end"] - sil["start"]
        if duration >= gap:
            silence_gaps.append(sil)

    readings = []
    current_segments = [segments[0]]

    for seg in segments[1:]:
        # Check if there's a significant silence gap between this and previous segment
        prev_end = current_segments[-1]["end"]
        has_gap = False

        for sil in silence_gaps:
            if sil["start"] >= prev_end - 0.1 and sil["end"] <= seg["start"] + 0.1:
                has_gap = True
                break

        # Also check raw time gap between segments
        if seg["start"] - prev_end >= gap:
            has_gap = True

        if has_gap:
            # Save current reading
            combined_text = " ".join(s["text"] for s in current_segments)
            readings.append({
                "start": current_segments[0]["start"],
                "end": current_segments[-1]["end"],
                "text": combined_text,
                "segments": list(current_segments),
            })
            current_segments = [seg]
        else:
            current_segments.append(seg)

    # Save last reading
    if current_segments:
        combined_text = " ".join(s["text"] for s in current_segments)
        readings.append({
            "start": current_segments[0]["start"],
            "end": current_segments[-1]["end"],
            "text": combined_text,
            "segments": list(current_segments),
        })

    return readings


def _split_long_readings(readings: list[dict], max_duration: float = 40.0,
                         similarity_threshold: float = 60.0) -> list[dict]:
    """
    Split readings that are too long (contain multiple takes merged together).

    Strategy: for long readings, compare each segment with the first segment.
    When similarity is high again after dropping, it means the reporter restarted
    reading the same paragraph = new take boundary.
    """
    result = []

    for reading in readings:
        duration = reading["end"] - reading["start"]

        # Short enough - keep as is
        if duration <= max_duration or len(reading["segments"]) < 3:
            result.append(reading)
            continue

        # Long reading - try to find internal take boundaries
        segs = reading["segments"]
        sub_readings = _find_take_boundaries(segs, similarity_threshold)
        result.extend(sub_readings)

    return result


def _find_take_boundaries(segments: list[dict], similarity_threshold: float = 60.0) -> list[dict]:
    """
    Find take boundaries within a group of segments.

    The reporter may restart from ANY earlier point, not just the first sentence.
    For each segment, check if it's similar to any segment from the current take's
    early portion. If it matches, it's a restart (new take boundary).
    """
    if len(segments) <= 3:
        return [_make_reading(segments)]

    boundaries = [0]

    for i in range(2, len(segments)):
        last_boundary = boundaries[-1]

        # Need at least 2 segments since last boundary to consider a restart
        if i - last_boundary < 2:
            continue

        seg_text = segments[i]["text"]

        # Check against all segments from the current take's start
        # (only check the first half of current take to avoid matching end-of-take content)
        take_len = i - last_boundary
        check_range = max(1, take_len // 2)

        for k in range(last_boundary, last_boundary + check_range):
            ref_text = segments[k]["text"]
            sim = fuzz.token_set_ratio(seg_text, ref_text)

            if sim >= similarity_threshold:
                boundaries.append(i)
                break

    if len(boundaries) > 1:
        return _boundaries_to_readings(segments, boundaries)

    return [_make_reading(segments)]


def _boundaries_to_readings(segments: list[dict], boundaries: list[int]) -> list[dict]:
    """Convert boundary indices to reading dicts."""
    result = []
    for j in range(len(boundaries)):
        start_idx = boundaries[j]
        end_idx = boundaries[j + 1] if j + 1 < len(boundaries) else len(segments)
        result.append(_make_reading(segments[start_idx:end_idx]))
    return result


def _make_reading(segments: list[dict]) -> dict:
    """Build a reading dict from a list of segments."""
    combined_text = " ".join(s["text"] for s in segments)
    return {
        "start": segments[0]["start"],
        "end": segments[-1]["end"],
        "text": combined_text,
        "segments": list(segments),
    }


def _cluster_readings_into_scenes(readings: list[dict], similarity_threshold: float = 55.0) -> list[dict]:
    """
    Cluster consecutive similar readings into scenes.

    If two consecutive readings have similar text -> same scene (different takes).
    When text similarity drops -> new scene.

    Returns:
        List of scenes with takes.
    """
    if not readings:
        return []

    scenes = []
    current_takes = [readings[0]]

    for reading in readings[1:]:
        # Compare with the first take of current scene (the reference)
        ref_text = current_takes[0]["text"]
        similarity = fuzz.token_set_ratio(reading["text"], ref_text)

        if similarity >= similarity_threshold:
            # Similar text -> another take of the same scene
            current_takes.append(reading)
        else:
            # Different text -> save current scene, start new one
            scenes.append(_build_scene(len(scenes) + 1, current_takes))
            current_takes = [reading]

    # Save last scene
    if current_takes:
        scenes.append(_build_scene(len(scenes) + 1, current_takes))

    return scenes


def _build_scene(scene_number: int, takes: list[dict]) -> dict:
    """Build a scene dict from its takes. Select the last take."""
    selected = takes[-1]  # Last take (final attempt)
    return {
        "scene_number": scene_number,
        "total_takes": len(takes),
        "selected_take": {
            "start": selected["start"],
            "end": selected["end"],
            "text": selected["text"],
        },
        "takes": [
            {
                "start": t["start"],
                "end": t["end"],
                "text": t["text"],
            }
            for t in takes
        ],
    }


def detect_scenes(
    segments: list[dict],
    silences: list[dict],
    similarity_threshold: float = 55.0,
    scene_gap: float = 3.0,
) -> dict:
    """
    Full pipeline: group segments into readings, split long ones, cluster into scenes.

    Args:
        segments: Transcription segments [{"start", "end", "text"}, ...]
        silences: Detected silence periods [{"start", "end"}, ...]
        similarity_threshold: Min similarity (0-100) to consider two readings as same scene.
        scene_gap: Min silence gap (seconds) to split readings.

    Returns:
        Dict with:
        - "scenes": list of detected scenes with takes
        - "total_scenes": number of unique scenes
        - "total_readings": total number of readings detected
    """
    # Step 1: Group segments into readings by silence gaps
    readings = _group_into_readings(segments, silences, gap=scene_gap)
    log.info("Detected %d readings from %d segments (gap=%.1fs)", len(readings), len(segments), scene_gap)

    # Step 2: Split long readings that contain multiple takes
    readings = _split_long_readings(readings, max_duration=40.0, similarity_threshold=60.0)
    log.info("After splitting long readings: %d readings", len(readings))

    # Step 3: Cluster readings into scenes by text similarity
    scenes = _cluster_readings_into_scenes(readings, similarity_threshold)
    log.info("Clustered into %d scenes", len(scenes))

    # Build clips for XML (from selected takes)
    selected_clips = []
    for scene in scenes:
        take = scene["selected_take"]
        selected_clips.append({
            "start": take["start"],
            "end": take["end"],
            "shot_number": scene["scene_number"],
        })

    return {
        "scenes": scenes,
        "selected_clips": selected_clips,
        "total_scenes": len(scenes),
        "total_readings": len(readings),
    }
