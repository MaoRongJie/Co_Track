from pathlib import Path
from uuid import uuid4

import trimesh
from PIL import Image
from pygltflib import GLTF2

from app.agents.providers.meshy_texture_provider import (
    MeshyTextureProvider,
    _build_data_uri,
    _build_sanitized_meshy_input_path,
)
from app.core.config import Settings
from app.model_processing import NORMALIZED_MODEL_DIR


def create_textured_quad_glb_bytes() -> bytes:
    import numpy as np

    vertices = np.array(
        [
            [-0.5, -0.5, 0.0],
            [0.5, -0.5, 0.0],
            [0.5, 0.5, 0.0],
            [-0.5, 0.5, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    uv = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ],
        dtype=np.float64,
    )

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=uv,
        image=Image.new("RGB", (32, 16), (220, 32, 32)),
    )
    exported = mesh.export(file_type="glb")
    return exported if isinstance(exported, bytes) else exported.encode("utf-8")


def test_resolve_model_input_uses_sanitized_uv_preserving_copy_for_relative_model_url() -> None:
    source_name = f"pytest_meshy_{uuid4().hex}.glb"
    source_path = NORMALIZED_MODEL_DIR / source_name
    sanitized_path = _build_sanitized_meshy_input_path(source_path)

    try:
        source_path.write_bytes(create_textured_quad_glb_bytes())
        provider = MeshyTextureProvider(Settings(meshy_api_key="test-key"))

        resolved = provider._resolve_model_input(f"/files/models/{source_name}")

        assert sanitized_path.is_file()
        assert sanitized_path != source_path
        assert resolved == _build_data_uri(str(sanitized_path))

        source_gltf = GLTF2().load_binary(str(source_path))
        sanitized_gltf = GLTF2().load_binary(str(sanitized_path))
        assert len(source_gltf.images or []) > 0
        assert len(source_gltf.textures or []) > 0
        assert len(sanitized_gltf.images or []) == 0
        assert len(sanitized_gltf.textures or []) == 0

        source_scene = trimesh.load(source_path, force="scene")
        sanitized_scene = trimesh.load(sanitized_path, force="scene")
        source_geometry = next(iter(source_scene.geometry.values()))
        sanitized_geometry = next(iter(sanitized_scene.geometry.values()))

        source_uv = getattr(source_geometry.visual, "uv", None)
        sanitized_uv = getattr(sanitized_geometry.visual, "uv", None)
        assert source_uv is not None
        assert sanitized_uv is not None
        assert len(source_geometry.vertices) == len(sanitized_geometry.vertices)
        assert len(source_geometry.faces) == len(sanitized_geometry.faces)
        assert source_uv.shape == sanitized_uv.shape
    finally:
        source_path.unlink(missing_ok=True)
        sanitized_path.unlink(missing_ok=True)
