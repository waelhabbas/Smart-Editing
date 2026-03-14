"""Explainer service API routes."""

import os
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional

from backend.config import UPLOADS_DIR, OUTPUT_DIR, GEMINI_API_KEY
from backend.utils.file_utils import save_upload_streaming
from backend.services.explainer_service import ExplainerService

router = APIRouter()
log = logging.getLogger(__name__)
service = ExplainerService()


@router.post("/step1")
async def process_step1(
    video: UploadFile = File(...),
    csv_file: UploadFile = File(...),
    gemini_api_key: str = Form(default=""),
    language: str = Form(default=""),
    min_silence_ms: int = Form(default=500),
    silence_padding_ms: int = Form(default=150),
):
    """Step 1: Upload video + CSV template -> process base timeline."""
    api_key = gemini_api_key or GEMINI_API_KEY
    if not api_key:
        raise HTTPException(400, "Gemini API key required - enter it in the UI or set it in .env")

    result = await service.process_step1(
        video=video,
        csv_file=csv_file,
        api_key=api_key,
        language=language or None,
        min_silence_ms=min_silence_ms,
        silence_padding_ms=silence_padding_ms,
    )
    return JSONResponse(result)


@router.post("/step2")
async def process_step2(
    job_id: str = Form(...),
    media_files: list[UploadFile] = File(...),
    logo_file: Optional[UploadFile] = File(None),
    outro_file: Optional[UploadFile] = File(None),
    transition_file: Optional[UploadFile] = File(None),
):
    """Step 2: Upload B-roll/soundbite files -> finalize timeline + SRT."""
    result = await service.process_step2(
        job_id=job_id,
        media_files=media_files,
        logo_file=logo_file,
        outro_file=outro_file,
        transition_file=transition_file,
    )
    return JSONResponse(result)
