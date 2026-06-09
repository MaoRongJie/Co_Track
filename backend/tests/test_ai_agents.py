import base64
import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.api.ai as ai_api
from app.agents.pattern_asset_agent import PatternAssetAgent
from app.agents.providers.aihubmix_media_provider import AiHubMixMediaProvider
from app.agents.providers.provider_protocols import ImageGenerationResult
from app.agents.stage3_review_agents import Stage3ReviewAssessment
from app.db.models import AiMessage, GeneratedImage, GeneratedMediaAsset, MeetingSession, SessionMember
from app.db.session import SessionLocal
from app.main import fastapi_app
from app.model_processing import TEXTURE_MAP_DIR, to_texture_url

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


def set_invite_code(session_id: int, invite_code: str) -> None:
    with SessionLocal() as db:
        existing = db.execute(select(MeetingSession).where(MeetingSession.invite_code == invite_code)).scalar_one_or_none()
        if existing is not None and existing.id != session_id:
            existing.invite_code = f"9{uuid4().hex[:7]}"

        meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        meeting.invite_code = invite_code
        db.commit()


def create_png_data_url(color: tuple[int, int, int, int]) -> str:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (24, 24), color).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def seed_stage4_media_asset(*, session_id: int, user_id: int, result_id: str = "result_stage4_1") -> tuple[int, int, str]:
    from PIL import Image

    file_path = TEXTURE_MAP_DIR / f"test_stage4_media_{uuid4().hex[:10]}.png"
    Image.new("RGBA", (24, 24), (120, 180, 240, 255)).save(file_path, format="PNG")
    media_url = to_texture_url(file_path)

    with SessionLocal() as db:
        image_row = GeneratedImage(
            session_id=session_id,
            user_id=user_id,
            prompt="Stage 4 still frame",
            style_hint=None,
            revised_prompt=None,
            image_url=media_url,
            provider="aihubmix",
            model_name="gpt-image-1",
            metadata_json={"kind": "stage4_scene_image"},
        )
        db.add(image_row)
        db.flush()

        media_row = GeneratedMediaAsset(
            session_id=session_id,
            user_id=user_id,
            result_id=result_id,
            scheme_name="Stage 4 Candidate",
            media_type="image",
            media_url=media_url,
            prompt="Stage 4 still frame",
            provider="aihubmix",
            model_name="gpt-image-1",
            prediction_id="pred_stage4_1",
            source_image_url=None,
            metadata_json={
                "kind": "stage4_scene_image",
                "generated_image_id": image_row.id,
            },
        )
        db.add(media_row)
        db.commit()
        db.refresh(image_row)
        db.refresh(media_row)
        return media_row.id, image_row.id, str(file_path)


def test_stage4_remote_video_download_uses_aihubmix_auth(monkeypatch) -> None:  # noqa: ANN001
    video_bytes = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    captured: dict[str, object] = {}

    class SettingsStub:
        aihubmix_api_key = "test-aihubmix-key"
        aihubmix_base_url = "https://aihubmix.com/v1"

    class FakeResponse:
        content = video_bytes
        headers = {"content-type": "video/mp4"}

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            return FakeResponse()

    monkeypatch.setattr(ai_api, "get_settings", lambda: SettingsStub())
    monkeypatch.setattr(ai_api.httpx, "AsyncClient", FakeAsyncClient)

    output_url = asyncio.run(
        ai_api._download_stage4_remote_media(
            session_id=321,
            media_url="https://aihubmix.com/v1/videos/video-id/content",
            media_type="video",
        )
    )
    output_path = TEXTURE_MAP_DIR / Path(output_url).name
    try:
        assert output_url.startswith("/files/textures/stage4_video_321_")
        assert output_url.endswith(".mp4")
        assert output_path.read_bytes() == video_bytes
        assert captured["headers"] == {"Authorization": "Bearer test-aihubmix-key"}
    finally:
        if output_path.exists():
            output_path.unlink()


def test_stage4_video_reference_embeds_local_texture_image() -> None:
    from PIL import Image

    file_path = TEXTURE_MAP_DIR / f"test_stage4_video_reference_{uuid4().hex[:10]}.jpg"
    Image.new("RGB", (24, 24), (40, 120, 210)).save(file_path, format="JPEG")
    try:
        data_url = ai_api._stage4_video_reference_image_url(
            f"http://127.0.0.1:8000/files/textures/{file_path.name}"
        )
        header, payload = data_url.split(",", 1)
        assert header == "data:image/jpeg;base64"
        assert base64.b64decode(payload)
        assert ai_api._stage4_video_reference_image_url("https://example.com/reference.jpg") == "https://example.com/reference.jpg"
    finally:
        if file_path.exists():
            file_path.unlink()


def test_aihubmix_seedance_video_payload_locks_first_frame(monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    class SettingsStub:
        aihubmix_api_key = "test-aihubmix-key"
        aihubmix_base_url = "https://aihubmix.com/v1"
        aihubmix_poll_timeout_sec = 30

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "id": "video-123",
                "status": "completed",
                "url": "https://aihubmix.com/v1/videos/video-123/content",
            }

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            captured["json"] = kwargs.get("json")
            return FakeResponse()

    monkeypatch.setattr(ai_api.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        AiHubMixMediaProvider(SettingsStub()).generate_video(
            image_url="data:image/png;base64,AAAA",
            prompt="镜头缓慢向前推进",
            duration=4,
            resolution="480p",
            ratio="16:9",
            generate_audio=False,
        )
    )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert result.prediction_id == "video-123"
    assert captured["url"] == "https://aihubmix.com/v1/videos"
    assert "extra_body" not in payload
    assert payload["generate_audio"] is False
    assert payload["ratio"] == "16:9"
    assert payload["duration"] == 4
    content = payload["content"]
    assert isinstance(content, list)
    assert content == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AAAA"},
            "role": "first_frame",
        }
    ]


def seed_pattern_texture_workspace(*, session_id: int, user_id: int, meshy_base_color: str, edited_base_color: str) -> None:
    with SessionLocal() as db:
        meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == user_id,
            )
        ).scalar_one()
        meeting.brief_json = {
            "why": {
                "coreExperienceIntent": "calm speed",
                "culturalBrandPositioning": "clean industrial confidence",
            },
            "what": {
                "colorTendency": "ice blue with warm sand accents",
                "visualStyleKeywords": ["streamlined", "calm", "precise"],
                "referenceImagery": ["wind ribbons", "glacier light"],
            },
            "how": {
                "craftTechConstraints": ["manufacturable large-scale coating"],
                "regulatoryConstraints": ["rail exterior readability"],
            },
            "theme": "winter industrial flow",
            "mainColors": ["#d7c18c", "#c7a17a", "#f7efe3"],
            "styleKeywords": ["streamlined", "minimal", "precise"],
            "designElements": ["ribbons", "tapered stripes"],
            "productCategory": "high_speed_train",
        }
        member.workspace_json = {
            "source_text": "winter high-speed train exterior",
            "document_name": None,
            "document_excerpt": "",
            "image_name": None,
            "image_content_keywords": [],
            "image_style_keywords": [],
            "selected_image_keywords": ["flow", "glacier", "ribbon"],
            "brief_keywords": {
                "theme": "winter industrial flow",
                "main_colors": ["#d7c18c", "#c7a17a"],
                "accent_colors": ["#f7efe3"],
                "style_keywords": ["streamlined", "minimal", "precise"],
                "design_elements": ["ribbons", "tapered stripes"],
                "constraints_hint": "Keep the pattern manufacturable and legible.",
            },
            "texture_generation_status": "completed",
            "textured_models": [
                {
                    "result_id": "result_pattern_1",
                    "batch_id": "batch_pattern",
                    "source_type": "generated",
                    "created_at": "2026-04-21T10:00:00Z",
                    "family_id": "result_pattern_1",
                    "parent_result_id": None,
                    "scheme_id": "scheme_1",
                    "title": "Winter Flow",
                    "prompt_text": "Build a clean winter livery direction with tapered ribbons and calm motion.",
                    "status": "completed",
                    "textured_model_url": "/files/models/fake.glb",
                    "texture_maps": {
                        "base_color": meshy_base_color,
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": {
                        "model_url": "/files/models/fake_edited.glb",
                        "base_color_url": edited_base_color,
                        "applied_at": "2026-04-21T10:05:00Z",
                    },
                    "review_assessment": None,
                    "meshy_task_id": "meshy_task_1",
                    "error_message": None,
                    "shared_origin": None,
                    "submitted_by": None,
                }
            ],
            "textured_models_updated_at": "2026-04-21T10:06:00Z",
            "updated_at": "2026-04-21T10:06:00Z",
        }
        db.commit()


def seed_review_texture_workspace(
    *,
    session_id: int,
    user_id: int,
    review_assessment: dict[str, object] | None = None,
) -> None:
    with SessionLocal() as db:
        meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one()
        member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == user_id,
            )
        ).scalar_one()
        meeting.brief_json = {
            "why": {
                "coreExperienceIntent": "reliable speed",
                "culturalBrandPositioning": "modern national confidence",
            },
            "what": {
                "colorTendency": "clean blue-white motion",
                "visualStyleKeywords": ["calm", "precise", "streamlined"],
                "referenceImagery": ["winter wind", "glacier trail"],
            },
            "how": {
                "craftTechConstraints": ["large-scale coating consistency"],
                "regulatoryConstraints": ["rail exterior readability"],
            },
            "productCategory": "high_speed_train",
        }
        member.workspace_json = {
            "texture_generation_status": "completed",
            "textured_models": [
                {
                    "result_id": "result_review_1",
                    "batch_id": "batch_review",
                    "source_type": "generated",
                    "created_at": "2026-04-21T10:00:00Z",
                    "family_id": "result_review_1",
                    "parent_result_id": None,
                    "scheme_id": "scheme_review_1",
                    "title": "Review Candidate",
                    "prompt_text": "Calm blue-white high-speed rail livery.",
                    "status": "completed",
                    "textured_model_url": "/files/models/fake.glb",
                    "texture_maps": {
                        "base_color": "data:image/png;base64,ZmFrZQ==",
                        "metallic": None,
                        "normal": None,
                        "roughness": None,
                    },
                    "edited_variant": None,
                    "review_assessment": review_assessment,
                    "meshy_task_id": "meshy_review_1",
                    "error_message": None,
                    "shared_origin": None,
                    "submitted_by": None,
                }
            ],
            "textured_models_updated_at": "2026-04-21T10:06:00Z",
            "updated_at": "2026-04-21T10:06:00Z",
        }
        db.commit()


class FakeProvider:
    model_name = "fake-text-model"
    image_model = "fake-image-model"

    async def generate_image(self, *, prompt: str, style_hint: str | None = None, reference_images=None):  # noqa: ANN001
        _ = (style_hint, reference_images)
        return [
            ImageGenerationResult(
                image_url="data:image/png;base64,ZmFrZQ==",
                revised_prompt=f"refined::{prompt}",
                provider_payload={"source": "fake"},
            )
        ]


class FakePatternProvider:
    model_name = "fake-pattern-text-model"
    vision_model = "fake-pattern-vision-model"
    image_model = "fake-pattern-image-model"

    def __init__(self) -> None:
        self.last_complete_json_user_message: str | None = None
        self.last_visual_image_url: str | None = None
        self.last_generate_payload: dict[str, object] | None = None

    async def complete_json(self, *, system_prompt: str, user_message: str, history=None, temperature: float = 0.2):  # noqa: ANN001
        _ = (system_prompt, history, temperature)
        self.last_complete_json_user_message = user_message
        return {
            "prompt": "Create one simple tapered ribbon decal asset, transparent background, no mockup.",
            "styleHint": "Minimal flat industrial decal.",
            "analysisSummary": "Pattern stays simple and follows the current texture rhythm.",
            "dominantColors": ["#d7c18c", "#c7a17a"],
        }

    async def complete_json_with_messages(self, *, messages, temperature: float = 0.2, model: str | None = None):  # noqa: ANN001
        _ = (temperature, model)
        user_message = next((item for item in messages if item.get("role") == "user"), {})
        content = user_message.get("content") if isinstance(user_message, dict) else []
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
                    self.last_visual_image_url = image.get("url")
                    break
        return {
            "shape_motifs": ["tapered ribbons", "glacier streaks"],
            "line_quality": "clean directional edges",
            "composition_rhythm": "one primary sweep with restrained layering",
            "complexity": "low",
            "palette_advice": ["#d7c18c", "#c7a17a"],
            "negative_constraints": ["no logo", "no text"],
            "visual_summary": "Keep the pattern compact and calm.",
        }

    async def generate_image(  # noqa: ANN001
        self,
        *,
        prompt: str,
        style_hint: str | None = None,
        reference_images=None,
        background: str | None = None,
        output_format: str | None = None,
    ):
        self.last_generate_payload = {
            "prompt": prompt,
            "style_hint": style_hint,
            "reference_images": reference_images,
            "background": background,
            "output_format": output_format,
        }
        return [
            ImageGenerationResult(
                image_url=create_png_data_url((0, 0, 0, 0)),
                revised_prompt=f"revised::{prompt}",
                provider_payload={"source": "fake-pattern"},
            )
        ]


class FakeReviewService:
    async def analyze_scheme(self, *, provider, context):  # noqa: ANN001
        _ = provider
        passenger_name = str((context.review_personas or {}).get("passenger", {}).get("display_name") or "Passenger")
        engineering_name = str((context.review_personas or {}).get("engineering", {}).get("display_name") or "Engineering")
        return Stage3ReviewAssessment(
            status="completed",
            engineering={
                "paint_volume_kg": 120.0,
                "color_zone_count": 3,
                "masking_steps": 3,
                "gradient_ratio_percent": 8.0,
                "labor_hours": 140,
                "process_steps": 5,
                "curve_conformance_score": 82,
                "material_cost_yuan": 24000,
                "labor_cost_yuan": 18000,
                "total_cost_yuan": 42000,
                "color_variance_risk": "LOW",
                "weather_durability": "A",
                "maintenance_cycle_years": 6,
            },
            passenger={
                "scores": {
                    "first_impression": 8,
                    "safety_trust": 8,
                    "comfort_cleanliness": 7,
                    "perceived_quality": 8,
                    "speed_motion": 8,
                    "emotion_character": 7,
                },
                "overall_score": 7.7,
                "summary": "Passengers would read it as clean, fast, and trustworthy.",
                "strengths": [
                    "The body graphics feel calm and easy to trust.",
                    "The motion direction stays clear at first glance.",
                ],
                "issues": [
                    "The design still feels slightly safe rather than iconic.",
                    "Some side graphics could be more memorable.",
                ],
                "suggestions": [
                    "Sharpen one accent band to improve recall.",
                    "Keep the calm base but add one clearer focal point.",
                ],
            },
            recommendation="recommended",
            source="llm",
            model_name="fake-review-model",
            settings_revision_used=context.settings_revision,
            persona_labels_used={
                "passenger": passenger_name,
                "engineering": engineering_name,
            },
        )


def test_generate_image_persist(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_ai_image")
    token = host["access_token"]
    meeting = create_session(token, "AI Image Session")
    session_id = meeting["id"]

    generated = client.post(
        "/api/ai/generate-image",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "prompt": "industrial winter exterior pattern",
            "style_hint": "clean industrial",
            "reference_images": [],
        },
    )
    assert generated.status_code == 200
    items = generated.json()["items"]
    assert len(items) == 1
    image_id = items[0]["id"]
    assert image_id > 0

    with SessionLocal() as db:
        row = db.execute(select(GeneratedImage).where(GeneratedImage.id == image_id)).scalar_one_or_none()
        assert row is not None
        assert row.session_id == session_id
        assert row.prompt == "industrial winter exterior pattern"


def test_generate_image_forbidden_for_non_member(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_ai_image_forbidden")
    host_token = host["access_token"]
    outsider = register_and_login("outsider_ai_image_forbidden")
    outsider_token = outsider["access_token"]

    meeting = create_session(host_token, "Forbidden AI Image Session")
    session_id = meeting["id"]

    forbidden = client.post(
        "/api/ai/generate-image",
        headers=auth_header(outsider_token),
        json={
            "session_id": session_id,
            "prompt": "winter train pattern",
            "style_hint": "clean industrial",
            "reference_images": [],
        },
    )
    assert forbidden.status_code == 403


def test_generate_image_persist_for_555555(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    user = register_and_login("member_image_555555")
    token = user["access_token"]
    meeting = create_session(token, "Image Persist Session")
    session_id = meeting["id"]

    with SessionLocal() as db:
        db.execute(delete(GeneratedImage).where(GeneratedImage.session_id == session_id))
        db.execute(delete(AiMessage).where(AiMessage.session_id == session_id))
        db.commit()

    generated = client.post(
        "/api/ai/generate-image",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "prompt": "ice blue streamline body pattern",
            "style_hint": "clean industrial",
            "reference_images": [],
        },
    )
    assert generated.status_code == 200
    items = generated.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] > 0

    with SessionLocal() as db:
        image_rows = db.execute(select(GeneratedImage).where(GeneratedImage.session_id == session_id)).scalars().all()
        message_rows = db.execute(select(AiMessage).where(AiMessage.session_id == session_id)).scalars().all()
        assert len(image_rows) >= 1
        assert len(message_rows) >= 1


def test_generate_image_persist_for_custom_invite(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    user = register_and_login("member_image_666666")
    token = user["access_token"]
    meeting = create_session(token, "Image Persist Custom Invite Session")
    session_id = meeting["id"]

    set_invite_code(session_id, "966666")
    with SessionLocal() as db:
        db.execute(delete(GeneratedImage).where(GeneratedImage.session_id == session_id))
        db.execute(delete(AiMessage).where(AiMessage.session_id == session_id))
        db.commit()

    generated = client.post(
        "/api/ai/generate-image",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "prompt": "platform recognition pattern",
            "style_hint": "clean industrial",
            "reference_images": [],
        },
    )
    assert generated.status_code == 200
    items = generated.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] > 0

    with SessionLocal() as db:
        image_rows = db.execute(select(GeneratedImage).where(GeneratedImage.session_id == session_id)).scalars().all()
        message_rows = db.execute(select(AiMessage).where(AiMessage.session_id == session_id)).scalars().all()
        assert len(image_rows) >= 1
        assert len(message_rows) >= 1


def test_generate_texture_pattern_persists_and_uses_user_prompt(monkeypatch) -> None:  # noqa: ANN001
    provider = FakePatternProvider()
    monkeypatch.setattr(ai_api, "get_pattern_image_provider", lambda: provider)
    monkeypatch.setattr(ai_api, "get_pattern_asset_agent", lambda: PatternAssetAgent())

    host = register_and_login("host_pattern_asset")
    token = host["access_token"]
    user_id = host["user"]["id"]
    meeting = create_session(token, "Pattern Asset Session")
    session_id = meeting["id"]

    meshy_base_color = create_png_data_url((215, 193, 140, 255))
    edited_base_color = create_png_data_url((199, 161, 122, 255))
    canvas_snapshot = create_png_data_url((247, 239, 227, 255))
    seed_pattern_texture_workspace(
        session_id=session_id,
        user_id=user_id,
        meshy_base_color=meshy_base_color,
        edited_base_color=edited_base_color,
    )

    generated = client.post(
        "/api/ai/texture-plan/generate-pattern",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "result_id": "result_pattern_1",
            "preview_mode": "meshy",
            "workspace_id": "workspace:test",
            "pattern_prompt_text": "像冰裂纹的流线几何贴花",
            "canvas_snapshot_data_url": canvas_snapshot,
        },
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["item"]["id"] > 0
    assert payload["source_result_id"] == "result_pattern_1"
    assert payload["pattern_prompt_text"] == "像冰裂纹的流线几何贴花"
    assert provider.last_visual_image_url == canvas_snapshot
    assert provider.last_generate_payload is not None
    assert provider.last_generate_payload["background"] == "transparent"
    assert provider.last_generate_payload["output_format"] == "png"
    assert provider.last_complete_json_user_message is not None
    assert "像冰裂纹的流线几何贴花" in provider.last_complete_json_user_message

    with SessionLocal() as db:
        row = db.execute(select(GeneratedImage).where(GeneratedImage.id == payload["item"]["id"])).scalar_one_or_none()
        assert row is not None
        assert row.metadata_json["kind"] == "pattern_asset"
        assert row.metadata_json["source_result_id"] == "result_pattern_1"
        assert row.metadata_json["preview_mode"] == "meshy"
        assert row.metadata_json["canvas_snapshot_used"] is True
        assert row.metadata_json["pattern_prompt_text"] == "像冰裂纹的流线几何贴花"


def test_generate_texture_pattern_uses_edited_texture_without_user_prompt(monkeypatch) -> None:  # noqa: ANN001
    provider = FakePatternProvider()
    monkeypatch.setattr(ai_api, "get_pattern_image_provider", lambda: provider)
    monkeypatch.setattr(ai_api, "get_pattern_asset_agent", lambda: PatternAssetAgent())

    host = register_and_login("host_pattern_asset_edited")
    token = host["access_token"]
    user_id = host["user"]["id"]
    meeting = create_session(token, "Pattern Asset Edited Session")
    session_id = meeting["id"]

    meshy_base_color = create_png_data_url((215, 193, 140, 255))
    edited_base_color = create_png_data_url((199, 161, 122, 255))
    seed_pattern_texture_workspace(
        session_id=session_id,
        user_id=user_id,
        meshy_base_color=meshy_base_color,
        edited_base_color=edited_base_color,
    )

    generated = client.post(
        "/api/ai/texture-plan/generate-pattern",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "result_id": "result_pattern_1",
            "preview_mode": "edited",
            "workspace_id": "workspace:test",
            "pattern_prompt_text": "",
        },
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["pattern_prompt_text"] is None
    assert provider.last_visual_image_url == edited_base_color
    assert provider.last_generate_payload is not None
    assert provider.last_generate_payload["background"] == "transparent"


def test_host_can_patch_session_settings_and_non_host_cannot() -> None:
    host = register_and_login("host_settings_patch")
    host_token = host["access_token"]
    member = register_and_login("member_settings_patch")
    member_token = member["access_token"]

    meeting = create_session(host_token, "Settings Session")
    session_id = meeting["id"]

    joined = client.post(
        "/api/sessions/join",
        headers=auth_header(member_token),
        json={"invite_code": meeting["invite_code"], "role": "designer"},
    )
    assert joined.status_code == 200

    forbidden = client.patch(
        f"/api/sessions/{session_id}/settings",
        headers=auth_header(member_token),
        json={
            "review_personas": {
                "passenger": {"display_name": "Airport Commuter"},
                "engineering": {"display_name": "Depot Engineer"},
            }
        },
    )
    assert forbidden.status_code == 403

    updated = client.patch(
        f"/api/sessions/{session_id}/settings",
        headers=auth_header(host_token),
        json={
            "review_personas": {
                "passenger": {
                    "display_name": "Airport Commuter",
                    "identity_summary": "A commuter focused on clarity, trust, and quick recognition.",
                    "preference_tags": ["clear", "safe"],
                    "dislike_tags": ["messy"],
                    "focus_points": ["first impression", "clarity"],
                },
                "engineering": {
                    "display_name": "Depot Engineer",
                    "identity_summary": "A depot reviewer focused on maintenance and stable process.",
                    "priority_tags": ["stable process", "easy upkeep"],
                    "risk_focus": ["masking workload", "maintenance cycle"],
                    "focus_points": ["durability", "cost"],
                },
            }
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["session_settings"]["revision"] == 2
    assert payload["session_settings"]["review_personas"]["passenger"]["display_name"] == "Airport Commuter"
    assert payload["session_settings"]["review_personas"]["engineering"]["display_name"] == "Depot Engineer"


def test_stage4_media_delete_permissions_and_cleanup() -> None:
    host = register_and_login("host_stage4_delete")
    host_token = host["access_token"]
    creator = register_and_login("creator_stage4_delete")
    creator_token = creator["access_token"]
    viewer = register_and_login("viewer_stage4_delete")
    viewer_token = viewer["access_token"]

    meeting = create_session(host_token, "Stage4 Delete Session")
    session_id = meeting["id"]

    creator_join = client.post(
        "/api/sessions/join",
        headers=auth_header(creator_token),
        json={"invite_code": meeting["invite_code"], "role": "designer"},
    )
    assert creator_join.status_code == 200
    viewer_join = client.post(
        "/api/sessions/join",
        headers=auth_header(viewer_token),
        json={"invite_code": meeting["invite_code"], "role": "observer"},
    )
    assert viewer_join.status_code == 200

    asset_id, generated_image_id, file_path = seed_stage4_media_asset(
        session_id=session_id,
        user_id=creator["user"]["id"],
    )

    creator_list = client.get(
        "/api/ai/stage4/media",
        headers=auth_header(creator_token),
        params={"session_id": session_id, "result_id": "result_stage4_1"},
    )
    assert creator_list.status_code == 200
    assert creator_list.json()["items"][0]["can_delete"] is True

    viewer_list = client.get(
        "/api/ai/stage4/media",
        headers=auth_header(viewer_token),
        params={"session_id": session_id, "result_id": "result_stage4_1"},
    )
    assert viewer_list.status_code == 200
    assert viewer_list.json()["items"][0]["can_delete"] is False

    host_list = client.get(
        "/api/ai/stage4/media",
        headers=auth_header(host_token),
        params={"session_id": session_id, "result_id": "result_stage4_1"},
    )
    assert host_list.status_code == 200
    assert host_list.json()["items"][0]["can_delete"] is True

    forbidden = client.delete(
        f"/api/ai/stage4/media/{asset_id}",
        headers=auth_header(viewer_token),
        params={"session_id": session_id},
    )
    assert forbidden.status_code == 403

    deleted = client.delete(
        f"/api/ai/stage4/media/{asset_id}",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert deleted.status_code == 204

    with SessionLocal() as db:
        media_row = db.execute(select(GeneratedMediaAsset).where(GeneratedMediaAsset.id == asset_id)).scalar_one_or_none()
        image_row = db.execute(select(GeneratedImage).where(GeneratedImage.id == generated_image_id)).scalar_one_or_none()
        assert media_row is None
        assert image_row is None

    assert not Path(file_path).exists()


def test_existing_review_stays_unchanged_until_refresh_after_settings_change(monkeypatch) -> None:  # noqa: ANN001
    host = register_and_login("host_review_settings")
    host_token = host["access_token"]
    user_id = host["user"]["id"]
    meeting = create_session(host_token, "Review Settings Session")
    session_id = meeting["id"]

    seed_review_texture_workspace(
        session_id=session_id,
        user_id=user_id,
        review_assessment={
            "status": "completed",
            "engineering": {
                "paint_volume_kg": 100.0,
                "color_zone_count": 2,
                "masking_steps": 2,
                "gradient_ratio_percent": 6.0,
                "labor_hours": 120,
                "process_steps": 4,
                "curve_conformance_score": 80,
                "material_cost_yuan": 20000,
                "labor_cost_yuan": 16000,
                "total_cost_yuan": 36000,
                "color_variance_risk": "LOW",
                "weather_durability": "A",
                "maintenance_cycle_years": 6,
            },
            "passenger": {
                "scores": {
                    "first_impression": 8,
                    "safety_trust": 8,
                    "comfort_cleanliness": 7,
                    "perceived_quality": 8,
                    "speed_motion": 8,
                    "emotion_character": 7,
                },
                "overall_score": 7.7,
                "summary": "Passengers would read it as clean and trustworthy.",
                "strengths": ["Clean body lines remain easy to trust.", "The motion read stays stable from afar."],
                "issues": ["The design still feels slightly safe.", "One side area could be more memorable."],
                "suggestions": ["Sharpen one accent line.", "Keep the base calm but clearer in hierarchy."],
            },
            "recommendation": "recommended",
            "source": "llm",
            "model_name": "seed-model",
            "error_message": None,
            "settings_revision_used": 1,
            "persona_labels_used": {
                "passenger": "Ordinary Passenger",
                "engineering": "Coating Process Engineer",
            },
        },
    )

    updated = client.patch(
        f"/api/sessions/{session_id}/settings",
        headers=auth_header(host_token),
        json={
            "review_personas": {
                "passenger": {"display_name": "Airport Commuter"},
                "engineering": {"display_name": "Depot Engineer"},
            }
        },
    )
    assert updated.status_code == 200
    assert updated.json()["session_settings"]["revision"] == 2

    unchanged = client.get(
        "/api/ai/texture-plan/models",
        headers=auth_header(host_token),
        params={"session_id": session_id},
    )
    assert unchanged.status_code == 200
    review_before_refresh = unchanged.json()["models"][0]["review_assessment"]
    assert review_before_refresh["settings_revision_used"] == 1
    assert review_before_refresh["persona_labels_used"]["passenger"] == "Ordinary Passenger"

    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: object())
    monkeypatch.setattr(ai_api, "get_stage3_review_service", lambda: FakeReviewService())

    refreshed = client.post(
        "/api/ai/texture-plan/refresh-review",
        headers=auth_header(host_token),
        json={"session_id": session_id, "result_id": "result_review_1"},
    )
    assert refreshed.status_code == 200
    refreshed_review = refreshed.json()["models"][0]["review_assessment"]
    assert refreshed_review["settings_revision_used"] == 2
    assert refreshed_review["persona_labels_used"] == {
        "passenger": "Airport Commuter",
        "engineering": "Depot Engineer",
    }
