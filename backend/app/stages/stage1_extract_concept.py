from __future__ import annotations

from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.graph.engine import (
    get_stage1_intent_and_3d_generation_agent,
    try_get_openai_text_image_provider,
)


def build_fallback_brief(goal: str, category: str) -> dict[str, object]:
    pieces = [item.strip() for item in goal.replace("\n", ",").split(",") if item.strip()]
    theme = pieces[0] if pieces else "Industrial appearance concept"

    lowered_goal = goal.lower()
    main_colors = ["#1E90FF"]
    if "blue" in lowered_goal and "white" in lowered_goal:
        main_colors = ["#1E90FF", "#FFFFFF"]

    style_keywords = pieces[1:4] if len(pieces) > 1 else []
    design_elements: list[str] = []
    for token in ("snow", "streamline", "stripe", "tech", "speed", "wave"):
        if token in lowered_goal:
            design_elements.append(token)

    return {
        "theme": theme,
        "mainColors": main_colors,
        "accentColors": ["#C0C0C0"],
        "styleKeywords": style_keywords,
        "designElements": design_elements[:4],
        "constraintsHint": "Keep branding clear and ensure manufacturable coating patterns.",
        "productCategory": category,
    }


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

