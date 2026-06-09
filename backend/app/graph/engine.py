from __future__ import annotations

from app.agents.creative_dialogue_and_image_agent import CreativeDialogueAndImageAgent
from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent
from app.agents.pattern_asset_agent import PatternAssetAgent
from app.agents.stage4_media_agent import Stage4MediaAgent
from app.agents.providers.aihubmix_media_provider import AiHubMixMediaProvider
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.agents.providers.three_d_generation_provider import ThreeDModelGenerationProvider
from app.graph.session_store import get_workflow_session_store


def get_creative_dialogue_and_image_agent() -> CreativeDialogueAndImageAgent:
    return get_workflow_session_store().get_creative_agent()


def get_pattern_asset_agent() -> PatternAssetAgent:
    return get_workflow_session_store().get_pattern_agent()


def get_stage4_media_agent() -> Stage4MediaAgent:
    return get_workflow_session_store().get_stage4_media_agent()


def get_openai_text_image_provider() -> OpenAITextImageProvider:
    return get_workflow_session_store().get_openai_provider()


def get_pattern_image_provider() -> OpenAITextImageProvider:
    return get_workflow_session_store().get_pattern_provider()


def try_get_openai_text_image_provider() -> OpenAITextImageProvider | None:
    return get_workflow_session_store().try_get_openai_provider()


def try_get_pattern_image_provider() -> OpenAITextImageProvider | None:
    return get_workflow_session_store().try_get_pattern_provider()


def get_stage1_intent_and_3d_generation_agent(
    text_provider: OpenAITextImageProvider | None,
) -> Stage1IntentAndThreeDGenerationAgent:
    return get_workflow_session_store().get_stage1_agent(text_provider)


def get_three_d_model_generation_provider() -> ThreeDModelGenerationProvider:
    return get_workflow_session_store().get_three_d_provider()


def get_meshy_texture_provider():
    from app.agents.providers.meshy_texture_provider import MeshyTextureProvider  # noqa: F811
    return get_workflow_session_store().get_meshy_texture_provider()


def get_aihubmix_media_provider() -> AiHubMixMediaProvider:
    return get_workflow_session_store().get_aihubmix_media_provider()
