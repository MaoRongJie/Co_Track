from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.model_processing import NORMALIZED_MODEL_DIR, TEXTURE_MAP_DIR, to_model_url, to_texture_url
from app.texture_planning import utcnow_iso


class ModelTexturingError(RuntimeError):
    pass


@dataclass(slots=True)
class EditedTextureApplicationResult:
    model_url: str
    base_color_url: str
    applied_at: str


def apply_edited_texture_to_model(
    *,
    session_id: int,
    scheme_id: str,
    base_model_reference: str,
    edited_base_color_bytes: bytes,
    texture_maps: dict[str, str | None] | None,
    meshy_task_id: str | None = None,
) -> EditedTextureApplicationResult:
    Image = _require_pillow()
    GLTF2, GLTFImage, Texture, TextureInfo, PbrMetallicRoughness, NormalMaterialTexture = _require_pygltflib()

    base_model_path = _resolve_local_model_path(base_model_reference)
    base_color_source_path = _resolve_local_texture_path(texture_maps.get("base_color") if texture_maps else None)
    metallic_source_path = _resolve_local_texture_path(texture_maps.get("metallic") if texture_maps else None)
    normal_source_path = _resolve_local_texture_path(texture_maps.get("normal") if texture_maps else None)
    roughness_source_path = _resolve_local_texture_path(texture_maps.get("roughness") if texture_maps else None)

    safe_scheme_id = _slugify(scheme_id, fallback="scheme")
    safe_task_id = _slugify(meshy_task_id or "manual", fallback="manual")
    applied_at = utcnow_iso()
    output_token = f"session_{abs(session_id)}_{safe_scheme_id}_{safe_task_id}_{uuid4().hex[:10]}"
    edited_base_color_path = TEXTURE_MAP_DIR / f"{output_token}_base_color.png"
    packed_metallic_roughness_path = TEXTURE_MAP_DIR / f"{output_token}_metallic_roughness.png"
    edited_model_path = NORMALIZED_MODEL_DIR / f"{output_token}_edited.glb"

    with Image.open(io.BytesIO(edited_base_color_bytes)) as uploaded_base_color:
        target_size = _determine_target_texture_size(
            uploaded_size=uploaded_base_color.size,
            base_color_source_path=base_color_source_path,
            metallic_source_path=metallic_source_path,
            normal_source_path=normal_source_path,
            roughness_source_path=roughness_source_path,
            image_module=Image,
        )
        prepared_base_color = _resize_image(uploaded_base_color.convert("RGBA"), target_size, Image)
        prepared_base_color.save(edited_base_color_path, format="PNG")

    packed_metallic_roughness_exists = _build_packed_metallic_roughness_texture(
        output_path=packed_metallic_roughness_path,
        size=target_size,
        metallic_source_path=metallic_source_path,
        roughness_source_path=roughness_source_path,
        image_module=Image,
    )

    gltf = GLTF2().load_binary(str(base_model_path))
    if not gltf.materials:
        raise ModelTexturingError("Locked base model contains no materials, so the edited texture cannot be applied.")

    gltf.images = list(gltf.images or [])
    gltf.textures = list(gltf.textures or [])

    base_color_texture_index = _append_texture_from_path(
        gltf=gltf,
        image_cls=GLTFImage,
        texture_cls=Texture,
        source_path=edited_base_color_path,
    )
    metallic_roughness_texture_index = (
        _append_texture_from_path(
            gltf=gltf,
            image_cls=GLTFImage,
            texture_cls=Texture,
            source_path=packed_metallic_roughness_path,
        )
        if packed_metallic_roughness_exists
        else None
    )
    normal_texture_index = (
        _append_texture_from_path(
            gltf=gltf,
            image_cls=GLTFImage,
            texture_cls=Texture,
            source_path=normal_source_path,
        )
        if normal_source_path is not None
        else None
    )

    for material in gltf.materials:
        if material.pbrMetallicRoughness is None:
            material.pbrMetallicRoughness = PbrMetallicRoughness()
        material.alphaMode = "OPAQUE"
        material.alphaCutoff = None
        material.pbrMetallicRoughness.baseColorTexture = TextureInfo(index=base_color_texture_index)
        material.pbrMetallicRoughness.baseColorFactor = [1.0, 1.0, 1.0, 1.0]
        if metallic_roughness_texture_index is not None:
            material.pbrMetallicRoughness.metallicRoughnessTexture = TextureInfo(index=metallic_roughness_texture_index)
        if normal_texture_index is not None:
            normal_texture = (
                NormalMaterialTexture(index=normal_texture_index)
                if NormalMaterialTexture is not None
                else TextureInfo(index=normal_texture_index)
            )
            material.normalTexture = normal_texture

    gltf.save_binary(str(edited_model_path))

    return EditedTextureApplicationResult(
        model_url=to_model_url(edited_model_path),
        base_color_url=to_texture_url(edited_base_color_path),
        applied_at=applied_at,
    )


def _require_pillow() -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ModelTexturingError(
            "Missing backend dependency 'Pillow'. Run backend dependency sync before applying edited textures."
        ) from exc
    return Image


def _require_pygltflib() -> tuple[Any, Any, Any, Any, Any, Any]:
    try:
        from pygltflib import GLTF2, Image, NormalMaterialTexture, PbrMetallicRoughness, Texture, TextureInfo
    except ImportError as exc:
        raise ModelTexturingError(
            "Missing backend dependency 'pygltflib'. Run backend dependency sync before applying edited textures."
        ) from exc
    return GLTF2, Image, Texture, TextureInfo, PbrMetallicRoughness, NormalMaterialTexture


def _resolve_local_model_path(model_reference: str) -> Path:
    reference = (model_reference or "").strip()
    if not reference:
        raise ModelTexturingError("Locked base model reference is empty.")

    direct_path = Path(reference)
    if direct_path.is_file():
        return direct_path

    if reference.startswith("/files/models/"):
        candidate = (NORMALIZED_MODEL_DIR / Path(reference).name).resolve()
        try:
            candidate.relative_to(NORMALIZED_MODEL_DIR.resolve())
        except ValueError as exc:
            raise ModelTexturingError("Locked base model path resolved outside the model directory.") from exc
        if candidate.is_file():
            return candidate

    raise ModelTexturingError(
        "Locked base model file could not be resolved locally. "
        "Expected a local path or a /files/models/... URL."
    )


def _resolve_local_texture_path(texture_reference: str | None) -> Path | None:
    reference = (texture_reference or "").strip()
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


def _determine_target_texture_size(
    *,
    uploaded_size: tuple[int, int],
    base_color_source_path: Path | None,
    metallic_source_path: Path | None,
    normal_source_path: Path | None,
    roughness_source_path: Path | None,
    image_module: Any,
) -> tuple[int, int]:
    for source_path in (base_color_source_path, metallic_source_path, normal_source_path, roughness_source_path):
        if source_path is None or not source_path.is_file():
            continue
        with image_module.open(source_path) as reference_image:
            width, height = reference_image.size
            if width > 0 and height > 0:
                return width, height
    width, height = uploaded_size
    if width <= 0 or height <= 0:
        raise ModelTexturingError("Edited texture PNG is empty or invalid.")
    return width, height


def _resize_image(image: Any, size: tuple[int, int], image_module: Any) -> Any:
    if image.size == size:
        return image.copy()
    return image.resize(size, image_module.Resampling.LANCZOS)


def _build_packed_metallic_roughness_texture(
    *,
    output_path: Path,
    size: tuple[int, int],
    metallic_source_path: Path | None,
    roughness_source_path: Path | None,
    image_module: Any,
) -> bool:
    if metallic_source_path is None and roughness_source_path is None:
        return False

    metallic_image = _load_single_channel_texture(
        source_path=metallic_source_path,
        size=size,
        default_value=0,
        image_module=image_module,
    )
    roughness_image = _load_single_channel_texture(
        source_path=roughness_source_path,
        size=size,
        default_value=255,
        image_module=image_module,
    )

    packed = image_module.merge(
        "RGBA",
        (
            image_module.new("L", size, 0),
            roughness_image,
            metallic_image,
            image_module.new("L", size, 255),
        ),
    )
    packed.save(output_path, format="PNG")
    return True


def _load_single_channel_texture(
    *,
    source_path: Path | None,
    size: tuple[int, int],
    default_value: int,
    image_module: Any,
) -> Any:
    if source_path is None or not source_path.is_file():
        return image_module.new("L", size, default_value)
    with image_module.open(source_path) as source_image:
        grayscale = source_image.convert("L")
        return _resize_image(grayscale, size, image_module)


def _append_texture_from_path(*, gltf: Any, image_cls: Any, texture_cls: Any, source_path: Path) -> int:
    image_index = len(gltf.images)
    gltf.images.append(image_cls(uri=_path_to_data_uri(source_path)))
    texture_index = len(gltf.textures)
    gltf.textures.append(texture_cls(source=image_index))
    return texture_index


def _path_to_data_uri(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(source_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _slugify(value: str, *, fallback: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value.strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned[:48] or fallback
