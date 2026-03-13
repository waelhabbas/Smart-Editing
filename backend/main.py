"""
Smart Editing - FastAPI backend.
Auto-detects scenes from video and generates Premiere Pro timeline.
"""

import os
import json
import uuid
import asyncio
import logging
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from typing import Optional
from dotenv import load_dotenv
from transcriber import transcribe, extract_audio
from gemini_detector import detect_scenes_with_gemini
from script_parser import parse_script
from silence_remover import detect_silences, remove_silences_from_segments
from xml_generator import generate_fcp_xml
from srt_generator import generate_srt

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Smart Editing")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def save_upload_streaming(upload: UploadFile, dest: str):
    """Save uploaded file by streaming chunks instead of loading all into memory."""
    with open(dest, "wb") as f:
        while chunk := await upload.read(1024 * 1024):  # 1MB chunks
            f.write(chunk)


@app.post("/api/process")
async def process_video(
    video: UploadFile = File(...),
    script: Optional[UploadFile] = File(default=None),
    gemini_api_key: str = Form(default=""),
    language: str = Form(default=""),
    min_silence_ms: int = Form(default=500),
    silence_padding_ms: int = Form(default=150),
):
    """
    Process a video file: auto-detect scenes and generate Premiere Pro timeline.
    Optional script upload for better take selection.
    """
    # API key: from form or .env
    api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="مفتاح Gemini API مطلوب — أدخله في الواجهة أو في ملف .env")

    job_id = str(uuid.uuid4())[:8]
    log.info("Job %s: started", job_id)

    # Save video (streaming - low memory)
    video_ext = Path(video.filename).suffix
    video_path = str(UPLOADS_DIR / f"{job_id}_video{video_ext}")
    await save_upload_streaming(video, video_path)
    log.info("Job %s: video saved", job_id)

    # Parse optional script
    script_text = None
    script_path = None
    if script and script.filename:
        script_ext = Path(script.filename).suffix
        script_path = str(UPLOADS_DIR / f"{job_id}_script{script_ext}")
        await save_upload_streaming(script, script_path)
        try:
            shots = parse_script(script_path)
            if shots:
                script_text = "\n".join(f"{s['shot_number']}. {s['text']}" for s in shots)
                log.info("Job %s: parsed script with %d shots", job_id, len(shots))
        except Exception as e:
            log.warning("Job %s: failed to parse script: %s", job_id, e)
        finally:
            if script_path and os.path.exists(script_path):
                os.remove(script_path)
                script_path = None

    # Extract audio ONCE and reuse for transcription + silence detection
    audio_path = str(UPLOADS_DIR / f"{job_id}_audio.wav")

    try:
        # Step 1: Extract audio
        log.info("Job %s: extracting audio...", job_id)
        await asyncio.to_thread(extract_audio, video_path, audio_path)

        # Step 2: Transcribe
        lang = language if language else None
        log.info("Job %s: transcribing...", job_id)
        segments = await asyncio.to_thread(transcribe, audio_path, lang)

        if not segments:
            raise HTTPException(status_code=400, detail="لم يتم العثور على كلام في الفيديو")
        log.info("Job %s: got %d segments", job_id, len(segments))

        # Step 3: Detect silences
        log.info("Job %s: detecting silences...", job_id)
        silences = await asyncio.to_thread(
            detect_silences, audio_path, min_silence_ms, -40,
        )

        # Step 4: Gemini AI analyzes scenes and takes
        log.info("Job %s: sending to Gemini AI for scene analysis...", job_id)
        scene_result = await asyncio.to_thread(
            detect_scenes_with_gemini, segments, api_key, script_text
        )
        scenes = scene_result["scenes"]

        if not scenes:
            raise HTTPException(status_code=400, detail="لم يتم اكتشاف أي مشاهد في الفيديو")
        log.info("Job %s: detected %d scenes from %d readings",
                 job_id, scene_result["total_scenes"], scene_result["total_readings"])

        # Step 5: Remove silences from selected clips
        selected_clips = scene_result["selected_clips"]
        final_clips = remove_silences_from_segments(
            selected_clips, silences, padding_ms=silence_padding_ms
        )

        # Compute timeline positions for each clip (needed for B-Roll matching)
        timeline_pos_sec = 0.0
        for clip in final_clips:
            clip_dur = clip["end"] - clip["start"]
            clip["timeline_start"] = timeline_pos_sec
            clip["timeline_end"] = timeline_pos_sec + clip_dur
            timeline_pos_sec += clip_dur

        # Save metadata for B-Roll post-processing
        metadata = {
            "job_id": job_id,
            "segments": segments,
            "final_clips": final_clips,
        }
        metadata_path = str(OUTPUT_DIR / f"{job_id}_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, ensure_ascii=False)
        log.info("Job %s: metadata saved for B-Roll", job_id)

        # Clean up audio
        if os.path.exists(audio_path):
            os.remove(audio_path)
            audio_path = None

        # Step 6: Generate FCP XML
        xml_filename = f"{job_id}_timeline.xml"
        xml_path = str(OUTPUT_DIR / xml_filename)

        log.info("Job %s: generating XML...", job_id)
        await asyncio.to_thread(
            generate_fcp_xml, video_path, final_clips, xml_path, "Smart Edit Timeline",
        )

        # Step 7: Generate SRT subtitle file
        srt_filename = f"{job_id}_subtitles.srt"
        srt_path = str(OUTPUT_DIR / srt_filename)

        log.info("Job %s: generating SRT...", job_id)
        await asyncio.to_thread(
            generate_srt, final_clips, srt_path, segments,
            use_script_text=bool(script_text),
        )

        # Build summary response
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

        log.info("Job %s: done!", job_id)
        return JSONResponse({
            "status": "success",
            "job_id": job_id,
            "download_url": f"/api/download/{xml_filename}",
            "srt_download_url": f"/api/download/{srt_filename}",
            "total_scenes": scene_result["total_scenes"],
            "total_readings": scene_result["total_readings"],
            "total_clips_after_silence_removal": len(final_clips),
            "original_duration": round(sum(s["end"] - s["start"] for s in segments), 2),
            "final_duration": round(sum(c["end"] - c["start"] for c in final_clips), 2),
            "scenes_summary": summary,
            "token_usage": scene_result.get("token_usage"),
        })

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Job %s: processing failed", job_id)
        raise HTTPException(status_code=500, detail=f"خطأ في المعالجة: {str(e)}")
    finally:
        # Clean up: audio + video upload
        for path in [audio_path, video_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    log.info("Job %s: cleaned up %s", job_id, Path(path).name)
                except OSError:
                    pass


@app.post("/api/add-broll")
async def add_broll(
    job_id: str = Form(...),
    broll_files: list[UploadFile] = File(...),
    instructions_file: UploadFile = File(...),
):
    """Add B-Roll clips to an existing processed timeline."""
    from broll_parser import parse_broll_instructions
    from broll_matcher import find_word_on_timeline, find_paragraph_span
    from xml_generator import get_video_info, seconds_to_frames, add_broll_to_xml

    # Validate job exists
    metadata_path = OUTPUT_DIR / f"{job_id}_metadata.json"
    xml_path = OUTPUT_DIR / f"{job_id}_timeline.xml"
    if not metadata_path.exists() or not xml_path.exists():
        raise HTTPException(404, "لم يتم العثور على المشروع. قم بمعالجة الفيديو أولاً")

    # Load metadata
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    segments = metadata["segments"]
    final_clips = metadata["final_clips"]

    # Save uploaded B-Roll files
    broll_dir = UPLOADS_DIR / f"{job_id}_broll"
    broll_dir.mkdir(exist_ok=True)

    broll_paths = {}
    for bf in broll_files:
        dest = str(broll_dir / bf.filename)
        await save_upload_streaming(bf, dest)
        broll_paths[bf.filename] = dest
    log.info("Job %s B-Roll: uploaded files: %s", job_id, list(broll_paths.keys()))
    log.info("Job %s B-Roll: metadata has %d segments, %d final_clips",
             job_id, len(segments), len(final_clips))

    # Save and parse instructions file
    instr_path = str(UPLOADS_DIR / f"{job_id}_broll_instructions.txt")
    await save_upload_streaming(instructions_file, instr_path)

    try:
        instructions = parse_broll_instructions(instr_path)
        log.info("Job %s B-Roll: parsed %d instructions: %s",
                 job_id, len(instructions),
                 [(i["broll_filename"], i["target_word"], i["is_full"]) for i in instructions])

        # Read the sequence timebase from existing XML
        import xml.etree.ElementTree as ET_parse
        tree = ET_parse.parse(str(xml_path))
        seq_tb = int(tree.find(".//sequence/rate/timebase").text)

        # Match each instruction to a timeline position
        broll_clips = []
        warnings = []
        broll_file_registry = {}
        file_counter = 1

        for instr in instructions:
            log.info("Job %s B-Roll: processing instruction: file='%s', word='%s', full=%s",
                     job_id, instr["broll_filename"], instr["target_word"], instr["is_full"])
            if instr["broll_filename"] not in broll_paths:
                msg = f"ملف B-Roll غير موجود: {instr['broll_filename']} (الملفات المرفوعة: {list(broll_paths.keys())})"
                log.warning("Job %s B-Roll: %s", job_id, msg)
                warnings.append(msg)
                continue

            broll_path = broll_paths[instr["broll_filename"]]

            # Register B-Roll file if not already
            if instr["broll_filename"] not in broll_file_registry:
                broll_info = await asyncio.to_thread(get_video_info, broll_path)
                broll_file_registry[instr["broll_filename"]] = {
                    "path": broll_path,
                    "info": broll_info,
                    "file_id": f"file-broll-{file_counter}",
                }
                file_counter += 1

            reg = broll_file_registry[instr["broll_filename"]]

            if instr["is_full"]:
                span = find_paragraph_span(instr["target_word"], segments, final_clips)
                if not span:
                    warnings.append(
                        f"لم يتم العثور على الكلمة '{instr['target_word']}' في التايملاين"
                    )
                    continue

                tl_start = span["timeline_start"]
                tl_end = span["timeline_end"]
                duration_sec = tl_end - tl_start

                broll_clips.append({
                    "broll_filename": instr["broll_filename"],
                    "timeline_start_frames": seconds_to_frames(tl_start, seq_tb),
                    "timeline_end_frames": seconds_to_frames(tl_end, seq_tb),
                    "source_in_frames": 0,
                    "source_out_frames": seconds_to_frames(duration_sec, seq_tb),
                    "file_id": reg["file_id"],
                })
            else:
                word_match = find_word_on_timeline(
                    instr["target_word"], segments, final_clips,
                )
                if not word_match:
                    warnings.append(
                        f"لم يتم العثور على الكلمة '{instr['target_word']}' في التايملاين"
                    )
                    continue

                tl_start = word_match["timeline_position"]
                broll_duration = instr["source_out"] - instr["source_in"]
                tl_end = tl_start + broll_duration

                broll_clips.append({
                    "broll_filename": instr["broll_filename"],
                    "timeline_start_frames": seconds_to_frames(tl_start, seq_tb),
                    "timeline_end_frames": seconds_to_frames(tl_end, seq_tb),
                    "source_in_frames": seconds_to_frames(instr["source_in"], seq_tb),
                    "source_out_frames": seconds_to_frames(instr["source_out"], seq_tb),
                    "file_id": reg["file_id"],
                })

        if not broll_clips:
            detail = "لم يتم مطابقة أي بي رول مع التايملاين"
            if warnings:
                detail += "\n" + "\n".join(warnings)
            log.warning("Job %s B-Roll: no clips matched. Warnings: %s", job_id, warnings)
            raise HTTPException(400, detail)

        # Generate updated XML with B-Roll V2 track
        broll_xml_filename = f"{job_id}_timeline_broll.xml"
        broll_xml_path = str(OUTPUT_DIR / broll_xml_filename)

        await asyncio.to_thread(
            add_broll_to_xml,
            str(xml_path), broll_clips, broll_file_registry, broll_xml_path,
        )

        log.info("Job %s: B-Roll XML generated with %d clips", job_id, len(broll_clips))

        return JSONResponse({
            "status": "success",
            "download_url": f"/api/download/{broll_xml_filename}",
            "broll_count": len(broll_clips),
            "warnings": warnings,
        })

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Job %s: B-Roll processing failed", job_id)
        raise HTTPException(500, f"خطأ في معالجة البي رول: {str(e)}")
    finally:
        if os.path.exists(instr_path):
            os.remove(instr_path)


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Download a generated XML file."""
    # Validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="اسم ملف غير صالح")

    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="الملف غير موجود")

    media_type = "application/xml" if filename.endswith(".xml") else "text/plain"
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )


# Serve frontend
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
