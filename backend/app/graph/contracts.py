from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
