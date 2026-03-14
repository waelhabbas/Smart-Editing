"""Template file download routes."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import TEMPLATES_DIR

router = APIRouter()


@router.get("/{service_name}")
async def download_template(service_name: str):
    """Download a CSV template file for a given service."""
    if "/" in service_name or "\\" in service_name or ".." in service_name:
        raise HTTPException(400, "Invalid template name")

    # Map service name to template file
    template_map = {
        "Explainer": "Explainer.csv",
    }

    filename = template_map.get(service_name)
    if not filename:
        raise HTTPException(404, "Template not found")

    file_path = TEMPLATES_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "Template file not found")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="text/csv",
    )
