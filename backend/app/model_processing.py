from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any


TRAIN_CATEGORIES = {"high_speed_train", "intercity_train", "metro_vehicle"}
SUPPORTED_MODEL_SUFFIXES = {".glb", ".gltf"}
BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_ASSET_ROOT = BACKEND_DIR / ".tmp" / "model_assets"
ORIGINAL_UPLOAD_DIR = MODEL_ASSET_ROOT / "original"
NORMALIZED_MODEL_DIR = MODEL_ASSET_ROOT / "models"
UV_TEMPLATE_DIR = MODEL_ASSET_ROOT / "uv"
TEXTURE_MAP_DIR = MODEL_ASSET_ROOT / "textures"

for _directory in (ORIGINAL_UPLOAD_DIR, NORMALIZED_MODEL_DIR, UV_TEMPLATE_DIR, TEXTURE_MAP_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


class ModelProcessingError(RuntimeError):
    pass


@dataclass(slots=True)
class ProcessedModelAsset:
    model_url: str
    uv_template_url: str
    surface_area_m2: float
    paintable_uv_pixels: int
    mapping_meta: dict[str, Any]
    normalized_model_path: Path
    uv_template_path: Path


def get_uv_size(product_category: str) -> tuple[int, int]:
    if product_category in TRAIN_CATEGORIES:
        return 4096, 2048
    return 2048, 1024


def create_original_upload_path(*, session_id: int, task_id: int, suffix: str) -> Path:
    safe_suffix = suffix if suffix in SUPPORTED_MODEL_SUFFIXES else ".glb"
    return ORIGINAL_UPLOAD_DIR / f"session_{session_id}_task_{abs(task_id)}{safe_suffix}"


def create_normalized_model_path(*, session_id: int, model_id: int) -> Path:
    return NORMALIZED_MODEL_DIR / f"session_{session_id}_model_{abs(model_id)}.glb"


def create_uv_template_path(*, session_id: int, model_id: int) -> Path:
    return UV_TEMPLATE_DIR / f"session_{session_id}_model_{abs(model_id)}.png"


def to_model_url(path: Path) -> str:
    return f"/files/models/{path.name}"


def to_uv_url(path: Path) -> str:
    return f"/files/uv/{path.name}"


def to_texture_url(path: Path) -> str:
    return f"/files/textures/{path.name}"


def process_uploaded_model(
    *,
    source_path: Path,
    session_id: int,
    model_id: int,
    product_category: str,
    original_filename: str,
    stage_callback: Callable[[str, int, str], None] | None = None,
) -> ProcessedModelAsset:
    trimesh = _require_module("trimesh")
    numpy = _require_module("numpy")
    xatlas = _require_module("xatlas")
    image_module, image_draw_module = _require_pillow()

    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_MODEL_SUFFIXES:
        raise ModelProcessingError("Only GLB/GLTF uploads are supported in the current version.")

    _notify_stage(stage_callback, "validate", 10, "Validating uploaded model file")
    try:
        loaded = trimesh.load(source_path, force="scene")
    except Exception as exc:  # noqa: BLE001
        raise ModelProcessingError(f"Failed to read 3D model: {exc}") from exc

    _notify_stage(stage_callback, "inspect", 30, "Inspecting mesh geometry and UV state")
    merged_mesh, mesh_names, material_count = _load_merged_mesh(loaded, trimesh)
    if merged_mesh is None or len(merged_mesh.vertices) == 0 or len(merged_mesh.faces) == 0:
        raise ModelProcessingError("Uploaded file contains no polygon mesh.")

    merged_mesh.remove_unreferenced_vertices()

    bbox_extents = merged_mesh.bounding_box.extents.tolist()
    surface_area = float(merged_mesh.area)
    if surface_area <= 0:
        raise ModelProcessingError("Mesh surface area is invalid.")

    warnings: list[str] = []
    uv_source = "embedded"
    has_original_uv = _has_viable_uv(merged_mesh, numpy)
    if not has_original_uv:
        _notify_stage(stage_callback, "unwrap_if_needed", 55, "Generating UV layout for mesh")
        uv_source = "auto_unwrapped"
        warnings.append("Original UV is missing or unusable; auto unwrap applied.")
        merged_mesh = _auto_unwrap_mesh(merged_mesh, numpy, trimesh, xatlas)

    if not _has_viable_uv(merged_mesh, numpy):
        raise ModelProcessingError("Model UV is still invalid after processing.")

    _notify_stage(stage_callback, "export_uv_png", 80, "Exporting UV template and normalized model")
    uv = _extract_uv(merged_mesh, numpy)
    normalized_model_path = create_normalized_model_path(session_id=session_id, model_id=model_id)
    uv_template_path = create_uv_template_path(session_id=session_id, model_id=model_id)

    # When the upload already contains usable UVs in a GLB, keep an exact copy of
    # the source model as the locked painting/retexture artifact. Re-exporting via
    # trimesh can slightly restructure materials or embedded payloads, which has
    # proven less compatible with downstream retexture services even when the UVs
    # themselves remain valid.
    if has_original_uv and uv_source == "embedded" and suffix == ".glb":
        normalized_model_path.write_bytes(source_path.read_bytes())
    else:
        try:
            export_blob = merged_mesh.export(file_type="glb")
        except Exception as exc:  # noqa: BLE001
            raise ModelProcessingError(f"Failed to export normalized GLB: {exc}") from exc
        if isinstance(export_blob, str):
            export_blob = export_blob.encode("utf-8")
        normalized_model_path.write_bytes(export_blob)

    embedded_texture_image = _extract_embedded_texture_image(loaded, numpy_module=numpy)
    uv_template_mode = "embedded_texture" if embedded_texture_image is not None else "outline_template"
    if embedded_texture_image is not None:
        uv_width, uv_height, paintable_uv_pixels = _save_embedded_texture_image(
            image=embedded_texture_image,
            output_path=uv_template_path,
            image_module=image_module,
            numpy_module=numpy,
        )
    else:
        uv_width, uv_height = get_uv_size(product_category)
        paintable_uv_pixels = _render_uv_template(
            uv=uv,
            faces=numpy.asarray(merged_mesh.faces, dtype=numpy.int64),
            output_path=uv_template_path,
            width=uv_width,
            height=uv_height,
            image_module=image_module,
            image_draw_module=image_draw_module,
            numpy_module=numpy,
        )
    if paintable_uv_pixels <= 0:
        raise ModelProcessingError("UV layout contains no paintable area.")

    _notify_stage(stage_callback, "persist_or_transient_finalize", 95, "Finalizing processed model asset")
    mesh_to_region = {name: name for name in mesh_names} if mesh_names else {"merged_surface": "merged_surface"}
    mapping_meta = {
        "inspection": {
            "file_name": original_filename,
            "format": suffix.lstrip("."),
            "mesh_count": len(mesh_names) if mesh_names else 1,
            "material_count": material_count,
            "bbox_m": [round(float(value), 6) for value in bbox_extents],
            "has_original_uv": has_original_uv,
            "uv_source": uv_source,
            "uv_template_mode": uv_template_mode,
            "warnings": warnings,
        },
        "uv_spec": {
            "width": uv_width,
            "height": uv_height,
            "paintable_uv_pixels": paintable_uv_pixels,
        },
        "mesh_to_region": mesh_to_region,
    }

    return ProcessedModelAsset(
        model_url=to_model_url(normalized_model_path),
        uv_template_url=to_uv_url(uv_template_path),
        surface_area_m2=surface_area,
        paintable_uv_pixels=paintable_uv_pixels,
        mapping_meta=mapping_meta,
        normalized_model_path=normalized_model_path,
        uv_template_path=uv_template_path,
    )


def _notify_stage(
    callback: Callable[[str, int, str], None] | None,
    pipeline_stage: str,
    progress: int,
    message: str,
) -> None:
    if callback is None:
        return
    callback(pipeline_stage, progress, message)


def _require_module(module_name: str) -> Any:
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise ModelProcessingError(
            f"Missing backend dependency '{module_name}'. Run backend dependency sync before uploading models."
        ) from exc


def _require_pillow() -> tuple[Any, Any]:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ModelProcessingError(
            "Missing backend dependency 'Pillow'. Run backend dependency sync before uploading models."
        ) from exc
    return Image, ImageDraw


def _load_merged_mesh(loaded: Any, trimesh: Any) -> tuple[Any | None, list[str], int]:
    if isinstance(loaded, trimesh.Trimesh):
        mesh_names = ["uploaded_mesh"]
        material_count = 1 if getattr(loaded.visual, "material", None) is not None else 0
        return loaded.copy(), mesh_names, material_count

    if not isinstance(loaded, trimesh.Scene):
        return None, [], 0

    geometry_names = [str(name) for name in loaded.geometry.keys()]
    material_count = 0
    for mesh in loaded.geometry.values():
        if getattr(mesh.visual, "material", None) is not None:
            material_count += 1

    try:
        merged = loaded.to_geometry()
    except Exception as exc:  # noqa: BLE001
        raise ModelProcessingError(f"Failed to merge model scene: {exc}") from exc

    if isinstance(merged, list):
        merged = trimesh.util.concatenate([item for item in merged if isinstance(item, trimesh.Trimesh)])
    if not isinstance(merged, trimesh.Trimesh):
        return None, geometry_names, material_count
    return merged, geometry_names, material_count


def _extract_uv(mesh: Any, numpy_module: Any) -> Any:
    uv = getattr(mesh.visual, "uv", None)
    if uv is None:
        raise ModelProcessingError("Model has no UV coordinates.")
    return numpy_module.asarray(uv, dtype=numpy_module.float64)


def _has_viable_uv(mesh: Any, numpy_module: Any) -> bool:
    try:
        uv = _extract_uv(mesh, numpy_module)
    except ModelProcessingError:
        return False

    if uv.ndim != 2 or uv.shape[1] != 2 or len(uv) != len(mesh.vertices):
        return False
    if not numpy_module.isfinite(uv).all():
        return False

    uv_min = uv.min(axis=0)
    uv_max = uv.max(axis=0)
    if float(uv_min.min()) < -1e-4 or float(uv_max.max()) > 1.0001:
        return False

    triangle_uv = uv[numpy_module.asarray(mesh.faces, dtype=numpy_module.int64)]
    edge_a = triangle_uv[:, 1] - triangle_uv[:, 0]
    edge_b = triangle_uv[:, 2] - triangle_uv[:, 0]
    area = numpy_module.abs(edge_a[:, 0] * edge_b[:, 1] - edge_a[:, 1] * edge_b[:, 0]) * 0.5
    return bool((area > 1e-10).any())


def _auto_unwrap_mesh(mesh: Any, numpy_module: Any, trimesh: Any, xatlas_module: Any) -> Any:
    try:
        vertex_mapping, remapped_faces, uvs = xatlas_module.parametrize(
            numpy_module.asarray(mesh.vertices, dtype=numpy_module.float32),
            numpy_module.asarray(mesh.faces, dtype=numpy_module.uint32),
        )
    except Exception as exc:  # noqa: BLE001
        raise ModelProcessingError(f"Automatic UV unwrap failed: {exc}") from exc

    new_vertices = numpy_module.asarray(mesh.vertices, dtype=numpy_module.float64)[vertex_mapping]
    new_faces = numpy_module.asarray(remapped_faces, dtype=numpy_module.int64)
    new_uvs = numpy_module.asarray(uvs, dtype=numpy_module.float64)
    if len(new_vertices) == 0 or len(new_faces) == 0 or len(new_uvs) == 0:
        raise ModelProcessingError("Automatic UV unwrap produced an empty result.")

    unwrapped = trimesh.Trimesh(vertices=new_vertices, faces=new_faces, process=False)
    unwrapped.visual = trimesh.visual.texture.TextureVisuals(uv=new_uvs)
    return unwrapped


def _extract_embedded_texture_image(loaded: Any, *, numpy_module: Any) -> Any | None:
    geometries = []
    if hasattr(loaded, "geometry") and isinstance(getattr(loaded, "geometry"), dict):
        geometries = list(loaded.geometry.values())
    else:
        geometries = [loaded]

    for geometry in geometries:
        visual = getattr(geometry, "visual", None)
        if visual is None:
            continue

        material = getattr(visual, "material", None)
        image = _extract_texture_from_material(material)
        if image is not None and _is_meaningful_texture_image(image, numpy_module=numpy_module):
            return image

        visual_image = getattr(visual, "image", None)
        if visual_image is not None and _is_meaningful_texture_image(visual_image, numpy_module=numpy_module):
            return visual_image

    return None


def _is_meaningful_texture_image(image: Any, *, numpy_module: Any) -> bool:
    if image is None or not hasattr(image, "convert"):
        return False

    rgba_image = image.convert("RGBA")
    width, height = rgba_image.size
    if width <= 0 or height <= 0:
        return False

    pixel_array = numpy_module.asarray(rgba_image)
    if pixel_array.size == 0:
        return False

    flattened = pixel_array.reshape(-1, pixel_array.shape[-1])
    unique_pixels = numpy_module.unique(flattened, axis=0)

    # Trimesh may synthesize a tiny solid-color placeholder texture when a mesh has UVs
    # but no actual embedded texture image. That should not replace the real UV template.
    if width * height <= 16 and len(unique_pixels) == 1:
        return False

    return True


def _extract_texture_from_material(material: Any) -> Any | None:
    if material is None:
        return None

    direct_image = getattr(material, "image", None)
    if direct_image is not None:
        return direct_image

    texture_attr_names = (
        "baseColorTexture",
        "emissiveTexture",
        "metallicRoughnessTexture",
        "normalTexture",
        "occlusionTexture",
    )
    for attr_name in texture_attr_names:
        texture = getattr(material, attr_name, None)
        if texture is not None:
            return texture

    data = getattr(material, "_data", None)
    if isinstance(data, dict):
        for key in texture_attr_names:
            texture = data.get(key)
            if texture is not None:
                return texture
    return None


def _save_embedded_texture_image(*, image: Any, output_path: Path, image_module: Any, numpy_module: Any) -> tuple[int, int, int]:
    if image is None:
        raise ModelProcessingError("Embedded texture image is missing.")

    pil_image = image if hasattr(image, "save") else image_module.open(image)
    rgba_image = pil_image.convert("RGBA")
    rgba_image.save(output_path)
    width, height = rgba_image.size
    alpha_channel = numpy_module.asarray(rgba_image.getchannel("A"))
    paintable_uv_pixels = int((alpha_channel > 0).sum())
    if paintable_uv_pixels <= 0:
        paintable_uv_pixels = int(width * height)
    return width, height, paintable_uv_pixels


def _render_uv_template(
    *,
    uv: Any,
    faces: Any,
    output_path: Path,
    width: int,
    height: int,
    image_module: Any,
    image_draw_module: Any,
    numpy_module: Any,
) -> int:
    rgb_image = image_module.new("RGB", (width, height), (255, 255, 255))
    mask_image = image_module.new("L", (width, height), 0)
    rgb_draw = image_draw_module.Draw(rgb_image)
    mask_draw = image_draw_module.Draw(mask_image)

    for face in faces:
        triangle = uv[face]
        points = [
            (
                float(triangle[index][0]) * (width - 1),
                (1.0 - float(triangle[index][1])) * (height - 1),
            )
            for index in range(3)
        ]
        mask_draw.polygon(points, fill=255)

    for start, end in _extract_uv_island_outline_segments(uv=uv, faces=faces, width=width, height=height):
        rgb_draw.line([start, end], fill=(71, 85, 105), width=3)

    rgb_image.save(output_path)
    mask_array = numpy_module.asarray(mask_image)
    return int((mask_array > 0).sum())


def _extract_uv_island_outline_segments(*, uv: Any, faces: Any, width: int, height: int) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    edge_counts: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
    edge_points: dict[tuple[tuple[int, int], tuple[int, int]], tuple[tuple[float, float], tuple[float, float]]] = {}

    for face in faces:
        triangle = uv[face]
        face_points = [_uv_to_pixel_point(triangle[index], width=width, height=height) for index in range(3)]
        for start_index, end_index in ((0, 1), (1, 2), (2, 0)):
            start = face_points[start_index]
            end = face_points[end_index]
            key = _normalize_uv_edge_key(start, end)
            edge_counts[key] = edge_counts.get(key, 0) + 1
            edge_points.setdefault(key, (start, end))

    outline_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for key, count in edge_counts.items():
        if count == 1:
            outline_segments.append(edge_points[key])
    return outline_segments


def _uv_to_pixel_point(uv_point: Any, *, width: int, height: int) -> tuple[float, float]:
    return (
        float(uv_point[0]) * (width - 1),
        (1.0 - float(uv_point[1])) * (height - 1),
    )


def _normalize_uv_edge_key(
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[int, int], tuple[int, int]]:
    start_key = (int(round(start[0] * 1000)), int(round(start[1] * 1000)))
    end_key = (int(round(end[0] * 1000)), int(round(end[1] * 1000)))
    return (start_key, end_key) if start_key <= end_key else (end_key, start_key)
