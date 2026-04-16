from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol


@dataclass(slots=True)
class ImageGenerationResult:
    image_url: str
    revised_prompt: str | None = None
    provider_payload: dict[str, Any] | None = None


class ModelProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, provider_code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code


class ModelProviderNotConfiguredError(ModelProviderError):
    def __init__(self, message: str = "AI provider is not configured") -> None:
        super().__init__(message, status_code=503, provider_code="PROVIDER_NOT_CONFIGURED")


class TextAndImageProvider(Protocol):
    model_name: str

    async def stream_text(
        self,
        *,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        ...

    async def generate_image(
        self,
        *,
        prompt: str,
        style_hint: str | None = None,
        reference_images: list[str] | None = None,
    ) -> list[ImageGenerationResult]:
        ...


