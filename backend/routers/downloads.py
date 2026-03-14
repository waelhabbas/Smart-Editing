"""File download routes for generated XML and SRT files."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import OUTPUT_DIR

router = APIRouter()


@router.get("/download/{filename}")
async def download_file(filename: str):
    """Download a generated file (XML or SRT)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")

    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")

    if filename.endswith(".xml"):
        media_type = "application/xml"
    elif filename.endswith(".srt"):
        media_type = "text/plain; charset=utf-8"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )
