from __future__ import annotations

from dataclasses import dataclass

from app.agents.creative_dialogue_and_image_agent import CreativeDialogueAndImageAgent
from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent
from app.agents.providers.meshy_texture_provider import MeshyTextureProvider
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.agents.providers.provider_protocols import ModelProviderNotConfiguredError
from app.agents.providers.three_d_generation_provider import ThreeDModelGenerationProvider
from app.core.config import get_settings
from app.llm.client import build_openai_text_image_provider


@dataclass(slots=True)
class WorkflowSessionStore:
    creative_agent: CreativeDialogueAndImageAgent | None = None
    stage1_agent: Stage1IntentAndThreeDGenerationAgent | None = None
    openai_provider: OpenAITextImageProvider | None = None
    three_d_provider: ThreeDModelGenerationProvider | None = None
    meshy_provider: MeshyTextureProvider | None = None
    openai_fingerprint: tuple[str, str, str, str, str, int] | None = None
    stage1_fingerprint: tuple[str, str, int] | None = None
    three_d_fingerprint: tuple[str, str, str, bool] | None = None
    meshy_fingerprint: tuple[str, str] | None = None

    def get_creative_agent(self) -> CreativeDialogueAndImageAgent:
        if self.creative_agent is None:
            self.creative_agent = CreativeDialogueAndImageAgent()
        return self.creative_agent

    def get_openai_provider(self) -> OpenAITextImageProvider:
        settings = get_settings()
        if not settings.openai_api_key.strip():
            raise ModelProviderNotConfiguredError("OPENAI_API_KEY is not configured")

        current = (
            settings.openai_api_key.strip(),
            settings.openai_base_url.strip(),
            settings.openai_text_model,
            settings.openai_vision_model,
            settings.openai_image_model,
            settings.openai_timeout_ms,
        )
        if self.openai_provider is None or self.openai_fingerprint != current:
            self.openai_provider = build_openai_text_image_provider(settings)
            self.openai_fingerprint = current
        return self.openai_provider

    def try_get_openai_provider(self) -> OpenAITextImageProvider | None:
        try:
            return self.get_openai_provider()
        except ModelProviderNotConfiguredError:
            return None

    def get_stage1_agent(
        self,
        text_provider: OpenAITextImageProvider | None,
    ) -> Stage1IntentAndThreeDGenerationAgent:
        if text_provider is None:
            current_fingerprint: tuple[str, str, int] | None = None
        else:
            settings = get_settings()
            current_fingerprint = (
                settings.openai_base_url.strip(),
                settings.openai_text_model.strip(),
                settings.openai_timeout_ms,
            )

        if self.stage1_agent is None or self.stage1_fingerprint != current_fingerprint:
            self.stage1_agent = Stage1IntentAndThreeDGenerationAgent(text_provider=text_provider)
            self.stage1_fingerprint = current_fingerprint
        return self.stage1_agent

    def get_three_d_provider(self) -> ThreeDModelGenerationProvider:
        settings = get_settings()
        current = (
            settings.tripo_api_key.strip(),
            settings.meshy_api_key.strip(),
            settings.hyper3d_api_key.strip(),
            settings.model_generation_enable_remote,
        )
        if self.three_d_provider is None or self.three_d_fingerprint != current:
            self.three_d_provider = ThreeDModelGenerationProvider(settings)
            self.three_d_fingerprint = current
        return self.three_d_provider

    def get_meshy_texture_provider(self) -> MeshyTextureProvider:
        settings = get_settings()
        current = (
            settings.meshy_api_key.strip(),
            settings.meshy_base_url.strip(),
        )
        if self.meshy_provider is None or self.meshy_fingerprint != current:
            self.meshy_provider = MeshyTextureProvider(settings)
            self.meshy_fingerprint = current
        return self.meshy_provider


_SESSION_STORE = WorkflowSessionStore()


def get_workflow_session_store() -> WorkflowSessionStore:
    return _SESSION_STORE
