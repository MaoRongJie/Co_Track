import time
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.api.ai as ai_api
from app.agents.creative_dialogue_and_image_agent import TexturePlanResult, TextureSchemePlan
from app.agents.providers.meshy_texture_provider import TexturedModelResult
from app.db.models import MeetingSession, ModelAsset, ModelGenerationTask
from app.db.session import SessionLocal
from app.main import fastapi_app


client = TestClient(fastapi_app)


def register_and_login(name_prefix: str) -> dict[str, object]:
    suffix = uuid4().hex[:8]
    email = f"{name_prefix}_{suffix}@co-track.local"
    password = "Pass@123456"

    response = client.post(
        "/api/auth/register",
        json={"email": email, "name": f"{name_prefix}_{suffix}", "password": password},
    )
    response.raise_for_status()
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_session(token: str, name: str) -> dict[str, object]:
    response = client.post("/api/sessions", json={"name": name}, headers=auth_header(token))
    response.raise_for_status()
    return response.json()


def join_session(token: str, invite_code: str, role: str = "designer") -> dict[str, object]:
    response = client.post(
        "/api/sessions/join",
        json={"invite_code": invite_code, "role": role},
        headers=auth_header(token),
    )
    response.raise_for_status()
    return response.json()


def create_demo_glb_bytes(*, with_uv: bool, with_texture: bool = False) -> bytes:
    import numpy as np
    import trimesh
    from PIL import Image

    if with_uv:
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
        if with_texture:
            texture = Image.new("RGB", (32, 16), (220, 32, 32))
            mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, image=texture)
        else:
            mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv)
    else:
        mesh = trimesh.creation.box(extents=(1.0, 0.5, 0.25))

    exported = mesh.export(file_type="glb")
    return exported if isinstance(exported, bytes) else exported.encode("utf-8")


def wait_for_task_ready(token: str, task_id: int) -> dict[str, object]:
    last_payload: dict[str, object] | None = None
    for _ in range(40):
        response = client.get(f"/api/models/tasks/{task_id}", headers=auth_header(token))
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"ready", "failed"}:
            return payload
        time.sleep(0.25)
    raise AssertionError(f"Task {task_id} did not finish in time. Last payload: {last_payload}")


def test_upload_model_with_embedded_uv_creates_real_uv_asset() -> None:
    host = register_and_login("host_upload_uv")
    token = host["access_token"]
    meeting = create_session(token, "Upload UV Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("with_uv.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    task_id = uploaded.json()["task_id"]
    assert task_id > 0

    ready_payload = wait_for_task_ready(token, task_id)
    assert ready_payload["status"] == "ready"
    assert ready_payload["pipeline_stage"] == "ready"
    result_model = ready_payload["result_model"]
    assert result_model is not None
    assert result_model["mapping_meta"]["inspection"]["uv_source"] == "embedded"

    model_url = result_model["model_url"]
    uv_template_url = result_model["uv_template_url"]
    assert client.get(model_url, headers=auth_header(token)).status_code == 200
    uv_response = client.get(uv_template_url, headers=auth_header(token))
    assert uv_response.status_code == 200

    from PIL import Image

    uv_image = Image.open(BytesIO(uv_response.content)).convert("RGB")
    assert uv_image.getpixel((uv_image.width // 2, uv_image.height // 2)) == (255, 255, 255)


def test_upload_model_prefers_embedded_texture_image_as_uv_template() -> None:
    host = register_and_login("host_upload_texture")
    token = host["access_token"]
    meeting = create_session(token, "Upload Texture Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("with_texture.glb", create_demo_glb_bytes(with_uv=True, with_texture=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200

    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])
    assert ready_payload["status"] == "ready"
    result_model = ready_payload["result_model"]
    assert result_model is not None
    assert result_model["mapping_meta"]["inspection"]["uv_template_mode"] == "embedded_texture"
    assert result_model["mapping_meta"]["uv_spec"]["width"] == 32
    assert result_model["mapping_meta"]["uv_spec"]["height"] == 16

    from PIL import Image

    uv_response = client.get(result_model["uv_template_url"], headers=auth_header(token))
    assert uv_response.status_code == 200
    uv_image = Image.open(BytesIO(uv_response.content)).convert("RGB")
    assert uv_image.size == (32, 16)
    assert uv_image.getpixel((10, 8)) == (220, 32, 32)


def test_upload_model_without_uv_auto_unwraps() -> None:
    host = register_and_login("host_upload_unwrap")
    token = host["access_token"]
    meeting = create_session(token, "Upload Unwrap Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "automobile"},
        files={"file": ("without_uv.glb", create_demo_glb_bytes(with_uv=False), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200

    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])
    assert ready_payload["status"] == "ready"
    result_model = ready_payload["result_model"]
    assert result_model is not None
    assert result_model["mapping_meta"]["inspection"]["uv_source"] == "auto_unwrapped"
    assert result_model["paintable_uv_pixels"] > 0
    assert client.get(result_model["uv_template_url"], headers=auth_header(token)).status_code == 200


def test_upload_invalid_format_returns_error() -> None:
    host = register_and_login("host_invalid_upload")
    token = host["access_token"]
    meeting = create_session(token, "Invalid Upload Session")

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(meeting["id"]), "product_category": "high_speed_train"},
        files={"file": ("invalid.txt", b"not-a-model", "text/plain")},
    )
    assert uploaded.status_code == 400
    assert "GLB/GLTF" in uploaded.json()["detail"]


def test_permissions_for_upload_select_and_advance() -> None:
    host = register_and_login("host_perm")
    host_token = host["access_token"]
    designer = register_and_login("designer_perm")
    designer_token = designer["access_token"]

    meeting = create_session(host_token, "Permission Session")
    session_id = meeting["id"]
    invite_code = meeting["invite_code"]

    joined = client.post(
        "/api/sessions/join",
        headers=auth_header(designer_token),
        json={"invite_code": invite_code, "role": "designer"},
    )
    assert joined.status_code == 200

    forbidden_upload = client.post(
        "/api/models/upload",
        headers=auth_header(designer_token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("demo.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert forbidden_upload.status_code == 403

    host_upload = client.post(
        "/api/models/upload",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("demo.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert host_upload.status_code == 200
    ready_payload = wait_for_task_ready(host_token, host_upload.json()["task_id"])
    base_model_id = ready_payload["result_model"]["id"]

    forbidden_select = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(designer_token),
        json={"base_model_id": base_model_id},
    )
    assert forbidden_select.status_code == 403

    host_select = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(host_token),
        json={"base_model_id": base_model_id},
    )
    assert host_select.status_code == 200

    forbidden_advance = client.post(
        f"/api/sessions/{session_id}/advance",
        headers=auth_header(designer_token),
    )
    assert forbidden_advance.status_code == 403


def test_advance_requires_locked_base_model() -> None:
    host = register_and_login("host_advance")
    token = host["access_token"]
    meeting = create_session(token, "Advance Gate Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("advance.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])
    base_model_id = ready_payload["result_model"]["id"]

    blocked = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(token))
    assert blocked.status_code == 400

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": base_model_id},
    )
    assert locked.status_code == 200

    advanced = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(token))
    assert advanced.status_code == 200
    assert advanced.json()["stage"] == "DESIGNING"


def test_host_can_revert_reviewing_stage_back_to_designing() -> None:
    host = register_and_login("host_revert")
    token = host["access_token"]
    meeting = create_session(token, "Revert Session")
    session_id = meeting["id"]

    with SessionLocal() as db:
        persisted = db.execute(
            select(MeetingSession).where(MeetingSession.id == session_id)
        ).scalar_one()
        persisted.stage = "REVIEWING"
        db.commit()

    reverted = client.post(f"/api/sessions/{session_id}/revert", headers=auth_header(token))
    assert reverted.status_code == 200
    assert reverted.json()["stage"] == "DESIGNING"


def test_apply_edited_texture_prefers_current_scheme_model_over_locked_base(monkeypatch) -> None:  # noqa: ANN001
    captured_reference: dict[str, str] = {}

    def fake_apply_edited_texture_to_model(**kwargs):  # noqa: ANN001
        captured_reference["base_model_reference"] = kwargs["base_model_reference"]
        return ai_api.EditedTextureApplicationResult(
            model_url="/files/models/fake_edited.glb",
            base_color_url="/files/textures/fake_edited.png",
            applied_at="2026-01-01T00:00:00Z",
        )

    monkeypatch.setattr(ai_api, "apply_edited_texture_to_model", fake_apply_edited_texture_to_model)

    host = register_and_login("host_apply_edit")
    token = host["access_token"]
    meeting = create_session(token, "Apply Edited Texture Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("editable.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])
    base_model_id = ready_payload["result_model"]["id"]

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": base_model_id},
    )
    assert locked.status_code == 200

    with SessionLocal() as db:
        persisted = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        persisted.texture_plan_json = {
            "textured_models": [
                {
                    "scheme_id": "scheme_1",
                    "title": "Scheme 1",
                    "prompt_text": "Prompt 1",
                    "status": "completed",
                    "textured_model_url": "/files/models/current_textured.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/current_base_color.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": None,
                    "meshy_task_id": "task_1",
                    "error_message": None,
                }
            ]
        }
        db.commit()

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(buffer, format="PNG")
    buffer.seek(0)

    applied = client.post(
        "/api/ai/texture-plan/apply-edited-texture",
        headers=auth_header(token),
        data={"session_id": str(session_id), "scheme_id": "scheme_1"},
        files={"edited_base_color": ("edited.png", buffer.getvalue(), "image/png")},
    )
    assert applied.status_code == 200
    assert captured_reference["base_model_reference"] == "/files/models/current_textured.glb"


def test_generate_model_textures_uses_original_upload_glb_for_uploaded_model_with_original_uv(monkeypatch) -> None:  # noqa: ANN001
    captured_model_inputs: list[str] = []

    class FakeTextureRuntime:
        async def plan_texture_schemes(self, *, provider, context):  # noqa: ANN001
            _ = (provider, context)
            return TexturePlanResult(
                schemes=[
                    TextureSchemePlan(
                        id="scheme_1",
                        title="Scheme 1",
                        strategy="Clean",
                        prompt_text="Create a clean industrial texture direction.",
                        key_points=["clean"],
                    ),
                    TextureSchemePlan(
                        id="scheme_2",
                        title="Scheme 2",
                        strategy="Dynamic",
                        prompt_text="Create a dynamic industrial texture direction.",
                        key_points=["dynamic"],
                    ),
                    TextureSchemePlan(
                        id="scheme_3",
                        title="Scheme 3",
                        strategy="Layered",
                        prompt_text="Create a layered industrial texture direction.",
                        key_points=["layered"],
                    ),
                ],
                brief_keywords={},
                selected_image_keywords=[],
            )

    class FakeTextureProvider:
        pass

    class FakeMeshyProvider:
        async def retexture_all_schemes(self, *, model_glb_path, schemes):  # noqa: ANN001
            captured_model_inputs.append(model_glb_path)
            return [
                TexturedModelResult(
                    scheme_id=str(scheme["id"]),
                    status="completed",
                    textured_model_url=f"/files/models/mock_{scheme['id']}.glb",
                    meshy_task_id=f"mock_{scheme['id']}",
                    texture_maps=None,
                    error_message=None,
                )
                for scheme in schemes
            ]

    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeTextureRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "_engine_get_meshy_texture_provider", lambda: FakeMeshyProvider())

    host = register_and_login("host_meshy_locked_model")
    token = host["access_token"]
    meeting = create_session(token, "Meshy Locked Model Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("meshy_input.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    upload_task_id = uploaded.json()["task_id"]

    ready_payload = wait_for_task_ready(token, upload_task_id)
    assert ready_payload["status"] == "ready"
    result_model = ready_payload["result_model"]
    assert result_model is not None

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": result_model["id"]},
    )
    assert locked.status_code == 200

    generated = client.post(
        "/api/ai/texture-plan/generate-model-textures",
        headers=auth_header(token),
        data={"session_id": str(session_id), "source_text": "Generate three texture directions."},
    )
    assert generated.status_code == 200

    models_state = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert models_state.status_code == 200
    assert models_state.json()["status"] == "completed"

    with SessionLocal() as db:
        upload_task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == upload_task_id)).scalar_one()

    assert upload_task.source_path is not None
    assert captured_model_inputs == [upload_task.source_path]


def test_generate_model_textures_uses_locked_normalized_model_for_auto_unwrapped_upload(monkeypatch) -> None:  # noqa: ANN001
    captured_model_inputs: list[str] = []

    class FakeTextureRuntime:
        async def plan_texture_schemes(self, *, provider, context):  # noqa: ANN001
            _ = (provider, context)
            return TexturePlanResult(
                schemes=[
                    TextureSchemePlan(
                        id="scheme_1",
                        title="Scheme 1",
                        strategy="Clean",
                        prompt_text="Create a clean industrial texture direction.",
                        key_points=["clean"],
                    ),
                    TextureSchemePlan(
                        id="scheme_2",
                        title="Scheme 2",
                        strategy="Dynamic",
                        prompt_text="Create a dynamic industrial texture direction.",
                        key_points=["dynamic"],
                    ),
                    TextureSchemePlan(
                        id="scheme_3",
                        title="Scheme 3",
                        strategy="Layered",
                        prompt_text="Create a layered industrial texture direction.",
                        key_points=["layered"],
                    ),
                ],
                brief_keywords={},
                selected_image_keywords=[],
            )

    class FakeTextureProvider:
        pass

    class FakeMeshyProvider:
        async def retexture_all_schemes(self, *, model_glb_path, schemes):  # noqa: ANN001
            captured_model_inputs.append(model_glb_path)
            return [
                TexturedModelResult(
                    scheme_id=str(scheme["id"]),
                    status="completed",
                    textured_model_url=f"/files/models/mock_{scheme['id']}.glb",
                    meshy_task_id=f"mock_{scheme['id']}",
                    texture_maps=None,
                    error_message=None,
                )
                for scheme in schemes
            ]

    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeTextureRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "_engine_get_meshy_texture_provider", lambda: FakeMeshyProvider())

    host = register_and_login("host_meshy_auto_unwrap_model")
    token = host["access_token"]
    meeting = create_session(token, "Meshy Auto Unwrap Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "automobile"},
        files={"file": ("meshy_input_no_uv.glb", create_demo_glb_bytes(with_uv=False), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    upload_task_id = uploaded.json()["task_id"]

    ready_payload = wait_for_task_ready(token, upload_task_id)
    assert ready_payload["status"] == "ready"
    result_model = ready_payload["result_model"]
    assert result_model is not None
    assert result_model["mapping_meta"]["inspection"]["uv_source"] == "auto_unwrapped"

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": result_model["id"]},
    )
    assert locked.status_code == 200

    generated = client.post(
        "/api/ai/texture-plan/generate-model-textures",
        headers=auth_header(token),
        data={"session_id": str(session_id), "source_text": "Generate three texture directions."},
    )
    assert generated.status_code == 200

    models_state = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert models_state.status_code == 200
    assert models_state.json()["status"] == "completed"

    with SessionLocal() as db:
        upload_task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == upload_task_id)).scalar_one()

    assert upload_task.source_path is not None
    assert captured_model_inputs == [result_model["model_url"]]
    assert captured_model_inputs[0] != upload_task.source_path


def test_555555_upload_select_advance_persist(monkeypatch) -> None:  # noqa: ANN001
    class FakeTextureRuntime:
        async def plan_texture_schemes(self, *, provider, context):  # noqa: ANN001
            _ = (provider, context)
            return TexturePlanResult(
                schemes=[
                    TextureSchemePlan(
                        id="scheme_1",
                        title="Scheme 1",
                        strategy="Clean",
                        prompt_text="Create a clean industrial texture direction.",
                        key_points=["clean"],
                    ),
                    TextureSchemePlan(
                        id="scheme_2",
                        title="Scheme 2",
                        strategy="Dynamic",
                        prompt_text="Create a dynamic industrial texture direction.",
                        key_points=["dynamic"],
                    ),
                    TextureSchemePlan(
                        id="scheme_3",
                        title="Scheme 3",
                        strategy="Layered",
                        prompt_text="Create a layered industrial texture direction.",
                        key_points=["layered"],
                    ),
                ],
                brief_keywords={"theme": "winter"},
                selected_image_keywords=["snowflake", "speed"],
            )

    class FakeTextureProvider:
        pass

    class FakeMeshyProvider:
        async def retexture_all_schemes(self, *, model_glb_path, schemes):  # noqa: ANN001
            _ = model_glb_path
            return [
                TexturedModelResult(
                    scheme_id=str(scheme["id"]),
                    status="completed",
                    textured_model_url=f"/files/models/mock_{scheme['id']}.glb",
                    meshy_task_id=f"mock_{scheme['id']}",
                    texture_maps={
                        "base_color": f"/files/textures/{scheme['id']}_base_color.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    error_message=None,
                )
                for scheme in schemes
            ]

    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeTextureRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "_engine_get_meshy_texture_provider", lambda: FakeMeshyProvider())

    user = register_and_login("host_stage1_persist_upload")
    token = user["access_token"]
    meeting = create_session(token, "Persistent Upload Session")
    session_id = meeting["id"]
    design_goal = "Winter streamline body with blue white palette and snowflake accents."

    with SessionLocal() as db:
        db.execute(delete(ModelGenerationTask).where(ModelGenerationTask.session_id == session_id))
        db.execute(delete(ModelAsset).where(ModelAsset.session_id == session_id))
        meeting_before = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        meeting_before.stage = "LOBBY"
        meeting_before.design_goal_text = None
        meeting_before.product_category = None
        meeting_before.product_profile = {}
        meeting_before.brief_json = None
        meeting_before.texture_plan_json = None
        meeting_before.model_locked_at = None
        meeting_before.base_model_id = None
        db.commit()

    parsed = client.post(
        "/api/ai/parse-brief",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "design_goal": design_goal,
            "product_category": "high_speed_train",
        },
    )
    assert parsed.status_code == 200
    assert parsed.json()["brief_json"]["productCategory"] == "high_speed_train"

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("demo.glb", create_demo_glb_bytes(with_uv=False), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["task_id"] > 0

    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])
    assert ready_payload["status"] == "ready"
    result_model = ready_payload["result_model"]
    assert result_model is not None
    assert result_model["id"] > 0
    assert result_model["mapping_meta"]["inspection"]["uv_source"] == "auto_unwrapped"
    assert client.get(result_model["model_url"], headers=auth_header(token)).status_code == 200
    assert client.get(result_model["uv_template_url"], headers=auth_header(token)).status_code == 200

    selected = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": result_model["id"]},
    )
    assert selected.status_code == 200
    assert selected.json()["base_model_id"] == result_model["id"]

    base_model_state = client.get(f"/api/sessions/{session_id}/base-model", headers=auth_header(token))
    assert base_model_state.status_code == 200
    assert base_model_state.json()["base_model"]["id"] == result_model["id"]

    advanced = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(token))
    assert advanced.status_code == 200
    assert advanced.json()["stage"] == "DESIGNING"

    generated = client.post(
        "/api/ai/texture-plan/generate-model-textures",
        headers=auth_header(token),
        data={"session_id": str(session_id), "source_text": "Keep the texture crisp, aerodynamic, and wintry."},
    )
    assert generated.status_code == 200

    texture_plan_state = client.get(
        "/api/ai/texture-plan",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert texture_plan_state.status_code == 200
    assert texture_plan_state.json()["source_text"] == "Keep the texture crisp, aerodynamic, and wintry."

    texture_models_state = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert texture_models_state.status_code == 200
    assert texture_models_state.json()["status"] == "completed"
    assert len(texture_models_state.json()["models"]) == 3

    rejoined = join_session(token, meeting["invite_code"], role="host")
    assert rejoined["session"]["stage"] == "DESIGNING"
    assert rejoined["session"]["design_goal_text"] == design_goal
    assert rejoined["session"]["product_category"] == "high_speed_train"
    assert rejoined["session"]["brief_json"]["productCategory"] == "high_speed_train"

    with SessionLocal() as db:
        task_rows = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.session_id == session_id)).scalars().all()
        model_rows = db.execute(select(ModelAsset).where(ModelAsset.session_id == session_id)).scalars().all()
        meeting_after = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()

    assert len(task_rows) >= 1
    assert len(model_rows) >= 1
    assert meeting_after.stage == "DESIGNING"
    assert meeting_after.design_goal_text == design_goal
    assert meeting_after.product_category == "high_speed_train"
    assert isinstance(meeting_after.brief_json, dict)
    assert isinstance(meeting_after.texture_plan_json, dict)
    assert meeting_after.model_locked_at is not None
    assert meeting_after.base_model_id == result_model["id"]
