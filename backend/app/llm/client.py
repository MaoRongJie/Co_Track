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


def build_pattern_text_image_provider(settings: Settings) -> OpenAITextImageProvider:
    api_key = settings.pattern_api_key.strip() or settings.openai_api_key
    base_url = settings.pattern_base_url.strip() or settings.openai_base_url
    text_model = settings.pattern_text_model.strip() or settings.openai_text_model
    vision_model = settings.pattern_vision_model.strip() or settings.openai_vision_model
    image_model = settings.pattern_image_model.strip() or settings.openai_image_model
    timeout_ms = settings.pattern_timeout_ms or settings.openai_timeout_ms
    return OpenAITextImageProvider(
        api_key=api_key,
        base_url=base_url,
        text_model=text_model,
        vision_model=vision_model,
        image_model=image_model,
        timeout_ms=timeout_ms,
    )
