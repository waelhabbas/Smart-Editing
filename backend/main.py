"""
Smart Editing - FastAPI backend.
Auto-detects scenes from video and generates Premiere Pro timeline.
"""

import os
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
