from __future__ import annotations

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.graph.engine import get_openai_text_image_provider


def get_stage4_provider() -> OpenAITextImageProvider:
    return get_openai_text_image_provider()


async def run_stage4_generate_image_assets(
    *,
    provider: OpenAITextImageProvider,
    prompt: str,
    style_hint: str | None,
    reference_images: list[str] | None,
):
    return await provider.generate_image(
        prompt=prompt,
        style_hint=style_hint,
        reference_images=reference_images,
    )

