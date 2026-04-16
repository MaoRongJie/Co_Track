from __future__ import annotations

from app.db.models import AiMessage
from app.schemas.ai import AiMessageOut


def safe_chat_role(raw: str) -> str:
    return raw if raw in {"user", "assistant", "system"} else "assistant"


def safe_chat_mode(raw: str | None) -> str | None:
    if raw in {"creative", "image"}:
        return raw
    return None


def to_ai_message_out(item: AiMessage) -> AiMessageOut:
    return AiMessageOut(
        id=item.id,
        session_id=item.session_id,
        user_id=item.user_id,
        role=safe_chat_role(item.role),  # type: ignore[arg-type]
        mode=safe_chat_mode(item.mode),  # type: ignore[arg-type]
        content=item.content,
        created_at=item.created_at,
    )

