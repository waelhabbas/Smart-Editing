"""File upload and cleanup utilities."""

import os
import shutil
import logging
from pathlib import Path
from fastapi import UploadFile

log = logging.getLogger(__name__)


async def save_upload_streaming(upload: UploadFile, dest: str):
    """Save uploaded file by streaming chunks (1MB) instead of loading all into memory."""
    with open(dest, "wb") as f:
        while chunk := await upload.read(1024 * 1024):
            f.write(chunk)


def cleanup_files(*paths: str | None):
    """Remove files if they exist. Ignores None values and missing files."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                log.info("Cleaned up: %s", Path(path).name)
            except OSError:
                pass


def cleanup_dir(dir_path: str | Path):
    """Remove a directory and all its contents if it exists."""
    if os.path.isdir(dir_path):
        try:
            shutil.rmtree(dir_path)
            log.info("Cleaned up directory: %s", Path(dir_path).name)
        except OSError:
            pass
