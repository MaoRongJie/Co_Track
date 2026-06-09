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
        background: str | None = None,
        output_format: str | None = None,
    ) -> list[ImageGenerationResult]:
        ...


class PatternImageProvider(Protocol):
    model_name: str
    vision_model: str
    image_model: str

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any] | None:
        ...

    async def complete_json_with_messages(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        model: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    async def generate_image(
        self,
        *,
        prompt: str,
        style_hint: str | None = None,
        reference_images: list[str] | None = None,
        background: str | None = None,
        output_format: str | None = None,
    ) -> list[ImageGenerationResult]:
        ...


