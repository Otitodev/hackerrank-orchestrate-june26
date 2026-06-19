"""Image path resolution, ID extraction, and base64 encoding for the Vision API.

Image paths in ``claims.csv`` are repo-relative (e.g.
``images/test/case_001/img_1.jpg``) and resolve against ``dataset/``. The
``image_id`` is the filename stem (``img_1``) and is only unique *within* a
claim, so never build a global image index keyed on it.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .csv_loader import DATASET_DIR

MAX_DIMENSION = 1568          # Anthropic vision recommendation
MAX_ENCODED_BYTES = 5 * 1024 * 1024

# Media types accepted directly by the vision APIs (Anthropic/OpenAI/Gemini).
# NOTE: dataset files all carry a ``.jpg`` extension but are actually a mix of
# JPEG / PNG / WEBP / AVIF, so we must sniff the real format from magic bytes
# rather than trusting the suffix (a wrong media_type is a hard 400 error).
_SUPPORTED_MEDIA = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def sniff_media_type(data: bytes) -> Optional[str]:
    """Return the real image media type from magic bytes, or ``None`` if unknown."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"          # not directly supported -> transcode
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic"          # not directly supported -> transcode
    return None


@dataclass
class ResolvedImage:
    image_id: str            # filename stem, e.g. "img_1"
    rel_path: str            # as given in image_paths
    abs_path: Path
    exists: bool


def image_id_from_path(rel_path: str) -> str:
    """Return the image ID (filename without extension)."""
    return Path(rel_path).stem


def resolve_image_paths(
    image_paths_field: str, base_dir: Path = DATASET_DIR
) -> List[ResolvedImage]:
    """Parse the semicolon-separated ``image_paths`` field into resolved images."""
    resolved: List[ResolvedImage] = []
    for raw in image_paths_field.split(";"):
        rel = raw.strip()
        if not rel:
            continue
        abs_path = (base_dir / rel).resolve()
        resolved.append(
            ResolvedImage(
                image_id=image_id_from_path(rel),
                rel_path=rel,
                abs_path=abs_path,
                exists=abs_path.is_file(),
            )
        )
    return resolved


def encode_image(abs_path: Path) -> Optional[Tuple[str, str]]:
    """Return ``(base64_data, media_type)`` for an image, or ``None`` if missing.

    The media type is determined by sniffing the real bytes (the dataset's
    ``.jpg`` files are a mix of JPEG/PNG/WEBP/AVIF). Directly-supported formats
    that fit the size limit are passed through untouched; everything else
    (AVIF/HEIC, unknown, or oversized) is transcoded to JPEG and downscaled to
    ``MAX_DIMENSION``. Pillow is imported lazily.
    """
    if not abs_path.is_file():
        return None

    raw = abs_path.read_bytes()
    media_type = sniff_media_type(raw)

    # Fast path: a directly-supported format that fits the byte budget.
    if media_type in _SUPPORTED_MEDIA and len(raw) <= MAX_ENCODED_BYTES:
        return base64.standard_b64encode(raw).decode("ascii"), media_type

    # Otherwise transcode to JPEG (handles AVIF/HEIC, unknown, or oversized).
    try:
        from PIL import Image
    except ImportError:
        if media_type in _SUPPORTED_MEDIA:
            # No Pillow but format is usable as-is (just oversized): send raw.
            return base64.standard_b64encode(raw).decode("ascii"), media_type
        return None  # can't transcode an unsupported format without Pillow

    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
    except Exception:
        return None  # unreadable/corrupt image -> caller treats as missing
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
