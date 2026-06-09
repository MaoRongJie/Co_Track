from __future__ import annotations

from typing import Any

from app.agents.intent_and_3d_generation_agent import (
    Stage1IntentAndThreeDGenerationAgent,
    ThreeDModelGenerationPlan,
)
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.graph.engine import (
    get_stage1_intent_and_3d_generation_agent,
    get_three_d_model_generation_provider,
    try_get_openai_text_image_provider,
)


def build_fallback_model_generation_plan(
    *,
    product_category: str,
    product_profile: dict[str, Any],
    brief_json: dict[str, Any] | None,
) -> ThreeDModelGenerationPlan:
    _ = product_profile
    theme = "工业外观"
    if isinstance(brief_json, dict):
        raw_theme = brief_json.get("theme")
        if isinstance(raw_theme, str) and raw_theme.strip():
            theme = raw_theme.strip()
        elif isinstance(brief_json.get("why"), dict):
            core_experience = brief_json["why"].get("coreExperienceIntent")
            if isinstance(core_experience, str) and core_experience.strip():
                theme = core_experience.strip()

    prompt = (
        "请为协同涂层设计创建一个近似的工业产品参考模型。"
        f"产品类别：{product_category}。主题：{theme}。"
        "优先保证简单拓扑和 UV 稳定性。"
    )
    negative_prompt = "不要出现文字标识或内部细节，避免细小零件。"

    return ThreeDModelGenerationPlan(
        provider_route="fallback",
        generation_prompt=prompt,
        negative_prompt=negative_prompt,
        generation_intent={},
        metadata={
            "suggested_surface_area_m2": 298.4 if "train" in product_category else 52.6,
            "suggested_paintable_uv_pixels": 4096 * 2048 if "train" in product_category else 2048 * 1024,
            "product_category": product_category,
            "llm_used": False,
        },
    )


def get_stage2_dependencies() -> tuple[
    Stage1IntentAndThreeDGenerationAgent,
    OpenAITextImageProvider | None,
    dict[str, bool],
]:
    text_provider = try_get_openai_text_image_provider()
    stage1_agent = get_stage1_intent_and_3d_generation_agent(text_provider)
    provider_availability = get_three_d_model_generation_provider().provider_availability
    return stage1_agent, text_provider, provider_availability


async def run_stage2_plan_3d_model(
    *,
    stage1_agent: Stage1IntentAndThreeDGenerationAgent,
    product_category: str,
    product_profile: dict[str, Any],
    brief_json: dict[str, Any] | None,
    provider_availability: dict[str, bool],
) -> ThreeDModelGenerationPlan:
    return await stage1_agent.plan_model_generation(
        product_category=product_category,
        product_profile=product_profile,
        brief_json=brief_json,
        provider_availability=provider_availability,
    )
