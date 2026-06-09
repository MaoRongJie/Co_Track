from __future__ import annotations

import base64
import binascii
import io
from pathlib import Path
from typing import Any

from app.model_processing import TEXTURE_MAP_DIR


def image_reference_to_data_url(image_reference: str | None) -> str | None:
    reference = str(image_reference or "").strip()
    if not reference:
        return None
    if reference.startswith("data:image/"):
        return reference

    local_path = _resolve_local_image_path(reference)
    if local_path is None or not local_path.is_file():
        return None

    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(local_path.suffix.lower(), "image/png")
    encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def extract_image_metrics(image_reference: str | None) -> dict[str, Any]:
    width = 1024
    height = 1024
    if not image_reference:
        return _default_image_metrics(width=width, height=height)

    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return _default_image_metrics(width=width, height=height)

    image = _load_image_from_reference(reference=str(image_reference).strip(), image_module=Image)
    if image is None:
        return _default_image_metrics(width=width, height=height)

    with image:
        rgba_image = image.convert("RGBA")
        width, height = rgba_image.size
        sample = rgba_image.resize((min(256, width), min(256, height)))
        sample_array = np.asarray(sample, dtype=np.float32)

    alpha = sample_array[:, :, 3] / 255.0
    opaque_mask = alpha > 0.05
    rgb = sample_array[:, :, :3] / 255.0
    if not opaque_mask.any():
        opaque_mask = np.ones(alpha.shape, dtype=bool)

    pixels = rgb[opaque_mask]
    maxc = pixels.max(axis=1)
    minc = pixels.min(axis=1)
    value = maxc
    saturation = np.where(maxc <= 1e-6, 0.0, (maxc - minc) / np.maximum(maxc, 1e-6))
    luma = pixels[:, 0] * 0.2126 + pixels[:, 1] * 0.7152 + pixels[:, 2] * 0.0722

    opaque_ratio_percent = round(float(opaque_mask.mean() * 100.0), 1)
    saturation_score = int(round(float(np.clip(saturation.mean() * 100.0, 0.0, 100.0))))
    contrast_score = int(round(float(np.clip(luma.std() * 320.0, 0.0, 100.0))))
    vibrant_ratio_percent = round(float(((saturation > 0.55) & (value > 0.22) & (value < 0.92)).mean() * 100.0), 1)
    dark_ratio_percent = round(float((luma < 0.25).mean() * 100.0), 1)
    bright_ratio_percent = round(float((luma > 0.78).mean() * 100.0), 1)

    diff_candidates: list[np.ndarray] = []
    if sample_array.shape[1] > 1:
        right_mask = opaque_mask[:, 1:] & opaque_mask[:, :-1]
        right_diff = np.linalg.norm(sample_array[:, 1:, :3] - sample_array[:, :-1, :3], axis=2)
        diff_candidates.append(right_diff[right_mask])
    if sample_array.shape[0] > 1:
        down_mask = opaque_mask[1:, :] & opaque_mask[:-1, :]
        down_diff = np.linalg.norm(sample_array[1:, :, :3] - sample_array[:-1, :, :3], axis=2)
        diff_candidates.append(down_diff[down_mask])

    if diff_candidates:
        diffs = np.concatenate([item for item in diff_candidates if item.size > 0], axis=0)
    else:
        diffs = np.asarray([], dtype=np.float32)

    if diffs.size == 0:
        gradient_ratio_percent = 0.0
        edge_complexity_score = 0
    else:
        smooth_gradient_ratio = ((diffs >= 6.0) & (diffs <= 52.0)).mean()
        sharp_edge_ratio = (diffs > 58.0).mean()
        gradient_ratio_percent = round(float(np.clip(smooth_gradient_ratio * 100.0, 0.0, 100.0)), 1)
        edge_complexity_score = int(round(float(np.clip(sharp_edge_ratio * 180.0, 0.0, 100.0))))

    quantized = sample.convert("RGB").quantize(colors=6)
    palette = quantized.getpalette() or []
    color_counts = quantized.getcolors(maxcolors=256) or []
    total_count = sum(count for count, _ in color_counts) or 1
    dominant_colors: list[str] = []
    dominant_shares: list[float] = []
    for count, palette_index in sorted(color_counts, reverse=True)[:5]:
        offset = palette_index * 3
        if offset + 2 >= len(palette):
            continue
        rgb_triplet = palette[offset : offset + 3]
        dominant_colors.append(f"#{rgb_triplet[0]:02x}{rgb_triplet[1]:02x}{rgb_triplet[2]:02x}")
        dominant_shares.append(round(count / total_count * 100.0, 1))

    estimated_color_zones = max(1, min(8, sum(1 for share in dominant_shares if share >= 7.5)))
    if vibrant_ratio_percent >= 18.0 and estimated_color_zones < 6:
        estimated_color_zones += 1

    return {
        "width": width,
        "height": height,
        "opaque_ratio_percent": opaque_ratio_percent,
        "dominant_colors": dominant_colors or ["#cbd5e1"],
        "dominant_color_shares": dominant_shares or [100.0],
        "estimated_color_zones": estimated_color_zones,
        "gradient_ratio_percent": gradient_ratio_percent,
        "contrast_score": contrast_score,
        "saturation_score": saturation_score,
        "vibrant_ratio_percent": vibrant_ratio_percent,
        "dark_ratio_percent": dark_ratio_percent,
        "bright_ratio_percent": bright_ratio_percent,
        "edge_complexity_score": edge_complexity_score,
    }


def _default_image_metrics(*, width: int, height: int) -> dict[str, Any]:
    return {
        "width": width,
        "height": height,
        "opaque_ratio_percent": 100.0,
        "dominant_colors": ["#cbd5e1", "#94a3b8"],
        "dominant_color_shares": [64.0, 36.0],
        "estimated_color_zones": 2,
        "gradient_ratio_percent": 12.0,
        "contrast_score": 48,
        "saturation_score": 36,
        "vibrant_ratio_percent": 10.0,
        "dark_ratio_percent": 12.0,
        "bright_ratio_percent": 26.0,
        "edge_complexity_score": 38,
    }


def _load_image_from_reference(*, reference: str, image_module: Any) -> Any | None:
    if reference.startswith("data:image/"):
        try:
            _, encoded = reference.split(",", 1)
            raw_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return None
        return image_module.open(io.BytesIO(raw_bytes))

    local_path = _resolve_local_image_path(reference)
    if local_path is None or not local_path.is_file():
        return None
    return image_module.open(local_path)


def _resolve_local_image_path(image_reference: str | None) -> Path | None:
    reference = str(image_reference or "").strip()
    if not reference:
        return None

    direct_path = Path(reference)
    if direct_path.is_file():
        return direct_path

    if reference.startswith("/files/textures/"):
        candidate = (TEXTURE_MAP_DIR / Path(reference).name).resolve()
        try:
            candidate.relative_to(TEXTURE_MAP_DIR.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    return None
