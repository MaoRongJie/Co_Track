import time
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.api.ai as ai_api
from app.agents.creative_dialogue_and_image_agent import TexturePlanResult, TextureSchemePlan
from app.agents.providers.meshy_texture_provider import TexturedModelResult
from app.db.models import MeetingSession, ModelAsset, ModelGenerationTask, SessionMember
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


def create_demo_png_bytes(color: tuple[int, int, int, int] = (255, 255, 255, 255)) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_default_777777_invite_can_join() -> None:
    user = register_and_login("member_777777")
    joined = join_session(str(user["access_token"]), "777777", role="designer")
    assert joined["session"]["invite_code"] == "777777"
    assert joined["role"] == "designer"


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


def install_fake_stage3_review(monkeypatch) -> None:  # noqa: ANN001
    class FakeTextureProvider:
        pass

    class FakeReviewAssessment:
        def __init__(self, summary: str = "Passengers would likely see this scheme as calm and trustworthy.") -> None:
            self.summary = summary

        def as_dict(self) -> dict[str, object]:
            return {
                "status": "completed",
                "engineering": {
                    "paint_volume_kg": 87.0,
                    "color_zone_count": 3,
                    "masking_steps": 2,
                    "gradient_ratio_percent": 15.0,
                    "labor_hours": 134,
                    "process_steps": 5,
                    "curve_conformance_score": 83,
                    "material_cost_yuan": 29000,
                    "labor_cost_yuan": 22600,
                    "total_cost_yuan": 51600,
                    "color_variance_risk": "LOW",
                    "weather_durability": "A",
                    "maintenance_cycle_years": 6,
                },
                "passenger": {
                    "scores": {
                        "first_impression": 8,
                        "safety_trust": 8,
                        "comfort_cleanliness": 8,
                        "perceived_quality": 8,
                        "speed_motion": 7,
                        "emotion_character": 7,
                    },
                    "overall_score": 7.9,
                    "summary": self.summary,
                    "strengths": ["The scheme stays readable as the train approaches the platform."],
                    "issues": ["The scheme still leaves room for a stronger signature accent."],
                    "suggestions": ["Add one brighter contrast cue so the train is easier to remember."],
                },
                "recommendation": "recommended",
                "source": "llm",
                "model_name": "gpt-4o",
                "error_message": None,
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = provider
            return FakeReviewAssessment(summary=f"{context.scheme_id} feels shared, clear, and polished.")

    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())


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


def test_advancing_from_designing_to_stage3_requires_shared_results(monkeypatch) -> None:  # noqa: ANN001
    install_fake_stage3_review(monkeypatch)

    host = register_and_login("host_stage3_share_required")
    token = host["access_token"]
    meeting = create_session(token, "Stage3 Share Required Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("stage3_gate.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    design_stage = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(token))
    assert design_stage.status_code == 200
    assert design_stage.json()["stage"] == "DESIGNING"

    blocked = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(token))
    assert blocked.status_code == 400
    assert "Share at least one completed textured result" in blocked.json()["detail"]


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


def test_host_can_revert_designing_stage_back_to_model_preparing() -> None:
    host = register_and_login("host_revert_designing")
    token = host["access_token"]
    meeting = create_session(token, "Revert Designing Session")
    session_id = meeting["id"]

    with SessionLocal() as db:
        persisted = db.execute(
            select(MeetingSession).where(MeetingSession.id == session_id)
        ).scalar_one()
        persisted.stage = "DESIGNING"
        db.commit()

    reverted = client.post(f"/api/sessions/{session_id}/revert", headers=auth_header(token))
    assert reverted.status_code == 200
    assert reverted.json()["stage"] == "MODEL_PREPARING"


def test_apply_edited_texture_prefers_current_scheme_model_over_locked_base(monkeypatch) -> None:  # noqa: ANN001
    captured_reference: dict[str, str] = {}

    class FakeReviewAssessment:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "completed",
                "engineering": {
                    "paint_volume_kg": 88.4,
                    "color_zone_count": 3,
                    "masking_steps": 2,
                    "gradient_ratio_percent": 18.0,
                    "labor_hours": 136,
                    "process_steps": 5,
                    "curve_conformance_score": 78,
                    "material_cost_yuan": 28400,
                    "labor_cost_yuan": 22440,
                    "total_cost_yuan": 50840,
                    "color_variance_risk": "MEDIUM",
                    "weather_durability": "B",
                    "maintenance_cycle_years": 5,
                },
                "passenger": {
                    "scores": {
                        "first_impression": 8,
                        "safety_trust": 8,
                        "comfort_cleanliness": 7,
                        "perceived_quality": 8,
                        "speed_motion": 7,
                        "emotion_character": 7,
                    },
                    "overall_score": 7.8,
                    "summary": "It looks calm, premium, and distinctly seasonal from a passenger point of view.",
                    "strengths": [
                        "The cool palette feels calm and steady for a longer ride.",
                        "The bright blue band reads clearly from mid-platform distances.",
                    ],
                    "issues": [
                        "The design feels a little cautious before it feels exciting.",
                        "The winter story is clear but not especially bold.",
                    ],
                    "suggestions": [
                        "Add one brighter accent so the train is easier to remember.",
                        "Push the directional graphics slightly more so it feels faster on arrival.",
                    ],
                },
                "recommendation": "recommended",
                "source": "llm",
                "model_name": "gpt-4o",
                "error_message": None,
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = (provider, context)
            return FakeReviewAssessment()

    def fake_apply_edited_texture_to_model(**kwargs):  # noqa: ANN001
        captured_reference["base_model_reference"] = kwargs["base_model_reference"]
        return ai_api.EditedTextureApplicationResult(
            model_url="/files/models/fake_edited.glb",
            base_color_url="/files/textures/fake_edited.png",
            applied_at="2026-01-01T00:00:00Z",
        )

    monkeypatch.setattr(ai_api, "apply_edited_texture_to_model", fake_apply_edited_texture_to_model)
    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())

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
                    "result_id": "result_scheme_1",
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
        data={"session_id": str(session_id), "result_id": "result_scheme_1"},
        files={"edited_base_color": ("edited.png", buffer.getvalue(), "image/png")},
    )
    assert applied.status_code == 200
    assert captured_reference["base_model_reference"] == "/files/models/current_textured.glb"
    updated_model = applied.json()["models"][0]
    assert updated_model["review_assessment"]["recommendation"] == "recommended"
    assert updated_model["review_assessment"]["engineering"]["labor_hours"] == 136
    assert updated_model["review_assessment"]["passenger"]["summary"] == (
        "It looks calm, premium, and distinctly seasonal from a passenger point of view."
    )


def test_refresh_texture_review_endpoint_recomputes_selected_scheme_only(monkeypatch) -> None:  # noqa: ANN001
    class FakeReviewAssessment:
        def __init__(self, scheme_id: str) -> None:
            self.scheme_id = scheme_id

        def as_dict(self) -> dict[str, object]:
            labor_hours = 133 if self.scheme_id == "scheme_1" else 177
            recommendation = "recommended" if self.scheme_id == "scheme_1" else "highly_recommended"
            return {
                "status": "completed",
                "engineering": {
                    "paint_volume_kg": 84.2,
                    "color_zone_count": 3,
                    "masking_steps": 2,
                    "gradient_ratio_percent": 19.0,
                    "labor_hours": labor_hours,
                    "process_steps": 5,
                    "curve_conformance_score": 82,
                    "material_cost_yuan": 30800,
                    "labor_cost_yuan": 25110,
                    "total_cost_yuan": 55910,
                    "color_variance_risk": "MEDIUM",
                    "weather_durability": "B",
                    "maintenance_cycle_years": 5,
                },
                "passenger": {
                    "scores": {
                        "first_impression": 8,
                        "safety_trust": 8,
                        "comfort_cleanliness": 8,
                        "perceived_quality": 8,
                        "speed_motion": 8,
                        "emotion_character": 7,
                    },
                    "overall_score": 8.0,
                    "summary": f"{self.scheme_id} feels legible, contemporary, and broadly appealing.",
                    "strengths": [
                        f"{self.scheme_id} stays highly visible from the platform edge.",
                        f"{self.scheme_id} feels polished enough to invite passenger photos.",
                    ],
                    "issues": [
                        f"{self.scheme_id} still feels slightly safer than it feels expressive.",
                        f"{self.scheme_id} could be a little more emotionally distinctive.",
                    ],
                    "suggestions": [
                        f"Give {self.scheme_id} one sharper signature accent to improve memorability.",
                        f"Push the directional lines on {self.scheme_id} a little more to suggest speed.",
                    ],
                },
                "recommendation": recommendation,
                "source": "llm",
                "model_name": "gpt-4o",
                "error_message": None,
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = provider
            return FakeReviewAssessment(context.scheme_id)

    class FakeProvider:
        pass

    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_refresh_selected_review")
    token = host["access_token"]
    meeting = create_session(token, "Refresh Selected Review Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("refresh_selected.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
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
                    "result_id": "result_scheme_1",
                    "scheme_id": "scheme_1",
                    "title": "Scheme 1",
                    "prompt_text": "Prompt 1",
                    "status": "completed",
                    "textured_model_url": "/files/models/review_scheme_1.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/review_scheme_1.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "review_assessment": None,
                    "edited_variant": None,
                    "meshy_task_id": "task_1",
                    "error_message": None,
                },
                {
                    "result_id": "result_scheme_2",
                    "scheme_id": "scheme_2",
                    "title": "Scheme 2",
                    "prompt_text": "Prompt 2",
                    "status": "completed",
                    "textured_model_url": "/files/models/review_scheme_2.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/review_scheme_2.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "review_assessment": None,
                    "edited_variant": None,
                    "meshy_task_id": "task_2",
                    "error_message": None,
                },
            ]
        }
        db.commit()

    refreshed = client.post(
        "/api/ai/texture-plan/refresh-review",
        headers=auth_header(token),
        json={"session_id": session_id, "result_id": "result_scheme_2"},
    )
    assert refreshed.status_code == 200
    models = refreshed.json()["models"]
    assert len(models) == 2
    assert models[0]["scheme_id"] == "scheme_1"
    assert models[0]["review_assessment"] is None
    assert models[1]["scheme_id"] == "scheme_2"
    assert models[1]["review_assessment"]["status"] == "completed"
    assert models[1]["review_assessment"]["source"] == "llm"
    assert models[1]["review_assessment"]["model_name"] == "gpt-4o"
    assert models[1]["review_assessment"]["engineering"]["labor_hours"] == 177
    assert models[1]["review_assessment"]["recommendation"] == "highly_recommended"
    assert models[1]["review_assessment"]["passenger"]["summary"] == (
        "scheme_2 feels legible, contemporary, and broadly appealing."
    )

    with SessionLocal() as db:
        persisted = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        textured_models = persisted.texture_plan_json["textured_models"]

    assert textured_models[0]["review_assessment"] is None
    assert textured_models[1]["review_assessment"]["engineering"]["labor_hours"] == 177
    assert textured_models[1]["review_assessment"]["passenger"]["strengths"][0] == (
        "scheme_2 stays highly visible from the platform edge."
    )


def test_refresh_texture_review_clears_stored_review_when_call_fails(monkeypatch) -> None:  # noqa: ANN001
    class FakeFailedReviewAssessment:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "failed",
                "engineering": None,
                "passenger": None,
                "recommendation": None,
                "source": "failed",
                "model_name": "gpt-4o",
                "error_message": "OpenAI text API request failed",
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = (provider, context)
            return FakeFailedReviewAssessment()

    class FakeProvider:
        pass

    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_refresh_failed_review")
    token = host["access_token"]
    meeting = create_session(token, "Refresh Failed Review Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("refresh_failed.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
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
                    "result_id": "result_scheme_1",
                    "scheme_id": "scheme_1",
                    "title": "Scheme 1",
                    "prompt_text": "Prompt 1",
                    "status": "completed",
                    "textured_model_url": "/files/models/review_scheme_1.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/review_scheme_1.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "review_assessment": {
                        "status": "completed",
                        "engineering": {
                            "paint_volume_kg": 84.2,
                            "color_zone_count": 3,
                            "masking_steps": 2,
                            "gradient_ratio_percent": 19.0,
                            "labor_hours": 133,
                            "process_steps": 5,
                            "curve_conformance_score": 82,
                            "material_cost_yuan": 30800,
                            "labor_cost_yuan": 25110,
                            "total_cost_yuan": 55910,
                            "color_variance_risk": "MEDIUM",
                            "weather_durability": "B",
                            "maintenance_cycle_years": 5,
                        },
                        "passenger": {
                            "scores": {
                                "first_impression": 8,
                                "safety_trust": 8,
                                "comfort_cleanliness": 8,
                                "perceived_quality": 8,
                                "speed_motion": 7,
                                "emotion_character": 7,
                            },
                            "overall_score": 7.8,
                            "summary": "Passengers would likely see this as a polished seasonal update.",
                            "strengths": [
                                "The color blocks feel easy on the eyes for commuters.",
                                "The body graphics remain easy to pick out from a distance.",
                            ],
                            "issues": [
                                "The personality is appealing but still a little restrained.",
                                "The speed story could be pushed further.",
                            ],
                            "suggestions": [
                                "Add one crisper contrast accent to increase memorability.",
                                "Strengthen the directional graphics to make the train feel faster.",
                            ],
                        },
                        "recommendation": "recommended",
                        "source": "llm",
                        "model_name": "gpt-4o",
                        "error_message": None,
                    },
                    "edited_variant": None,
                    "meshy_task_id": "task_1",
                    "error_message": None,
                }
            ]
        }
        db.commit()

    refreshed = client.post(
        "/api/ai/texture-plan/refresh-review",
        headers=auth_header(token),
        json={"session_id": session_id, "result_id": "result_scheme_1"},
    )
    assert refreshed.status_code == 502
    assert refreshed.json()["detail"] == "OpenAI text API request failed"

    with SessionLocal() as db:
        persisted = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        textured_models = persisted.texture_plan_json["textured_models"]

    assert textured_models[0]["review_assessment"] is None


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


def test_generate_model_textures_appends_new_batch_instead_of_overwriting_existing_results(monkeypatch) -> None:  # noqa: ANN001
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

    class FakeReviewAssessment:
        def __init__(self, scheme_id: str) -> None:
            self.scheme_id = scheme_id

        def as_dict(self) -> dict[str, object]:
            return {
                "status": "completed",
                "engineering": {
                    "paint_volume_kg": 91.0,
                    "color_zone_count": 3,
                    "masking_steps": 2,
                    "gradient_ratio_percent": 18.0,
                    "labor_hours": 140,
                    "process_steps": 5,
                    "curve_conformance_score": 81,
                    "material_cost_yuan": 30200,
                    "labor_cost_yuan": 23400,
                    "total_cost_yuan": 53600,
                    "color_variance_risk": "MEDIUM",
                    "weather_durability": "B",
                    "maintenance_cycle_years": 5,
                },
                "passenger": {
                    "scores": {
                        "first_impression": 8,
                        "safety_trust": 8,
                        "comfort_cleanliness": 7,
                        "perceived_quality": 8,
                        "speed_motion": 7,
                        "emotion_character": 7,
                    },
                    "overall_score": 7.8,
                    "summary": f"{self.scheme_id} stays clear and appealing for platform passengers.",
                    "strengths": [f"{self.scheme_id} feels easy to recognize from a distance."],
                    "issues": [f"{self.scheme_id} could still feel a little more distinctive."],
                    "suggestions": [f"Give {self.scheme_id} one stronger signature accent."],
                },
                "recommendation": "recommended",
                "source": "llm",
                "model_name": "gpt-4o",
                "error_message": None,
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = provider
            return FakeReviewAssessment(context.scheme_id)

    class FakeMeshyProvider:
        def __init__(self) -> None:
            self.batch_counter = 0

        async def retexture_all_schemes(self, *, model_glb_path, schemes):  # noqa: ANN001
            _ = model_glb_path
            self.batch_counter += 1
            return [
                TexturedModelResult(
                    scheme_id=str(scheme["id"]),
                    status="completed",
                    textured_model_url=f"/files/models/batch_{self.batch_counter}_{scheme['id']}.glb",
                    meshy_task_id=f"batch_{self.batch_counter}_{scheme['id']}",
                    texture_maps={
                        "base_color": f"/files/textures/batch_{self.batch_counter}_{scheme['id']}.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    error_message=None,
                )
                for scheme in schemes
            ]

    fake_meshy_provider = FakeMeshyProvider()

    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeTextureRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "_engine_get_meshy_texture_provider", lambda: fake_meshy_provider)
    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())

    host = register_and_login("host_append_texture_results")
    token = host["access_token"]
    meeting = create_session(token, "Append Texture Results Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("append.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    first_generate = client.post(
        "/api/ai/texture-plan/generate-model-textures",
        headers=auth_header(token),
        data={"session_id": str(session_id), "source_text": "Generate the first three directions."},
    )
    assert first_generate.status_code == 200

    second_generate = client.post(
        "/api/ai/texture-plan/generate-model-textures",
        headers=auth_header(token),
        data={"session_id": str(session_id), "source_text": "Generate three more appended directions."},
    )
    assert second_generate.status_code == 200

    models_state = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert models_state.status_code == 200
    models = models_state.json()["models"]
    assert len(models) == 6
    assert all(model["status"] == "completed" for model in models)

    first_batch = models[:3]
    second_batch = models[3:]
    assert len({item["result_id"] for item in models}) == 6
    assert len({item["batch_id"] for item in first_batch}) == 1
    assert len({item["batch_id"] for item in second_batch}) == 1
    assert first_batch[0]["batch_id"] != second_batch[0]["batch_id"]
    assert [item["scheme_id"] for item in first_batch] == ["scheme_1", "scheme_2", "scheme_3"]
    assert [item["scheme_id"] for item in second_batch] == ["scheme_1", "scheme_2", "scheme_3"]
    assert all(item["source_type"] == "generated" for item in models)


def test_upload_textured_model_appends_uploaded_result_and_runs_review(monkeypatch) -> None:  # noqa: ANN001
    class FakeTextureProvider:
        pass

    class FakeReviewAssessment:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "completed",
                "engineering": {
                    "paint_volume_kg": 87.0,
                    "color_zone_count": 3,
                    "masking_steps": 2,
                    "gradient_ratio_percent": 15.0,
                    "labor_hours": 134,
                    "process_steps": 5,
                    "curve_conformance_score": 83,
                    "material_cost_yuan": 29000,
                    "labor_cost_yuan": 22600,
                    "total_cost_yuan": 51600,
                    "color_variance_risk": "LOW",
                    "weather_durability": "A",
                    "maintenance_cycle_years": 6,
                },
                "passenger": {
                    "scores": {
                        "first_impression": 8,
                        "safety_trust": 8,
                        "comfort_cleanliness": 8,
                        "perceived_quality": 8,
                        "speed_motion": 7,
                        "emotion_character": 7,
                    },
                    "overall_score": 7.9,
                    "summary": "Passengers would likely see this upload as calm, clean, and trustworthy.",
                    "strengths": ["The uploaded scheme stays readable as the train approaches the platform."],
                    "issues": ["The uploaded scheme still leaves room for a stronger signature accent."],
                    "suggestions": ["Add one brighter contrast cue so the upload is easier to remember."],
                },
                "recommendation": "recommended",
                "source": "llm",
                "model_name": "gpt-4o",
                "error_message": None,
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = (provider, context)
            return FakeReviewAssessment()

    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())

    host = register_and_login("host_upload_textured_result")
    token = host["access_token"]
    meeting = create_session(token, "Upload Textured Result Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("locked_base.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    upload_custom = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(token),
        data={"session_id": str(session_id), "title": "Custom Upload"},
        files={
            "model_file": ("custom.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("custom_base_color.png", create_demo_png_bytes((32, 144, 255, 255)), "image/png"),
        },
    )
    assert upload_custom.status_code == 200
    models = upload_custom.json()["models"]
    assert len(models) == 1
    uploaded_model = models[0]
    assert uploaded_model["title"] == "Custom Upload"
    assert uploaded_model["source_type"] == "uploaded"
    assert uploaded_model["batch_id"] is None
    assert uploaded_model["status"] == "completed"
    assert uploaded_model["result_id"].startswith("uploaded_")
    assert uploaded_model["scheme_id"] == "uploaded_custom"
    assert uploaded_model["review_assessment"]["status"] == "completed"
    assert uploaded_model["review_assessment"]["source"] == "llm"

    with SessionLocal() as db:
        persisted = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        textured_models = persisted.texture_plan_json["textured_models"]

    assert len(textured_models) == 1
    assert textured_models[0]["source_type"] == "uploaded"
    assert textured_models[0]["title"] == "Custom Upload"


def test_fetch_texture_models_does_not_backfill_missing_review_assessment(monkeypatch) -> None:  # noqa: ANN001
    host = register_and_login("host_review_backfill")
    token = host["access_token"]
    meeting = create_session(token, "Backfill Review Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("backfill.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
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
                    "title": "Existing Scheme",
                    "prompt_text": "Existing prompt",
                    "status": "completed",
                    "textured_model_url": "/files/models/existing_textured.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/retexture_scheme_1_019d9480-b61c-76db-8e51-65a98e1219de_base_color.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": None,
                    "review_assessment": None,
                    "meshy_task_id": "existing_task",
                    "error_message": None,
                }
            ]
        }
        db.commit()

    fetched = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert fetched.status_code == 200
    fetched_model = fetched.json()["models"][0]
    assert fetched_model["review_assessment"] is None


def test_fetch_texture_models_does_not_create_failed_review_on_read(monkeypatch) -> None:  # noqa: ANN001
    host = register_and_login("host_review_failed_no_mock")
    token = host["access_token"]
    meeting = create_session(token, "Failed Review Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("failed_review.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
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
                    "title": "Failed Review Scheme",
                    "prompt_text": "Existing prompt",
                    "status": "completed",
                    "textured_model_url": "/files/models/existing_textured.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/retexture_scheme_1_019d9480-b61c-76db-8e51-65a98e1219de_base_color.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": None,
                    "review_assessment": None,
                    "meshy_task_id": "existing_task",
                    "error_message": None,
                }
            ]
        }
        db.commit()

    fetched = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert fetched.status_code == 200
    fetched_model = fetched.json()["models"][0]
    assert fetched_model["review_assessment"] is None


def test_fetch_texture_models_does_not_refresh_legacy_review_assessment_without_source() -> None:
    host = register_and_login("host_review_refresh")
    token = host["access_token"]
    meeting = create_session(token, "Legacy Review Refresh Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("refresh.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
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
                    "title": "Legacy Scheme",
                    "prompt_text": "Legacy prompt",
                    "status": "completed",
                    "textured_model_url": "/files/models/existing_textured.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/retexture_scheme_1_019d9480-b61c-76db-8e51-65a98e1219de_base_color.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": None,
                    "review_assessment": {
                        "engineering": {
                            "paint_volume_kg": 999.0,
                            "color_zone_count": 7,
                            "masking_steps": 6,
                            "gradient_ratio_percent": 40.0,
                            "labor_hours": 2000,
                            "process_steps": 9,
                            "curve_conformance_score": 30,
                            "material_cost_yuan": 999999,
                            "labor_cost_yuan": 999999,
                            "total_cost_yuan": 1999998,
                            "color_variance_risk": "HIGH",
                            "weather_durability": "C",
                            "maintenance_cycle_years": 3,
                        },
                        "passenger": {
                            "ride_comfort": 10,
                            "platform_recognition": 10,
                            "social_appeal": 10,
                            "cultural_fit": 10,
                            "first_impression": 10,
                        },
                        "recommendation": "not_recommended",
                    },
                    "meshy_task_id": "legacy_task",
                    "error_message": None,
                }
            ]
        }
        db.commit()

    fetched = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert fetched.status_code == 200
    fetched_model = fetched.json()["models"][0]
    assert fetched_model["review_assessment"]["status"] == "failed"
    assert fetched_model["review_assessment"]["source"] == "failed"
    assert fetched_model["review_assessment"]["engineering"] is None
    assert fetched_model["review_assessment"]["passenger"] is None
    assert fetched_model["review_assessment"]["recommendation"] is None


def test_fetch_texture_models_marks_legacy_passenger_review_shape_as_failed() -> None:
    host = register_and_login("host_review_without_new_passenger_shape")
    token = host["access_token"]
    meeting = create_session(token, "Review Without New Passenger Shape Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("review_without_comments.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
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
                    "title": "Existing Review",
                    "prompt_text": "Existing prompt",
                    "status": "completed",
                    "textured_model_url": "/files/models/existing_review.glb",
                    "texture_maps": {
                        "base_color": "/files/textures/retexture_scheme_1_019d9480-b61c-76db-8e51-65a98e1219de_base_color.png",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": None,
                    "review_assessment": {
                        "status": "completed",
                        "source": "llm",
                        "engineering": {
                            "paint_volume_kg": 91.0,
                            "color_zone_count": 3,
                            "masking_steps": 2,
                            "gradient_ratio_percent": 17.0,
                            "labor_hours": 140,
                            "process_steps": 5,
                            "curve_conformance_score": 81,
                            "material_cost_yuan": 30000,
                            "labor_cost_yuan": 23000,
                            "total_cost_yuan": 53000,
                            "color_variance_risk": "MEDIUM",
                            "weather_durability": "B",
                            "maintenance_cycle_years": 5,
                        },
                        "passenger": {
                            "ride_comfort": 76,
                            "platform_recognition": 82,
                            "social_appeal": 78,
                            "cultural_fit": 74,
                            "first_impression": 80,
                        },
                        "recommendation": "recommended",
                        "model_name": "gpt-4o",
                        "error_message": None,
                    },
                    "meshy_task_id": "review_without_comments_task",
                    "error_message": None,
                }
            ]
        }
        db.commit()

    fetched = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(token),
        params={"session_id": session_id},
    )
    assert fetched.status_code == 200
    fetched_model = fetched.json()["models"][0]
    assert fetched_model["review_assessment"]["status"] == "failed"
    assert fetched_model["review_assessment"]["source"] == "failed"
    assert fetched_model["review_assessment"]["passenger"] is None
    assert fetched_model["review_assessment"]["recommendation"] is None


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

    class FakeReviewAssessment:
        def __init__(self, scheme_id: str) -> None:
            self.scheme_id = scheme_id

        def as_dict(self) -> dict[str, object]:
            return {
                "status": "completed",
                "engineering": {
                    "paint_volume_kg": 92.1,
                    "color_zone_count": 3,
                    "masking_steps": 2,
                    "gradient_ratio_percent": 16.5,
                    "labor_hours": 142,
                    "process_steps": 5,
                    "curve_conformance_score": 80,
                    "material_cost_yuan": 30120,
                    "labor_cost_yuan": 23430,
                    "total_cost_yuan": 53550,
                    "color_variance_risk": "MEDIUM",
                    "weather_durability": "B",
                    "maintenance_cycle_years": 5,
                },
                "passenger": {
                    "scores": {
                        "first_impression": 8,
                        "safety_trust": 8,
                        "comfort_cleanliness": 7,
                        "perceived_quality": 8,
                        "speed_motion": 7,
                        "emotion_character": 7,
                    },
                    "overall_score": 7.8,
                    "summary": f"{self.scheme_id} reads as clear, calm, and visually cohesive.",
                    "strengths": [
                        f"{self.scheme_id} feels calm and balanced for regular riders.",
                        f"{self.scheme_id} is easy to identify as it enters the station.",
                    ],
                    "issues": [
                        f"{self.scheme_id} could feel a little more distinctive from a distance.",
                        f"{self.scheme_id} is polished but not fully dynamic yet.",
                    ],
                    "suggestions": [
                        f"Give {self.scheme_id} one stronger accent so it is easier to remember.",
                        f"Sharpen the directional graphics on {self.scheme_id} to boost the sense of speed.",
                    ],
                },
                "recommendation": "recommended" if self.scheme_id != "scheme_3" else "acceptable",
                "source": "llm",
                "model_name": "gpt-4o",
                "error_message": None,
            }

    class FakeReviewService:
        async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
            _ = provider
            return FakeReviewAssessment(context.scheme_id)

    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeTextureRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeTextureProvider())
    monkeypatch.setattr(ai_api, "_engine_get_meshy_texture_provider", lambda: FakeMeshyProvider())
    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())

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
    assert parsed.json()["brief_json"]["why"]["coreExperienceIntent"]
    assert parsed.json()["brief_json"]["what"]["colorTendency"]
    assert parsed.json()["brief_json"]["how"]["craftTechConstraints"]
    assert isinstance(parsed.json()["brief_json"]["lockedItems"], list)
    assert isinstance(parsed.json()["brief_json"]["softDirections"], list)

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
    assert all(model["review_assessment"] is not None for model in texture_models_state.json()["models"])
    assert texture_models_state.json()["models"][0]["review_assessment"]["engineering"]["color_zone_count"] == 3
    assert texture_models_state.json()["models"][0]["review_assessment"]["passenger"]["summary"] == (
        "scheme_1 reads as clear, calm, and visually cohesive."
    )

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


def test_member_workspace_isolated_and_host_legacy_texture_plan_preserved(monkeypatch) -> None:  # noqa: ANN001
    install_fake_stage3_review(monkeypatch)

    host = register_and_login("host_member_workspace")
    host_token = host["access_token"]
    designer = register_and_login("designer_member_workspace")
    designer_token = designer["access_token"]

    meeting = create_session(host_token, "Member Workspace Session")
    session_id = meeting["id"]
    invite_code = meeting["invite_code"]
    join_session(designer_token, invite_code, role="designer")

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("workspace_base.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(host_token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(host_token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    uploaded_result = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "title": "Host Private Upload"},
        files={
            "model_file": ("host_private.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("host_private_base.png", create_demo_png_bytes((12, 80, 220, 255)), "image/png"),
        },
    )
    assert uploaded_result.status_code == 200
    host_models = uploaded_result.json()["models"]
    assert len(host_models) == 1
    assert host_models[0]["title"] == "Host Private Upload"

    designer_models = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(designer_token),
        params={"session_id": session_id},
    )
    assert designer_models.status_code == 200
    assert designer_models.json()["models"] == []

    with SessionLocal() as db:
        persisted_meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        host_member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == host["user"]["id"],
            )
        ).scalar_one()
        designer_member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == designer["user"]["id"],
            )
        ).scalar_one()

    assert isinstance(persisted_meeting.texture_plan_json, dict)
    assert len(persisted_meeting.texture_plan_json["textured_models"]) == 1
    assert isinstance(host_member.workspace_json, dict)
    assert len(host_member.workspace_json["textured_models"]) == 1
    assert host_member.workspace_json["textured_models"][0]["title"] == "Host Private Upload"
    assert designer_member.workspace_json in (None, {})


def test_share_and_import_results_create_independent_imported_copy(monkeypatch) -> None:  # noqa: ANN001
    install_fake_stage3_review(monkeypatch)

    host = register_and_login("host_share_import")
    host_token = host["access_token"]
    designer = register_and_login("designer_share_import")
    designer_token = designer["access_token"]

    meeting = create_session(host_token, "Share Import Session")
    session_id = meeting["id"]
    invite_code = meeting["invite_code"]
    join_session(designer_token, invite_code, role="designer")

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("share_base.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(host_token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(host_token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    uploaded_result = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "title": "Host Shared Upload"},
        files={
            "model_file": ("host_shared.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("host_shared_base.png", create_demo_png_bytes((0, 120, 200, 255)), "image/png"),
        },
    )
    assert uploaded_result.status_code == 200
    shared_result_id = uploaded_result.json()["models"][0]["result_id"]

    share_response = client.post(
        "/api/ai/texture-plan/share-results",
        headers=auth_header(host_token),
        json={"session_id": session_id, "result_ids": [shared_result_id]},
    )
    assert share_response.status_code == 200
    assert share_response.json()["shared_result_ids"] == [shared_result_id]

    members_response = client.get(
        f"/api/sessions/{session_id}/members",
        headers=auth_header(designer_token),
    )
    assert members_response.status_code == 200
    host_directory_entry = next(
        item for item in members_response.json()["members"] if item["user_id"] == host["user"]["id"]
    )
    assert host_directory_entry["public_share_count"] == 1
    assert host_directory_entry["can_live_sync"] is True

    shared_results = client.get(
        "/api/ai/texture-plan/shared-results",
        headers=auth_header(designer_token),
        params={"session_id": session_id, "member_user_id": host["user"]["id"]},
    )
    assert shared_results.status_code == 200
    assert len(shared_results.json()["models"]) == 1
    assert shared_results.json()["models"][0]["result_id"] == shared_result_id

    imported = client.post(
        "/api/ai/texture-plan/import-shared-results",
        headers=auth_header(designer_token),
        json={
            "session_id": session_id,
            "source_user_id": host["user"]["id"],
            "result_ids": [shared_result_id],
        },
    )
    assert imported.status_code == 200
    imported_models = imported.json()["models"]
    assert len(imported_models) == 1
    imported_model = imported_models[0]
    assert imported_model["source_type"] == "imported"
    assert imported_model["result_id"] != shared_result_id
    assert imported_model["family_id"] == shared_result_id
    assert imported_model["parent_result_id"] == shared_result_id
    assert imported_model["shared_origin"]["user_id"] == host["user"]["id"]
    assert imported_model["shared_origin"]["source_result_id"] == shared_result_id

    host_models = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert host_models.status_code == 200
    assert len(host_models.json()["models"]) == 1
    assert host_models.json()["models"][0]["source_type"] == "uploaded"


def test_stage3_shared_models_are_meeting_scoped(monkeypatch) -> None:  # noqa: ANN001
    install_fake_stage3_review(monkeypatch)

    host = register_and_login("host_stage3_shared_scope")
    host_token = host["access_token"]
    designer = register_and_login("designer_stage3_shared_scope")
    designer_token = designer["access_token"]

    meeting = create_session(host_token, "Stage3 Shared Scope Session")
    session_id = meeting["id"]
    invite_code = meeting["invite_code"]
    join_session(designer_token, invite_code, role="designer")

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("shared_scope.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(host_token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(host_token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    design_stage = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(host_token))
    assert design_stage.status_code == 200
    assert design_stage.json()["stage"] == "DESIGNING"

    host_uploaded_result = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "title": "Host Shared Candidate"},
        files={
            "model_file": ("host_shared_scope.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("host_shared_scope.png", create_demo_png_bytes((8, 120, 210, 255)), "image/png"),
        },
    )
    assert host_uploaded_result.status_code == 200
    host_result_id = host_uploaded_result.json()["models"][0]["result_id"]

    designer_uploaded_result = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(designer_token),
        data={"session_id": str(session_id), "title": "Designer Shared Candidate"},
        files={
            "model_file": ("designer_shared_scope.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("designer_shared_scope.png", create_demo_png_bytes((210, 120, 8, 255)), "image/png"),
        },
    )
    assert designer_uploaded_result.status_code == 200
    designer_result_id = designer_uploaded_result.json()["models"][0]["result_id"]

    host_share = client.post(
        "/api/ai/texture-plan/share-results",
        headers=auth_header(host_token),
        json={"session_id": session_id, "result_ids": [host_result_id]},
    )
    assert host_share.status_code == 200

    designer_share = client.post(
        "/api/ai/texture-plan/share-results",
        headers=auth_header(designer_token),
        json={"session_id": session_id, "result_ids": [designer_result_id]},
    )
    assert designer_share.status_code == 200

    stage3 = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(host_token))
    assert stage3.status_code == 200
    assert stage3.json()["stage"] == "COLLECTING"

    host_shared_models = client.get(
        "/api/ai/texture-plan/stage3-shared-models",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert host_shared_models.status_code == 200
    host_shared_payload = host_shared_models.json()
    assert host_shared_payload["status"] == "completed"
    assert [item["result_id"] for item in host_shared_payload["models"]] == [host_result_id, designer_result_id]
    assert host_shared_payload["models"][0]["submitted_by"]["user_id"] == host["user"]["id"]
    assert host_shared_payload["models"][1]["submitted_by"]["user_id"] == designer["user"]["id"]

    designer_shared_models = client.get(
        "/api/ai/texture-plan/stage3-shared-models",
        headers=auth_header(designer_token),
        params={"session_id": session_id},
    )
    assert designer_shared_models.status_code == 200
    assert [item["result_id"] for item in designer_shared_models.json()["models"]] == [
        host_result_id,
        designer_result_id,
    ]


def test_delete_textured_model_result_removes_shared_refs(monkeypatch) -> None:  # noqa: ANN001
    install_fake_stage3_review(monkeypatch)

    host = register_and_login("host_delete_textured_result")
    host_token = host["access_token"]

    meeting = create_session(host_token, "Delete Textured Result Session")
    session_id = meeting["id"]

    uploaded = client.post(
        "/api/models/upload",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "product_category": "high_speed_train"},
        files={"file": ("delete_base.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary")},
    )
    assert uploaded.status_code == 200
    ready_payload = wait_for_task_ready(host_token, uploaded.json()["task_id"])

    locked = client.post(
        f"/api/sessions/{session_id}/base-model/select",
        headers=auth_header(host_token),
        json={"base_model_id": ready_payload["result_model"]["id"]},
    )
    assert locked.status_code == 200

    design_stage = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(host_token))
    assert design_stage.status_code == 200
    assert design_stage.json()["stage"] == "DESIGNING"

    first_upload = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "title": "Delete Me"},
        files={
            "model_file": ("delete_me.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("delete_me.png", create_demo_png_bytes((12, 130, 220, 255)), "image/png"),
        },
    )
    assert first_upload.status_code == 200
    first_result_id = first_upload.json()["models"][0]["result_id"]

    second_upload = client.post(
        "/api/ai/texture-plan/upload-textured-model",
        headers=auth_header(host_token),
        data={"session_id": str(session_id), "title": "Keep Me"},
        files={
            "model_file": ("keep_me.glb", create_demo_glb_bytes(with_uv=True), "model/gltf-binary"),
            "base_color_file": ("keep_me.png", create_demo_png_bytes((220, 130, 12, 255)), "image/png"),
        },
    )
    assert second_upload.status_code == 200
    second_result_id = second_upload.json()["models"][-1]["result_id"]

    share_response = client.post(
        "/api/ai/texture-plan/share-results",
        headers=auth_header(host_token),
        json={"session_id": session_id, "result_ids": [first_result_id, second_result_id]},
    )
    assert share_response.status_code == 200
    assert share_response.json()["shared_result_ids"] == [first_result_id, second_result_id]

    stage3 = client.post(f"/api/sessions/{session_id}/advance", headers=auth_header(host_token))
    assert stage3.status_code == 200
    assert stage3.json()["stage"] == "COLLECTING"

    initial_shared_models = client.get(
        "/api/ai/texture-plan/stage3-shared-models",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert initial_shared_models.status_code == 200
    assert [item["result_id"] for item in initial_shared_models.json()["models"]] == [
        first_result_id,
        second_result_id,
    ]

    deleted = client.delete(
        f"/api/ai/texture-plan/models/{first_result_id}",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "completed"
    assert [item["result_id"] for item in deleted.json()["models"]] == [second_result_id]

    members_response = client.get(
        f"/api/sessions/{session_id}/members",
        headers=auth_header(host_token),
    )
    assert members_response.status_code == 200
    host_directory_entry = next(
        item for item in members_response.json()["members"] if item["user_id"] == host["user"]["id"]
    )
    assert host_directory_entry["shared_result_ids"] == [second_result_id]
    assert host_directory_entry["public_share_count"] == 1

    shared_models_after_delete = client.get(
        "/api/ai/texture-plan/stage3-shared-models",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert shared_models_after_delete.status_code == 200
    assert [item["result_id"] for item in shared_models_after_delete.json()["models"]] == [second_result_id]

    with SessionLocal() as db:
        member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == host["user"]["id"],
            )
        ).scalar_one()
        meeting_row = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()

    assert member.shared_result_ids_json == [second_result_id]
    assert [item["result_id"] for item in (meeting_row.stage3_shared_refs_json or [])] == [second_result_id]
