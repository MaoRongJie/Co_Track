from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.api.ai as ai_api
from app.agents.providers.provider_protocols import ImageGenerationResult
from app.agents.creative_dialogue_and_image_agent import CreativeRoutePlan
from app.db.models import AiMessage, GeneratedImage, MeetingSession
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


def join_session(token: str, invite_code: str) -> dict[str, object]:
    response = client.post(
        "/api/sessions/join",
        json={"invite_code": invite_code},
        headers=auth_header(token),
    )
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


class FakeRuntime:
    async def plan_chat(self, *, mode: str, message: str, context):  # noqa: ANN001
        route = "image" if mode == "image" else "creative"
        return CreativeRoutePlan(route=route, system_prompt="You are fake assistant.")


class FakeProvider:
    model_name = "fake-text-model"
    image_model = "fake-image-model"

    async def stream_text(self, *, system_prompt: str, user_message: str, history, temperature: float = 0.7):  # noqa: ANN001
        _ = (system_prompt, history, temperature)
        yield "你好，"
        yield f"已收到：{user_message}"

    async def generate_image(self, *, prompt: str, style_hint: str | None = None, reference_images=None):  # noqa: ANN001
        _ = (style_hint, reference_images)
        return [
            ImageGenerationResult(
                image_url="data:image/png;base64,ZmFrZQ==",
                revised_prompt=f"refined::{prompt}",
                provider_payload={"source": "fake"},
            )
        ]


def test_chat_stream_and_history_persist(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_ai_chat")
    token = host["access_token"]
    meeting = create_session(token, "AI Chat Session")
    session_id = meeting["id"]

    response = client.post(
        "/api/ai/chat",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "message": "给我一个蓝白涂装建议",
            "mode": "creative",
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert "event: chunk" in response.text
    assert "event: done" in response.text
    assert "event: chunk\ndata:" in response.text
    assert "\n\nevent: done\ndata:" in response.text

    history = client.get(
        "/api/ai/chat/history",
        headers=auth_header(token),
        params={"session_id": session_id, "limit": 10},
    )
    assert history.status_code == 200
    items = history.json()["items"]
    assert len(items) >= 2
    assert items[0]["role"] == "assistant"
    assert items[1]["role"] == "user"


def test_chat_forbidden_for_non_member(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_ai_forbidden")
    host_token = host["access_token"]
    outsider = register_and_login("outsider_ai_forbidden")
    outsider_token = outsider["access_token"]

    meeting = create_session(host_token, "Forbidden AI Session")
    session_id = meeting["id"]

    forbidden = client.post(
        "/api/ai/chat",
        headers=auth_header(outsider_token),
        json={"session_id": session_id, "message": "hi", "mode": "creative", "stream": True},
    )
    assert forbidden.status_code == 403


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
            "prompt": "鍐伴洩娴佺嚎杞﹁韩鍥炬",
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
        assert row.prompt == "鍐伴洩娴佺嚎杞﹁韩鍥炬"


def test_chat_persist_for_555555(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    user = register_and_login("member_ai_555555")
    token = user["access_token"]
    meeting = create_session(token, "AI Persist Session")
    session_id = meeting["id"]

    with SessionLocal() as db:
        db.execute(delete(AiMessage).where(AiMessage.session_id == session_id))
        db.commit()

    response = client.post(
        "/api/ai/chat",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "message": "请给一个材质方案",
            "mode": "creative",
            "stream": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_message"]["id"] > 0
    assert payload["assistant_message"]["id"] > 0

    history = client.get(
        "/api/ai/chat/history",
        headers=auth_header(token),
        params={"session_id": session_id, "limit": 10},
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) >= 2

    with SessionLocal() as db:
        rows = db.execute(select(AiMessage).where(AiMessage.session_id == session_id)).scalars().all()
        assert len(rows) >= 2


def test_chat_persist_for_666666(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_api, "get_creative_dialogue_and_image_agent", lambda: FakeRuntime())
    monkeypatch.setattr(ai_api, "get_openai_text_image_provider", lambda: FakeProvider())

    host = register_and_login("host_ai_666666")
    token = host["access_token"]
    meeting = create_session(token, "AI Chat Session 666666")
    session_id = meeting["id"]

    set_invite_code(session_id, "666666")
    with SessionLocal() as db:
        db.execute(delete(AiMessage).where(AiMessage.session_id == session_id))
        db.commit()

    response = client.post(
        "/api/ai/chat",
        headers=auth_header(token),
        json={
            "session_id": session_id,
            "message": "给我一个蓝白涂装建议",
            "mode": "creative",
            "stream": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_message"]["id"] > 0
    assert payload["assistant_message"]["id"] > 0

    history = client.get(
        "/api/ai/chat/history",
        headers=auth_header(token),
        params={"session_id": session_id, "limit": 10},
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) >= 2

    with SessionLocal() as db:
        rows = db.execute(select(AiMessage).where(AiMessage.session_id == session_id)).scalars().all()
        assert len(rows) >= 2


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
            "prompt": "冰雪流线车身图案",
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

