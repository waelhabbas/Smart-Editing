"""Explainer service - orchestrates the full video processing pipeline."""

import os
import json
import uuid
import asyncio
import logging
from pathlib import Path
from fastapi import UploadFile, HTTPException

from backend.config import UPLOADS_DIR, OUTPUT_DIR
from backend.services.base_service import BaseService
from backend.utils.file_utils import save_upload_streaming, cleanup_files, cleanup_dir

log = logging.getLogger(__name__)


class ExplainerService(BaseService):

    async def process_step1(
        self,
        video: UploadFile,
        csv_file: UploadFile,
        api_key: str,
        language: str | None = None,
    ) -> dict:
        """
        Step 1: Upload video + CSV -> process base timeline.

        Pipeline:
        1. Parse CSV into CSVShot list
        2. Extract audio from video
        3. Transcribe with Whisper (word-level timestamps)
        4. Send to Gemini to select best take per shot
        5. Build base timeline clips from selected takes
        6. Split clips at word gaps (using WhisperX word timestamps)
        7. Compute timeline positions
        8. Generate base FCP7 XML (V1 + A1)
        9. Save job metadata
        """
        from backend.pipeline.csv_parser import parse_csv_template
        from backend.pipeline.transcriber import transcribe, extract_audio
        from backend.pipeline.silence_remover import split_clips_on_word_gaps
        from backend.pipeline.gemini_analyzer import analyze_with_gemini
        from backend.pipeline.timeline_builder import build_base_timeline, compute_timeline_positions, validate_and_fix_clips
        from backend.pipeline.xml_generator import generate_base_xml, get_video_info

        job_id = str(uuid.uuid4())[:8]
        log.info("Job %s: Step 1 started", job_id)

        # Save video
        video_ext = Path(video.filename).suffix
        video_path = str(UPLOADS_DIR / f"{job_id}_video{video_ext}")
        await save_upload_streaming(video, video_path)

        # Save and parse CSV
        csv_path = str(UPLOADS_DIR / f"{job_id}_template.csv")
        await save_upload_streaming(csv_file, csv_path)

        audio_path = str(UPLOADS_DIR / f"{job_id}_audio.wav")

        try:
            # 1. Parse CSV
            csv_shots = parse_csv_template(csv_path)
            log.info("Job %s: parsed %d shots from CSV", job_id, len(csv_shots))

            # Identify required media files for Step 2
            required_files = []
            for shot in csv_shots:
                if shot.get("file_name") and shot["file_name"] not in required_files:
                    required_files.append(shot["file_name"])

            # 2. Extract audio
            log.info("Job %s: extracting audio...", job_id)
            await asyncio.to_thread(extract_audio, video_path, audio_path)

            # 3. Transcribe with Whisper
            log.info("Job %s: transcribing...", job_id)
            segments = await asyncio.to_thread(transcribe, audio_path, language)
            if not segments:
                raise HTTPException(400, "No speech detected in video")
            log.info("Job %s: got %d segments", job_id, len(segments))

            # 4. Gemini AI analysis - select best takes
            log.info("Job %s: sending to Gemini AI...", job_id)
            gemini_result = await asyncio.to_thread(
                analyze_with_gemini, segments, csv_shots, api_key, language
            )
            scenes = gemini_result["scenes"]
            if not scenes:
                raise HTTPException(400, "No scenes detected in video")

            # 5. Text-based take selection (precise word-level boundaries)
            from backend.pipeline.text_matcher import select_takes_by_text
            log.info("Job %s: selecting takes by text matching...", job_id)
            text_clips = select_takes_by_text(csv_shots, segments)

            # Use text-matched clips as primary, Gemini as fallback for missing shots
            matched_shots = {c["shot_number"] for c in text_clips}
            selected_clips = list(text_clips)
            for gc in gemini_result["selected_clips"]:
                if gc["shot_number"] not in matched_shots:
                    selected_clips.append(gc)
                    log.info("Job %s: Shot %s using Gemini fallback", job_id, gc["shot_number"])
            selected_clips.sort(key=lambda c: c["start"])

            # 5b. Validate and fix clip ordering (overlaps, reversals)
            from backend.config import MIN_CLIP_DURATION_SEC
            validation = validate_and_fix_clips(selected_clips, MIN_CLIP_DURATION_SEC)
            selected_clips = validation["clips"]
            clip_fixes = validation["fixes"]
            if clip_fixes:
                log.warning("Job %s: %d clip fixes applied", job_id, len(clip_fixes))

            # 6. Split clips at word gaps (using WhisperX word timestamps)
            final_clips = split_clips_on_word_gaps(selected_clips, segments)

            # 7. Get video info (needed for timebase before position computation)
            video_info = await asyncio.to_thread(get_video_info, video_path)

            # 8. Compute timeline positions (with frame positions for soundbite alignment)
            compute_timeline_positions(final_clips, timebase=video_info["timebase"])
            xml_filename = f"{job_id}_base.xml"
            xml_path = str(OUTPUT_DIR / xml_filename)

            log.info("Job %s: generating base XML...", job_id)
            await asyncio.to_thread(
                generate_base_xml, video_path, final_clips, xml_path, video_info
            )

            # 9. Save metadata for Step 2
            metadata = {
                "job_id": job_id,
                "video_path": video_path,
                "csv_shots": csv_shots,
                "segments": segments,
                "final_clips": final_clips,
                "required_files": required_files,
                "video_info": video_info,
                "language": language,
            }
            metadata_path = str(OUTPUT_DIR / f"{job_id}_metadata.json")
            with open(metadata_path, "w", encoding="utf-8") as mf:
                json.dump(metadata, mf, ensure_ascii=False)

            # Clean up audio (not video - needed for Step 2 reference)
            cleanup_files(audio_path, csv_path)
            audio_path = None

            # Build summary
            summary = []
            for scene in scenes:
                take = scene["selected_take"]
                summary.append({
                    "scene_number": scene["scene_number"],
                    "total_takes": scene["total_takes"],
                    "selected_start": round(take["start"], 2),
                    "selected_end": round(take["end"], 2),
                    "duration": round(take["end"] - take["start"], 2),
                })

            log.info("Job %s: Step 1 complete!", job_id)

            result = {
                "status": "success",
                "job_id": job_id,
                "download_url": f"/api/download/{xml_filename}",
                "total_scenes": gemini_result["total_scenes"],
                "total_readings": gemini_result["total_readings"],
                "total_clips_after_silence_removal": len(final_clips),
                "original_duration": round(sum(s["end"] - s["start"] for s in segments), 2),
                "final_duration": round(sum(c["end"] - c["start"] for c in final_clips), 2),
                "scenes_summary": summary,
                "required_files": required_files,
                "token_usage": gemini_result.get("token_usage"),
                "clip_fixes": clip_fixes if clip_fixes else None,
            }

            # Only include SRT in step 1 if no B-roll/soundbite files are needed
            if not required_files:
                from backend.pipeline.xml_generator import add_scale_keyframes
                await asyncio.to_thread(add_scale_keyframes, xml_path, xml_path)

                srt_filename = f"{job_id}_subtitles.srt"
                srt_path = str(OUTPUT_DIR / srt_filename)
                from backend.pipeline.srt_generator import generate_srt
                await asyncio.to_thread(
                    generate_srt, final_clips, csv_shots, segments, [], None, srt_path, language
                )
                result["srt_download_url"] = f"/api/download/{srt_filename}"

            return result

        except HTTPException:
            raise
        except Exception as e:
            log.exception("Job %s: Step 1 failed", job_id)
            raise HTTPException(500, f"Processing error: {str(e)}")
        finally:
            cleanup_files(audio_path, csv_path)

    async def process_step2(
        self,
        job_id: str,
        media_files: list[UploadFile],
        logo_file: UploadFile | None = None,
        outro_file: UploadFile | None = None,
        transition_file: UploadFile | None = None,
    ) -> dict:
        """
        Step 2: Upload B-roll/soundbite files -> finalize timeline + SRT.

        Pipeline:
        1. Load job metadata
        2. Validate uploaded files match CSV references
        3. Process B-roll overlays (V2 track)
        4. Process soundbites with timeline shifting (V3+A2)
        5. Generate final FCP7 XML
        6. Generate SRT (last step - accounts for all shifts)
        """
        from backend.pipeline.broll_processor import process_broll_shots
        from backend.pipeline.soundbite_processor import process_soundbite_shots
        from backend.pipeline.xml_generator import (
            get_video_info, add_broll_track, add_soundbite_with_shift,
            add_scale_keyframes, add_transition_track, add_logo_track, add_outro_track,
        )
        from backend.pipeline.srt_generator import generate_srt
        from backend.pipeline.transcriber import transcribe, extract_audio

        # Load metadata
        metadata_path = OUTPUT_DIR / f"{job_id}_metadata.json"
        base_xml_path = OUTPUT_DIR / f"{job_id}_base.xml"
        if not metadata_path.exists() or not base_xml_path.exists():
            raise HTTPException(404, "Job not found. Process the video first (Step 1).")

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        csv_shots = metadata["csv_shots"]
        segments = metadata["segments"]
        final_clips = metadata["final_clips"]
        video_info = metadata["video_info"]
        video_path = metadata["video_path"]
        language = metadata.get("language")

        # Save uploaded media files
        media_dir = UPLOADS_DIR / f"{job_id}_media"
        media_dir.mkdir(exist_ok=True)

        uploaded_files = {}
        for mf in media_files:
            dest = str(media_dir / mf.filename)
            await save_upload_streaming(mf, dest)
            uploaded_files[mf.filename] = dest
        log.info("Job %s: uploaded %d media files: %s", job_id, len(uploaded_files), list(uploaded_files.keys()))

        # Save logo file if provided
        logo_path = None
        if logo_file and logo_file.filename:
            logo_path = str(media_dir / logo_file.filename)
            await save_upload_streaming(logo_file, logo_path)
            log.info("Job %s: logo file saved: %s", job_id, logo_file.filename)

        # Save outro file if provided
        outro_path = None
        outro_info = None
        if outro_file and outro_file.filename:
            outro_path = str(media_dir / outro_file.filename)
            await save_upload_streaming(outro_file, outro_path)
            outro_info = await asyncio.to_thread(get_video_info, outro_path)
            log.info("Job %s: outro file saved: %s (duration: %.2fs)",
                     job_id, outro_file.filename, outro_info["duration"])

        # Save transition file if provided (single file with embedded video + audio)
        transition_path = None
        if transition_file and transition_file.filename:
            transition_path = str(media_dir / transition_file.filename)
            await save_upload_streaming(transition_file, transition_path)
            log.info("Job %s: transition file saved: %s", job_id, transition_file.filename)

        try:
            warnings = []
            tb = video_info["timebase"]

            # Validate required files
            for shot in csv_shots:
                fn = shot.get("file_name")
                if fn and fn not in uploaded_files:
                    warnings.append(f"Missing file: {fn}")

            # Process B-roll
            broll_clips, broll_registry = await process_broll_shots(
                csv_shots, final_clips, uploaded_files, tb, warnings
            )

            # Process soundbites
            sb_clips, sb_registry, sb_shifts, sb_transcriptions = await process_soundbite_shots(
                csv_shots, final_clips, uploaded_files, tb, language, warnings
            )

            if not broll_clips and not sb_clips and not warnings:
                # No media needed - just generate SRT
                pass

            # Generate final XML
            current_xml = str(base_xml_path)
            final_xml_filename = f"{job_id}_final.xml"
            final_xml_path = str(OUTPUT_DIR / final_xml_filename)

            if broll_clips and sb_clips:
                temp_path = str(OUTPUT_DIR / f"{job_id}_temp.xml")
                await asyncio.to_thread(
                    add_broll_track, current_xml, broll_clips, broll_registry, temp_path
                )
                await asyncio.to_thread(
                    add_soundbite_with_shift, temp_path, sb_clips, sb_registry, final_xml_path
                )
                cleanup_files(temp_path)
            elif broll_clips:
                await asyncio.to_thread(
                    add_broll_track, current_xml, broll_clips, broll_registry, final_xml_path
                )
            elif sb_clips:
                await asyncio.to_thread(
                    add_soundbite_with_shift, current_xml, sb_clips, sb_registry, final_xml_path
                )
            else:
                # No media clips - copy base XML as final
                import shutil
                shutil.copy2(current_xml, final_xml_path)

            # Add scale zoom keyframes
            await asyncio.to_thread(
                add_scale_keyframes, final_xml_path, final_xml_path
            )

            # Add transition track (V4 alpha video + A3 embedded audio)
            if transition_path:
                await asyncio.to_thread(
                    add_transition_track, final_xml_path, transition_path, final_xml_path
                )

            # Add logo overlay (topmost video track)
            if logo_path:
                await asyncio.to_thread(
                    add_logo_track, final_xml_path, logo_path, final_xml_path
                )

            # Add outro (topmost layer, overlaps end of sequence)
            if outro_path and outro_info:
                await asyncio.to_thread(
                    add_outro_track, final_xml_path, outro_path, outro_info, final_xml_path
                )

            # Generate SRT (LAST STEP)
            srt_filename = f"{job_id}_subtitles.srt"
            srt_path = str(OUTPUT_DIR / srt_filename)
            await asyncio.to_thread(
                generate_srt, final_clips, csv_shots, segments,
                sb_shifts, sb_transcriptions, srt_path, language
            )

            log.info("Job %s: Step 2 complete! %d B-roll, %d soundbites",
                     job_id, len(broll_clips), len(sb_clips))

            return {
                "status": "success",
                "download_url": f"/api/download/{final_xml_filename}",
                "srt_download_url": f"/api/download/{srt_filename}",
                "broll_count": len(broll_clips),
                "soundbite_count": len(sb_clips),
                "has_outro": outro_path is not None,
                "has_transition": transition_path is not None,
                "warnings": warnings,
            }

        except HTTPException:
            raise
        except Exception as e:
            log.exception("Job %s: Step 2 failed", job_id)
            raise HTTPException(500, f"Processing error: {str(e)}")
