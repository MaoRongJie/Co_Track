"""Model provider implementations."""

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.agents.providers.three_d_generation_provider import (
    ThreeDModelGenerationArtifact,
    ThreeDModelGenerationProvider,
)

# Backward-compatible aliases.
OpenAIProvider = OpenAITextImageProvider
ThreeDGenerationArtifact = ThreeDModelGenerationArtifact
ThreeDGenerationProvider = ThreeDModelGenerationProvider

__all__ = [
    "OpenAITextImageProvider",
    "OpenAIProvider",
    "ThreeDModelGenerationArtifact",
    "ThreeDGenerationArtifact",
    "ThreeDModelGenerationProvider",
    "ThreeDGenerationProvider",
]

