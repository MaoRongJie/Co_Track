from __future__ import annotations

from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent, _heuristic_brief
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.graph.engine import (
    get_stage1_intent_and_3d_generation_agent,
    try_get_openai_text_image_provider,
)


def build_fallback_brief(goal: str, category: str) -> dict[str, object]:
    return _heuristic_brief(goal, category)


def get_stage1_agent_with_optional_llm() -> tuple[Stage1IntentAndThreeDGenerationAgent, OpenAITextImageProvider | None]:
    text_provider = try_get_openai_text_image_provider()
    stage1_agent = get_stage1_intent_and_3d_generation_agent(text_provider)
    return stage1_agent, text_provider


async def run_stage1_extract_concept(
    *,
    design_goal: str,
    product_category: str,
    stage1_agent: Stage1IntentAndThreeDGenerationAgent,
) -> dict[str, object]:
    result = await stage1_agent.parse_brief_intent(
        design_goal=design_goal,
        product_category=product_category,
    )
    return result.brief_json
