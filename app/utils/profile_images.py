"""Validate and store profile pictures without trusting uploaded filenames."""

import logging
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
PROFILE_PICS_DIR = MEDIA_DIR / "profile_pics"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
logger = logging.getLogger(__name__)


def save_profile_image(data: bytes) -> str:
    """Decode, orient, resize and re-encode an upload; run in a worker thread."""
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Profile pictures must be 5 MB or smaller.")
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=400, detail="Profile pictures must be 16 megapixels or smaller.")
            source.load()
            image = ImageOps.exif_transpose(source)
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            image = image.convert("RGBA")
            image.info.clear()
            output = BytesIO()
            image.save(output, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="Choose a valid JPEG, PNG, or WebP image.") from None

    PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.png"
    destination = PROFILE_PICS_DIR / filename
    try:
        destination.write_bytes(output.getvalue())
    except OSError:
        remove_profile_image(filename)
        raise
    return filename


def remove_profile_image(filename: str | None) -> None:
    # Only remove files created by this uploader, never legacy paths or the default.
    if filename and re.fullmatch(r"[0-9a-f]{32}\.png", filename):
        try:
            (PROFILE_PICS_DIR / filename).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove profile picture %s", filename, exc_info=True)
