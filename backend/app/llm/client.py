from __future__ import annotations

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.core.config import Settings


def build_openai_text_image_provider(settings: Settings) -> OpenAITextImageProvider:
    return OpenAITextImageProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        text_model=settings.openai_text_model,
        vision_model=settings.openai_vision_model,
        image_model=settings.openai_image_model,
        timeout_ms=settings.openai_timeout_ms,
    )
