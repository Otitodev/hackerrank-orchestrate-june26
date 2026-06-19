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
_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


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

    Oversized images are downscaled to ``MAX_DIMENSION`` and re-encoded as JPEG.
    Pillow is imported lazily so the loader stays importable without it.
    """
    if not abs_path.is_file():
        return None

    media_type = _MEDIA_TYPES.get(abs_path.suffix.lower(), "image/jpeg")
    raw = abs_path.read_bytes()

    # Fast path: small enough and a directly-supported type.
    if len(raw) <= MAX_ENCODED_BYTES and abs_path.suffix.lower() in _MEDIA_TYPES:
        return base64.standard_b64encode(raw).decode("ascii"), media_type

    try:
        from PIL import Image
    except ImportError:
        # No Pillow: fall back to sending the raw bytes as-is.
        return base64.standard_b64encode(raw).decode("ascii"), media_type

    with Image.open(io.BytesIO(raw)) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
