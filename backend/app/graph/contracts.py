from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.creative_dialogue_and_image_agent import CreativeRoutePlan, SessionAiContext
from app.agents.intent_and_3d_generation_agent import (
    IntentRecognitionResult,
    ThreeDModelGenerationPlan,
)


@dataclass(slots=True)
class Stage1ExtractConceptInput:
    design_goal: str
    product_category: str


@dataclass(slots=True)
class Stage1ExtractConceptOutput:
    result: IntentRecognitionResult


@dataclass(slots=True)
class Stage2PlanThreeDInput:
    product_category: str
    product_profile: dict[str, Any]
    brief_json: dict[str, Any] | None
    provider_availability: dict[str, bool]


@dataclass(slots=True)
class Stage2PlanThreeDOutput:
    plan: ThreeDModelGenerationPlan


@dataclass(slots=True)
class Stage3CreativeChatInput:
    mode: str
    message: str
    context: SessionAiContext


@dataclass(slots=True)
class Stage3CreativeChatOutput:
    plan: CreativeRoutePlan

