"""
Process B-Roll overlays from CSV shot data.
Maps CSV cut points to V2 track overlay clips on the timeline.
"""

import asyncio
import logging
from backend.pipeline.xml_generator import get_video_info
from backend.pipeline.text_matcher import find_shot_span
from backend.utils.timecode import seconds_to_frames

log = logging.getLogger(__name__)


async def process_broll_shots(
    csv_shots: list[dict],
    final_clips: list[dict],
    uploaded_files: dict[str, str],
    timebase: int,
    warnings: list[str],
) -> tuple[list[dict], dict]:
    """
    Process all B-Roll shots from CSV and create V2 track clips.

    B-Roll clips overlay on top of the presenter (video-only, no audio).
    Multiple cuts on the same shot are placed sequentially on V2.

    Args:
        csv_shots: Parsed CSV shots.
        final_clips: Timeline clips with positions.
        uploaded_files: Dict mapping filename -> path.
        timebase: Sequence timebase (fps).
        warnings: List to append warnings to.

    Returns:
        Tuple of (broll_clips, broll_file_registry).
    """
    broll_shots = [s for s in csv_shots if s.get("type", "").lower() == "broll"]
    if not broll_shots:
        return [], {}

    broll_clips = []
    broll_file_registry = {}
    file_counter = 1

    for shot in broll_shots:
        shot_num = shot["shot_number"]
        file_name = shot.get("file_name")
        cuts = shot.get("cuts", [])

        if not file_name:
            warnings.append(f"Shot {shot_num}: B-Roll has no file_name")
            continue

        if file_name not in uploaded_files:
            warnings.append(f"Shot {shot_num}: Missing B-Roll file '{file_name}'")
            continue

        if not cuts:
            warnings.append(f"Shot {shot_num}: B-Roll has no cut points")
            continue

        # Register file
        if file_name not in broll_file_registry:
            file_path = uploaded_files[file_name]
            info = await asyncio.to_thread(get_video_info, file_path)
            broll_file_registry[file_name] = {
                "path": file_path,
                "info": info,
                "file_id": f"file-broll-{file_counter}",
            }
            file_counter += 1

        reg = broll_file_registry[file_name]

        # Find shot span on timeline
        span = find_shot_span(shot_num, final_clips)
        if not span:
            warnings.append(f"Shot {shot_num}: not found on timeline for B-Roll")
            continue

        # Place each cut sequentially on V2 within the shot span
        # Use frame-accurate positions if available (matches XML generator)
        tl_position = span["timeline_start"]
        tl_position_frames = span.get("timeline_start_frames")
        span_end_frames = span.get("timeline_end_frames")

        for j, cut in enumerate(cuts):
            cut_duration = cut["out"] - cut["in"]
            tl_end = tl_position + cut_duration

            # Don't exceed shot span
            if tl_end > span["timeline_end"]:
                tl_end = span["timeline_end"]
                cut_duration = tl_end - tl_position
                if cut_duration <= 0:
                    break

            cut_duration_frames = seconds_to_frames(cut_duration, timebase)

            if tl_position_frames is not None:
                start_f = tl_position_frames
                end_f = tl_position_frames + cut_duration_frames
                # Clamp to shot span in frames
                if span_end_frames is not None and end_f > span_end_frames:
                    end_f = span_end_frames
            else:
                start_f = seconds_to_frames(tl_position, timebase)
                end_f = seconds_to_frames(tl_end, timebase)

            broll_clips.append({
                "broll_filename": file_name,
                "timeline_start_frames": start_f,
                "timeline_end_frames": end_f,
                "source_in_frames": seconds_to_frames(cut["in"], timebase),
                "source_out_frames": seconds_to_frames(cut["in"] + cut_duration, timebase),
                "file_id": reg["file_id"],
            })
            tl_position_frames = end_f if tl_position_frames is not None else None

            log.info("Shot %d B-Roll cut %d: tl %.2f-%.2f, src %.2f-%.2f",
                     shot_num, j + 1, tl_position, tl_end, cut["in"], cut["in"] + cut_duration)

            tl_position = tl_end

    log.info("Processed %d B-Roll clips from %d shots", len(broll_clips), len(broll_shots))
    return broll_clips, broll_file_registry
