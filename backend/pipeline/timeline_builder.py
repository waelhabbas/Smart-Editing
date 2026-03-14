"""
Build the base timeline from selected takes.
Assigns timeline positions and manages clip ordering.
Validates and fixes overlapping/out-of-order clips from Gemini.
"""

import logging

log = logging.getLogger(__name__)


def build_base_timeline(selected_clips: list[dict]) -> list[dict]:
    """
    Build an ordered timeline from selected take clips.

    Args:
        selected_clips: List of clips from Gemini analysis.
            Each: {"start", "end", "shot_number", "text"}

    Returns:
        List of clips sorted by shot_number.
    """
    # Sort by shot_number to ensure correct order
    timeline = sorted(selected_clips, key=lambda c: c["shot_number"])
    log.info("Built base timeline: %d clips", len(timeline))
    return timeline


def validate_and_fix_clips(clips: list[dict], min_duration: float = 0.5) -> dict:
    """
    Validate clips are sequential and non-overlapping in source time.
    Fix issues: trim overlaps, remove tiny clips, resolve time reversals.

    Args:
        clips: List of clips with "start", "end", "shot_number", "text".
        min_duration: Minimum clip duration in seconds. Clips shorter than
                      this after trimming are removed.

    Returns:
        Dict with:
            - clips: Fixed list of clips
            - fixes: List of description strings for each fix applied
            - removed: Count of clips removed
    """
    if not clips:
        return {"clips": [], "fixes": [], "removed": 0}

    # Sort by start time to detect ordering issues
    sorted_clips = sorted(clips, key=lambda c: c["start"])

    # Check if shot_number order differs from time order
    shot_order = [c["shot_number"] for c in sorted(clips, key=lambda c: c["shot_number"])]
    time_order = [c["shot_number"] for c in sorted_clips]
    if shot_order != time_order:
        log.warning("Shot order differs from time order! Shot: %s, Time: %s", shot_order, time_order)

    # Work with time-sorted clips
    fixed = list(sorted_clips)
    fixes = []
    removed = 0

    i = 0
    while i < len(fixed) - 1:
        current = fixed[i]
        nxt = fixed[i + 1]

        # Case 1: Next clip starts before current clip ends (overlap)
        if nxt["start"] < current["end"]:
            overlap = current["end"] - nxt["start"]

            if nxt["start"] <= current["start"]:
                # Full containment or reversal — remove the shorter clip
                cur_dur = current["end"] - current["start"]
                nxt_dur = nxt["end"] - nxt["start"]
                if cur_dur >= nxt_dur:
                    fixes.append(
                        f"Shot {nxt['shot_number']}: removed (fully contained within shot {current['shot_number']})"
                    )
                    fixed.pop(i + 1)
                    removed += 1
                    continue
                else:
                    fixes.append(
                        f"Shot {current['shot_number']}: removed (fully contained within shot {nxt['shot_number']})"
                    )
                    fixed.pop(i)
                    removed += 1
                    continue
            else:
                # Partial overlap — trim current clip's end
                fixes.append(
                    f"Shot {current['shot_number']}: trimmed end by {overlap:.2f}s "
                    f"(overlap with shot {nxt['shot_number']})"
                )
                current["end"] = nxt["start"]

                # Check if trimmed clip is too short
                if current["end"] - current["start"] < min_duration:
                    fixes.append(
                        f"Shot {current['shot_number']}: removed (duration {current['end'] - current['start']:.2f}s < {min_duration}s after trimming)"
                    )
                    fixed.pop(i)
                    removed += 1
                    continue

        i += 1

    # Final pass: remove any clips with invalid duration
    final = []
    for clip in fixed:
        dur = clip["end"] - clip["start"]
        if dur < min_duration:
            fixes.append(
                f"Shot {clip['shot_number']}: removed (duration {dur:.2f}s < {min_duration}s)"
            )
            removed += 1
        else:
            final.append(clip)

    # Re-sort by shot_number for timeline building
    final.sort(key=lambda c: c["shot_number"])

    if fixes:
        log.warning("Clip validation: %d fixes applied, %d clips removed", len(fixes), removed)
        for fix in fixes:
            log.warning("  - %s", fix)
    else:
        log.info("Clip validation: all %d clips are clean (no overlaps)", len(final))

    return {"clips": final, "fixes": fixes, "removed": removed}


def compute_timeline_positions(clips: list[dict], timebase: int = 0):
    """
    Compute timeline_start and timeline_end for each clip.
    Modifies clips in place.

    If timebase > 0, also computes frame-accurate positions
    (timeline_start_frames, timeline_end_frames) using the same
    arithmetic as the XML generator to avoid rounding drift.

    Args:
        clips: List of clips with "start" and "end" fields (source times).
        timebase: FPS for frame-based positions. 0 = skip frame positions.
    """
    pos = 0.0
    frame_pos = 0
    for clip in clips:
        duration = clip["end"] - clip["start"]
        clip["timeline_start"] = pos
        clip["timeline_end"] = pos + duration
        pos += duration

        if timebase > 0:
            clip_in_frames = round(clip["start"] * timebase)
            clip_out_frames = round(clip["end"] * timebase)
            frame_dur = clip_out_frames - clip_in_frames
            clip["timeline_start_frames"] = frame_pos
            clip["timeline_end_frames"] = frame_pos + frame_dur
            frame_pos += frame_dur

    log.info("Computed timeline positions: total duration %.2fs", pos)
