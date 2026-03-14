"""
Process soundbite insertions from CSV shot data.
Inserts soundbites between shots and shifts the timeline forward.
"""

import asyncio
import logging
from backend.pipeline.xml_generator import get_video_info
from backend.pipeline.text_matcher import find_shot_span
from backend.pipeline.transcriber import transcribe, extract_audio
from backend.utils.timecode import seconds_to_frames
from backend.utils.file_utils import cleanup_files

log = logging.getLogger(__name__)


async def process_soundbite_shots(
    csv_shots: list[dict],
    final_clips: list[dict],
    uploaded_files: dict[str, str],
    timebase: int,
    language: str | None,
    warnings: list[str],
) -> tuple[list[dict], dict, list[dict], dict]:
    """
    Process all soundbite shots from CSV.

    Soundbites are inserted at the end of their shot's span,
    pushing all subsequent clips forward. Each soundbite gets
    both video (V3) and audio (A2) tracks.

    Args:
        csv_shots: Parsed CSV shots.
        final_clips: Timeline clips with positions.
        uploaded_files: Dict mapping filename -> path.
        timebase: Sequence timebase (fps).
        language: Language hint for Whisper transcription.
        warnings: List to append warnings to.

    Returns:
        Tuple of (sb_clips, sb_file_registry, sb_shifts, sb_transcriptions).
        sb_shifts: [{insertion_point, duration, after_shot}, ...]
        sb_transcriptions: {shot_number: [whisper_segments], ...}
    """
    sb_shots = [s for s in csv_shots if s.get("type", "").lower() == "soundbite"]
    if not sb_shots:
        return [], {}, [], {}

    sb_clips = []
    sb_file_registry = {}
    sb_shifts = []
    sb_transcriptions = {}
    file_counter = 1

    for shot in sb_shots:
        shot_num = shot["shot_number"]
        file_name = shot.get("file_name")
        cuts = shot.get("cuts", [])

        if not file_name:
            warnings.append(f"Shot {shot_num}: Soundbite has no file_name")
            continue

        if file_name not in uploaded_files:
            warnings.append(f"Shot {shot_num}: Missing soundbite file '{file_name}'")
            continue

        if not cuts:
            warnings.append(f"Shot {shot_num}: Soundbite has no cut points")
            continue

        # Register file
        if file_name not in sb_file_registry:
            file_path = uploaded_files[file_name]
            info = await asyncio.to_thread(get_video_info, file_path)
            sb_file_registry[file_name] = {
                "path": file_path,
                "info": info,
                "file_id": f"file-sb-{file_counter}",
            }
            file_counter += 1

        reg = sb_file_registry[file_name]

        # Find shot span on timeline to determine insertion point
        span = find_shot_span(shot_num, final_clips)
        if not span:
            warnings.append(f"Shot {shot_num}: not found on timeline for soundbite")
            continue

        # Insertion point = end of this shot's span
        insertion_point = span["timeline_end"]
        # Use frame-accurate position if available (matches XML generator's arithmetic)
        insertion_point_frames_base = span.get("timeline_end_frames")

        # Transcribe soundbite audio for SRT subtitles
        if shot_num not in sb_transcriptions:
            try:
                file_path = uploaded_files[file_name]
                audio_path = file_path.rsplit(".", 1)[0] + "_audio.wav"
                await asyncio.to_thread(extract_audio, file_path, audio_path)
                sb_segments = await asyncio.to_thread(transcribe, audio_path, language)
                sb_transcriptions[shot_num] = sb_segments
                cleanup_files(audio_path)
                log.info("Shot %d: transcribed soundbite (%d segments)", shot_num, len(sb_segments))
            except Exception as e:
                log.warning("Shot %d: failed to transcribe soundbite: %s", shot_num, e)
                sb_transcriptions[shot_num] = []

        # Process each cut
        total_sb_duration = 0.0
        total_sb_duration_frames = 0
        for j, cut in enumerate(cuts):
            cut_duration = cut["out"] - cut["in"]
            cut_duration_frames = seconds_to_frames(cut_duration, timebase)

            # Use frame-accurate insertion point to match XML generator's positions
            if insertion_point_frames_base is not None:
                ins_frames = insertion_point_frames_base + total_sb_duration_frames
            else:
                ins_frames = seconds_to_frames(insertion_point + total_sb_duration, timebase)

            sb_clips.append({
                "sb_filename": file_name,
                "insertion_point_frames": ins_frames,
                "duration_frames": cut_duration_frames,
                "source_in_frames": seconds_to_frames(cut["in"], timebase),
                "source_out_frames": seconds_to_frames(cut["out"], timebase),
                "file_id": reg["file_id"],
            })

            sb_shifts.append({
                "insertion_point": insertion_point + total_sb_duration,
                "duration": cut_duration,
                "after_shot": shot_num,
                "source_in": cut["in"],
                "source_out": cut["out"],
            })

            log.info("Shot %d SB cut %d: insert at %.2f, duration %.2f, src %.2f-%.2f",
                     shot_num, j + 1, insertion_point + total_sb_duration,
                     cut_duration, cut["in"], cut["out"])

            total_sb_duration += cut_duration
            total_sb_duration_frames += cut_duration_frames

    log.info("Processed %d soundbite clips from %d shots", len(sb_clips), len(sb_shots))
    return sb_clips, sb_file_registry, sb_shifts, sb_transcriptions
