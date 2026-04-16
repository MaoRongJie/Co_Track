from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from app.agents.providers.provider_protocols import ModelProviderError, TextAndImageProvider

try:
    from langgraph.graph import END, START, StateGraph

    HAS_LANGGRAPH = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    HAS_LANGGRAPH = False

ProviderRoute = Literal["tripo", "meshy", "hyper3d", "fallback"]


class Stage1RuntimeDependencyError(RuntimeError):
    pass


@dataclass(slots=True)
class IntentRecognitionResult:
    brief_json: dict[str, object]
    intent_payload: dict[str, object]
    used_llm: bool


@dataclass(slots=True)
class ThreeDModelGenerationPlan:
    provider_route: ProviderRoute
    generation_prompt: str
    negative_prompt: str
    generation_intent: dict[str, object]
    metadata: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_route": self.provider_route,
            "generation_prompt": self.generation_prompt,
            "negative_prompt": self.negative_prompt,
            "generation_intent": self.generation_intent,
            **self.metadata,
        }


class _BriefState(TypedDict):
    design_goal: str
    product_category: str
    raw_intent: dict[str, object]
    brief_json: dict[str, object]
    used_llm: bool


class _ModelState(TypedDict):
    product_category: str
    product_profile: dict[str, object]
    brief_json: dict[str, object]
    provider_availability: dict[str, bool]
    generation_intent: dict[str, object]
    generation_prompt: str
    negative_prompt: str
    provider_route: ProviderRoute
    metadata: dict[str, object]
    used_llm: bool


def _safe_text(value: object, *, default: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    return default


def _safe_list(value: object, *, max_items: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    picked: list[str] = []
    for item in value:
        text = _safe_text(item)
        if text:
            picked.append(text)
        if len(picked) >= max_items:
            break
    return picked


def _split_goal_chunks(goal: str) -> list[str]:
    chunks = re.split(r"[銆傦紱;,\n]+", goal)
    return [item.strip() for item in chunks if item and item.strip()]


def _heuristic_brief(goal: str, category: str) -> dict[str, object]:
    chunks = _split_goal_chunks(goal)
    lowered = goal.lower()
    color_tokens = []
    for token in ("blue", "white", "silver", "red", "green", "black", "#"):
        if token in lowered:
            color_tokens.append(token)
    main_colors = ["#1E90FF", "#FFFFFF"] if {"blue", "white"} & set(color_tokens) else ["#1E90FF"]

    elements = []
    for token in ("snow", "streamline", "stripe", "tech", "speed", "leaf", "wave"):
        if token in lowered:
            elements.append(token)

    return {
        "theme": chunks[0] if chunks else "Industrial appearance concept",
        "mainColors": main_colors,
        "accentColors": ["#C0C0C0"],
        "styleKeywords": chunks[1:4] if len(chunks) > 1 else [],
        "designElements": elements[:4],
        "constraintsHint": "Keep branding clear and ensure manufacturable coating patterns.",
        "productCategory": category,
    }


def _extract_json_object(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Fallback: extract the first JSON object in mixed text output.
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                fragment = text[start : idx + 1]
                try:
                    parsed = json.loads(fragment)
                except Exception:
                    return None
                if isinstance(parsed, dict):
                    return parsed
                return None
    return None


def _profile_to_text(profile: dict[str, object]) -> str:
    if not profile:
        return "{}"
    compact = {str(key): value for key, value in profile.items()}
    try:
        return json.dumps(compact, ensure_ascii=False)
    except Exception:
        return "{}"


def _default_surface_and_uv(product_category: str) -> tuple[float, int]:
    train_categories = {"high_speed_train", "intercity_train", "metro_vehicle"}
    if product_category in train_categories:
        return 298.4, 4096 * 2048
    return 52.6, 2048 * 1024


class Stage1IntentAndThreeDGenerationAgent:
    def __init__(self, *, text_provider: TextAndImageProvider | None) -> None:
        if not HAS_LANGGRAPH or StateGraph is None:
            raise Stage1RuntimeDependencyError(
                "LangGraph is required but not installed. Install `langgraph` to enable Stage-1 runtime."
            )

        self._text_provider = text_provider
        self._brief_graph = self._build_brief_graph()
        self._model_graph = self._build_model_graph()

    def _build_brief_graph(self):
        builder = StateGraph(_BriefState)
        builder.add_node("intent_recognizer", self._intent_recognizer_node)
        builder.add_node("brief_normalizer", self._brief_normalizer_node)
        builder.add_edge(START, "intent_recognizer")
        builder.add_edge("intent_recognizer", "brief_normalizer")
        builder.add_edge("brief_normalizer", END)
        return builder.compile()

    def _build_model_graph(self):
        builder = StateGraph(_ModelState)
        builder.add_node("generation_intent_extractor", self._generation_intent_node)
        builder.add_node("generation_prompt_builder", self._generation_prompt_node)
        builder.add_node("provider_router", self._provider_router_node)
        builder.add_node("plan_finalizer", self._plan_finalizer_node)
        builder.add_edge(START, "generation_intent_extractor")
        builder.add_edge("generation_intent_extractor", "generation_prompt_builder")
        builder.add_edge("generation_prompt_builder", "provider_router")
        builder.add_edge("provider_router", "plan_finalizer")
        builder.add_edge("plan_finalizer", END)
        return builder.compile()

    async def _complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object] | None:
        if self._text_provider is None:
            return None

        chunks: list[str] = []
        async for chunk in self._text_provider.stream_text(
            system_prompt=system_prompt,
            user_message=user_prompt,
            history=[],
            temperature=0.2,
        ):
            chunks.append(chunk)
        raw = "".join(chunks).strip()
        return _extract_json_object(raw)

    async def _intent_recognizer_node(self, state: _BriefState) -> _BriefState:
        design_goal = state["design_goal"]
        product_category = state["product_category"]
        heuristic = _heuristic_brief(design_goal, product_category)

        system_prompt = (
            "You are Co-Track Stage-1 Intent Recognizer. "
            "Extract an industrial appearance brief from user goal. "
            "Return strict JSON only."
        )
        user_prompt = json.dumps(
            {
                "task": "parse_brief",
                "design_goal": design_goal,
                "product_category": product_category,
                "output_schema": {
                    "theme": "string",
                    "mainColors": ["string"],
                    "accentColors": ["string"],
                    "styleKeywords": ["string"],
                    "designElements": ["string"],
                    "constraintsHint": "string",
                    "productCategory": "string",
                },
                "rules": [
                    "keep arrays concise",
                    "prefer practical, manufacturable wording",
                    "do not add markdown",
                ],
            },
            ensure_ascii=False,
        )

        raw_intent: dict[str, object] = {}
        used_llm = False
        try:
            parsed = await self._complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
            if isinstance(parsed, dict) and parsed:
                raw_intent = parsed
                used_llm = True
        except ModelProviderError:
            raw_intent = {}
        except Exception:
            raw_intent = {}

        if not raw_intent:
            raw_intent = heuristic
        return {**state, "raw_intent": raw_intent, "used_llm": used_llm}

    def _brief_normalizer_node(self, state: _BriefState) -> _BriefState:
        design_goal = state["design_goal"]
        category = state["product_category"]
        raw = state.get("raw_intent") or {}

        default_payload = _heuristic_brief(design_goal, category)
        theme = _safe_text(raw.get("theme"), default=_safe_text(default_payload.get("theme"), default="Design concept"))
        brief_json: dict[str, object] = {
            "theme": theme,
            "mainColors": _safe_list(raw.get("mainColors")) or _safe_list(default_payload.get("mainColors")) or ["#1E90FF"],
            "accentColors": _safe_list(raw.get("accentColors")) or _safe_list(default_payload.get("accentColors")) or ["#C0C0C0"],
            "styleKeywords": _safe_list(raw.get("styleKeywords"), max_items=8)
            or _safe_list(default_payload.get("styleKeywords"), max_items=8),
            "designElements": _safe_list(raw.get("designElements"), max_items=8)
            or _safe_list(default_payload.get("designElements"), max_items=8),
            "constraintsHint": _safe_text(
                raw.get("constraintsHint"),
                default=_safe_text(default_payload.get("constraintsHint"), default=""),
            ),
            "productCategory": _safe_text(raw.get("productCategory"), default=category) or category,
        }
        if brief_json["productCategory"] != category:
            brief_json["productCategory"] = category
        return {**state, "brief_json": brief_json}

    async def _generation_intent_node(self, state: _ModelState) -> _ModelState:
        product_category = state["product_category"]
        product_profile = state["product_profile"]
        brief_json = state["brief_json"]

        heuristic_intent: dict[str, object] = {
            "shapeKeywords": _safe_list(brief_json.get("designElements"), max_items=6),
            "styleKeywords": _safe_list(brief_json.get("styleKeywords"), max_items=8),
            "surfaceFinish": "paint-friendly smooth shell",
            "keepSymmetry": bool(product_profile.get("isSymmetric", True)),
            "targetUvSpec": "4096x2048" if product_category in {"high_speed_train", "intercity_train", "metro_vehicle"} else "2048x1024",
        }

        system_prompt = (
            "You are Co-Track Stage-1 3D Similarity Planner. "
            "Convert product profile and brief to generation intent JSON only."
        )
        user_prompt = json.dumps(
            {
                "task": "build_3d_generation_intent",
                "product_category": product_category,
                "product_profile": product_profile,
                "brief_json": brief_json,
                "output_schema": {
                    "shapeKeywords": ["string"],
                    "styleKeywords": ["string"],
                    "surfaceFinish": "string",
                    "keepSymmetry": "boolean",
                    "targetUvSpec": "string",
                },
            },
            ensure_ascii=False,
        )

        generation_intent: dict[str, object] = heuristic_intent
        used_llm = state.get("used_llm", False)
        try:
            parsed = await self._complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
            if isinstance(parsed, dict) and parsed:
                generation_intent = {
                    "shapeKeywords": _safe_list(parsed.get("shapeKeywords"), max_items=8)
                    or heuristic_intent["shapeKeywords"],
                    "styleKeywords": _safe_list(parsed.get("styleKeywords"), max_items=8)
                    or heuristic_intent["styleKeywords"],
                    "surfaceFinish": _safe_text(parsed.get("surfaceFinish"), default="paint-friendly smooth shell"),
                    "keepSymmetry": bool(parsed.get("keepSymmetry", True)),
                    "targetUvSpec": _safe_text(parsed.get("targetUvSpec"), default=str(heuristic_intent["targetUvSpec"])),
                }
                used_llm = True
        except ModelProviderError:
            pass
        except Exception:
            pass

        return {**state, "generation_intent": generation_intent, "used_llm": used_llm}

    def _generation_prompt_node(self, state: _ModelState) -> _ModelState:
        product_category = state["product_category"]
        product_profile = state["product_profile"]
        brief_json = state["brief_json"]
        generation_intent = state["generation_intent"]

        theme = _safe_text(brief_json.get("theme"), default="industrial appearance")
        color_hints = ", ".join(_safe_list(brief_json.get("mainColors"), max_items=4))
        shape_keywords = ", ".join(_safe_list(generation_intent.get("shapeKeywords"), max_items=6))
        style_keywords = ", ".join(_safe_list(generation_intent.get("styleKeywords"), max_items=6))
        surface_finish = _safe_text(generation_intent.get("surfaceFinish"), default="paint-friendly smooth shell")
        uv_spec = _safe_text(generation_intent.get("targetUvSpec"), default="2048x1024")
        profile_text = _profile_to_text(product_profile)

        prompt = (
            "Create an approximate industrial product reference model for collaborative coating design. "
            f"Product category: {product_category}. "
            f"Theme: {theme}. "
            f"Shape keywords: {shape_keywords or 'clean streamlined silhouette'}. "
            f"Style keywords: {style_keywords or 'industrial modern'}. "
            f"Color hints: {color_hints or '#1E90FF,#FFFFFF'}. "
            f"Surface finish: {surface_finish}. "
            f"Product profile: {profile_text}. "
            "Output must favor simple topology and stable UV seams for painting workflow. "
            f"Target UV recommendation: {uv_spec}."
        )
        negative_prompt = (
            "No human, no background scene, no text logo, no transparent shell, "
            "no interior details, avoid excessive tiny parts."
        )

        return {**state, "generation_prompt": prompt, "negative_prompt": negative_prompt}

    def _provider_router_node(self, state: _ModelState) -> _ModelState:
        availability = state["provider_availability"]
        provider: ProviderRoute = "fallback"
        for candidate in ("tripo", "meshy", "hyper3d"):
            if availability.get(candidate):
                provider = candidate  # type: ignore[assignment]
                break
        return {**state, "provider_route": provider}

    def _plan_finalizer_node(self, state: _ModelState) -> _ModelState:
        product_category = state["product_category"]
        surface_area_m2, paintable_uv_pixels = _default_surface_and_uv(product_category)
        metadata = {
            "suggested_surface_area_m2": surface_area_m2,
            "suggested_paintable_uv_pixels": paintable_uv_pixels,
            "product_category": product_category,
            "llm_used": state.get("used_llm", False),
        }
        return {**state, "metadata": metadata}

    async def parse_brief_intent(self, *, design_goal: str, product_category: str) -> IntentRecognitionResult:
        initial: _BriefState = {
            "design_goal": design_goal,
            "product_category": product_category,
            "raw_intent": {},
            "brief_json": {},
            "used_llm": False,
        }
        try:
            result = await self._brief_graph.ainvoke(initial)
        except Exception:
            fallback = _heuristic_brief(design_goal, product_category)
            return IntentRecognitionResult(brief_json=fallback, intent_payload=fallback, used_llm=False)
        brief = result.get("brief_json") if isinstance(result, dict) else None
        raw_intent = result.get("raw_intent") if isinstance(result, dict) else None
        return IntentRecognitionResult(
            brief_json=brief if isinstance(brief, dict) and brief else _heuristic_brief(design_goal, product_category),
            intent_payload=raw_intent if isinstance(raw_intent, dict) else {},
            used_llm=bool(result.get("used_llm")) if isinstance(result, dict) else False,
        )

    async def plan_model_generation(
        self,
        *,
        product_category: str,
        product_profile: dict[str, object],
        brief_json: dict[str, object] | None,
        provider_availability: dict[str, bool],
    ) -> ThreeDModelGenerationPlan:
        initial: _ModelState = {
            "product_category": product_category,
            "product_profile": product_profile,
            "brief_json": brief_json if isinstance(brief_json, dict) else {},
            "provider_availability": provider_availability,
            "generation_intent": {},
            "generation_prompt": "",
            "negative_prompt": "",
            "provider_route": "fallback",
            "metadata": {},
            "used_llm": False,
        }
        result = await self._model_graph.ainvoke(initial)

        provider_route_raw = result.get("provider_route")
        if provider_route_raw in {"tripo", "meshy", "hyper3d"}:
            provider_route: ProviderRoute = provider_route_raw
        else:
            provider_route = "fallback"

        generation_intent = result.get("generation_intent")
        metadata = result.get("metadata")

        return ThreeDModelGenerationPlan(
            provider_route=provider_route,
            generation_prompt=_safe_text(result.get("generation_prompt")),
            negative_prompt=_safe_text(result.get("negative_prompt")),
            generation_intent=generation_intent if isinstance(generation_intent, dict) else {},
            metadata=metadata if isinstance(metadata, dict) else {},
        )


# Backward-compatible aliases for existing imports.
BriefIntentResult = IntentRecognitionResult
ModelGenerationPlan = ThreeDModelGenerationPlan
Stage1AgentRuntime = Stage1IntentAndThreeDGenerationAgent

