from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, TypedDict

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.texture_planning import TEXTURE_SCHEME_IDS, extract_brief_keywords

try:
    from langgraph.graph import END, START, StateGraph

    HAS_LANGGRAPH = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    HAS_LANGGRAPH = False

RouteMode = Literal["creative", "image"]


class AgentRuntimeDependencyError(RuntimeError):
    pass


@dataclass(slots=True)
class SessionAiContext:
    session_id: int
    product_category: str | None
    brief_json: dict[str, Any] | None
    base_model_summary: str
    recent_messages: list[dict[str, str]]


@dataclass(slots=True)
class CreativeRoutePlan:
    route: RouteMode
    system_prompt: str


@dataclass(slots=True)
class TexturePlanningContext:
    session_id: int
    product_category: str | None
    brief_json: dict[str, Any] | None
    base_model_summary: str
    source_text: str
    document_text: str
    document_name: str | None
    selected_image_keywords: list[str]


@dataclass(slots=True)
class TextureSchemePlan:
    id: str
    title: str
    strategy: str
    prompt_text: str
    key_points: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TexturePlanResult:
    schemes: list[TextureSchemePlan]
    brief_keywords: dict[str, Any]
    selected_image_keywords: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemes": [asdict(item) for item in self.schemes],
            "brief_keywords": self.brief_keywords,
            "selected_image_keywords": self.selected_image_keywords,
        }


class _GraphState(TypedDict):
    mode: str
    message: str
    context_summary: str
    route: RouteMode
    system_prompt: str


def _safe_text(value: Any, *, default: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    return default


def _safe_list(value: Any, *, max_items: int = 8) -> list[str]:
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


def _build_context_summary(context: SessionAiContext) -> str:
    brief = context.brief_json or {}
    theme = str(brief.get("theme", "")).strip() if isinstance(brief, dict) else ""
    main_colors = brief.get("mainColors") if isinstance(brief, dict) else None
    style_keywords = brief.get("styleKeywords") if isinstance(brief, dict) else None

    color_text = ""
    if isinstance(main_colors, list):
        picked = [str(item).strip() for item in main_colors if str(item).strip()]
        if picked:
            color_text = ", ".join(picked[:4])

    style_text = ""
    if isinstance(style_keywords, list):
        picked = [str(item).strip() for item in style_keywords if str(item).strip()]
        if picked:
            style_text = ", ".join(picked[:5])

    parts: list[str] = []
    if context.product_category:
        parts.append(f"Product category: {context.product_category}")
    if theme:
        parts.append(f"Theme: {theme}")
    if color_text:
        parts.append(f"Main colors: {color_text}")
    if style_text:
        parts.append(f"Style keywords: {style_text}")
    if context.base_model_summary:
        parts.append(f"Base model: {context.base_model_summary}")
    return "\n".join(parts)


def _build_texture_context_summary(context: TexturePlanningContext) -> dict[str, Any]:
    return {
        "session_id": context.session_id,
        "product_category": context.product_category or "",
        "base_model_summary": context.base_model_summary,
        "brief_keywords": extract_brief_keywords(context.brief_json),
        "source_text": context.source_text,
        "document_name": context.document_name,
        "document_text": context.document_text[:4000],
        "selected_image_keywords": context.selected_image_keywords[:12],
    }


def _normalize_texture_schemes(raw: Any) -> list[TextureSchemePlan]:
    raw_items = raw if isinstance(raw, list) else []
    schemes: list[TextureSchemePlan] = []
    for index, scheme_id in enumerate(TEXTURE_SCHEME_IDS):
        source = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        title = _safe_text(source.get("title"), default=f"Scheme {index + 1}")
        strategy = _safe_text(source.get("strategy"))
        prompt_text = _safe_text(source.get("prompt_text"))
        key_points = _safe_list(source.get("key_points"), max_items=6)
        if not prompt_text:
            prompt_text = f"{title}. Build a manufacturable model texture direction with clear theme, color rhythm, and graphic logic."
        schemes.append(
            TextureSchemePlan(
                id=scheme_id,
                title=title,
                strategy=strategy,
                prompt_text=prompt_text,
                key_points=key_points,
            )
        )
    return schemes


def _tokenize_similarity_text(value: str) -> set[str]:
    normalized = value.lower()
    tokens = re.findall(r"[a-z0-9_#-]+|[\u4e00-\u9fff]", normalized)
    return {token for token in tokens if token.strip()}


def _schemes_are_sufficiently_distinct(schemes: list[TextureSchemePlan]) -> bool:
    if len(schemes) < 3:
        return False

    for left_index in range(len(schemes)):
        for right_index in range(left_index + 1, len(schemes)):
            left = schemes[left_index]
            right = schemes[right_index]
            left_text = " ".join([left.title, left.strategy, left.prompt_text, " ".join(left.key_points)])
            right_text = " ".join([right.title, right.strategy, right.prompt_text, " ".join(right.key_points)])
            left_tokens = _tokenize_similarity_text(left_text)
            right_tokens = _tokenize_similarity_text(right_text)
            if not left_tokens or not right_tokens:
                return False
            overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
            prompt_ratio = SequenceMatcher(a=left.prompt_text, b=right.prompt_text).ratio()
            if overlap >= 0.72 or prompt_ratio >= 0.88:
                return False
    return True


def _fallback_texture_schemes(context: TexturePlanningContext) -> list[TextureSchemePlan]:
    brief_keywords = extract_brief_keywords(context.brief_json)
    theme = _safe_text(brief_keywords.get("theme"), default="industrial appearance")
    colors = ", ".join(_safe_list(brief_keywords.get("main_colors"), max_items=4))
    styles = ", ".join(_safe_list(brief_keywords.get("style_keywords"), max_items=4))
    elements = ", ".join(_safe_list(brief_keywords.get("design_elements"), max_items=4))
    image_keywords = ", ".join(context.selected_image_keywords[:6])

    prompt_bases = [
        f"Build a clean primary direction around {theme}, emphasizing large-scale recognition and manufacturability.",
        f"Build a more dynamic direction around {theme}, emphasizing rhythm changes, movement, and layered transitions.",
        f"Build a more stylized direction around {theme}, emphasizing material mood, texture detail, and memorability.",
    ]

    schemes: list[TextureSchemePlan] = []
    for index, prompt_base in enumerate(prompt_bases, start=1):
        prompt_text = (
            f"{prompt_base} Main color reference: {colors or 'derive from the brief'}. "
            f"Style keywords: {styles or 'modern industrial'}. "
            f"Design elements: {elements or 'keep the composition restrained'}. "
            f"Image style reinforcement: {image_keywords or 'none'}. "
            "Ensure the texture direction remains readable on a large 3D model surface and feasible to manufacture."
        )
        schemes.append(
            TextureSchemePlan(
                id=f"scheme_{index}",
                title=f"Scheme {index}",
                strategy=f"Differentiated direction {index}",
                prompt_text=prompt_text,
                key_points=[
                    theme,
                    colors or "clear primary color structure",
                    styles or "modern industrial",
            image_keywords or "no selected image keywords",
                ],
            )
        )
    return schemes


class CreativeDialogueAndImageAgent:
    def __init__(self) -> None:
        if not HAS_LANGGRAPH or StateGraph is None:
            raise AgentRuntimeDependencyError(
                "LangGraph is required but not installed. Install `langgraph` to enable AI agent runtime."
            )

        builder = StateGraph(_GraphState)
        builder.add_node("route", self._route_node)
        builder.add_node("creative_agent_prompt", self._creative_prompt_node)
        builder.add_node("image_agent_prompt", self._image_prompt_node)
        builder.add_edge(START, "route")
        builder.add_conditional_edges(
            "route",
            self._route_branch,
            {
                "creative": "creative_agent_prompt",
                "image": "image_agent_prompt",
            },
        )
        builder.add_edge("creative_agent_prompt", END)
        builder.add_edge("image_agent_prompt", END)
        self._graph = builder.compile()

    def _route_node(self, state: _GraphState) -> _GraphState:
        declared_mode = str(state.get("mode", "creative")).strip().lower()
        route: RouteMode = "image" if declared_mode == "image" else "creative"
        return {**state, "route": route}

    @staticmethod
    def _route_branch(state: _GraphState) -> RouteMode:
        route = state.get("route")
        return "image" if route == "image" else "creative"

    def _creative_prompt_node(self, state: _GraphState) -> _GraphState:
        summary = state.get("context_summary", "")
        prompt = (
            "You are Co-Track Creative Assistant Agent.\n"
            "You support industrial appearance design teams with actionable advice.\n"
            "Be concise, practical, and design-oriented.\n"
            "When useful, provide palette ratio, element placement, and risk reminders.\n"
            "Reply in Chinese unless the user explicitly requests another language.\n"
        )
        if summary:
            prompt = f"{prompt}\nContext:\n{summary}"
        return {**state, "system_prompt": prompt}

    def _image_prompt_node(self, state: _GraphState) -> _GraphState:
        summary = state.get("context_summary", "")
        prompt = (
            "You are Co-Track Pattern Generation Agent.\n"
            "Help users refine prompt wording for 2D coating pattern generation.\n"
            "Prioritize manufacturability, readability at long distance, and brand consistency.\n"
            "Provide concrete prompt refinements and constraints.\n"
            "Reply in Chinese unless the user explicitly requests another language.\n"
        )
        if summary:
            prompt = f"{prompt}\nContext:\n{summary}"
        return {**state, "system_prompt": prompt}

    async def plan_chat(self, *, mode: str, message: str, context: SessionAiContext) -> CreativeRoutePlan:
        context_summary = _build_context_summary(context)
        state = _GraphState(
            mode=mode,
            message=message,
            context_summary=context_summary,
            route="creative",
            system_prompt="",
        )
        result = await self._graph.ainvoke(state)
        route = "image" if result.get("route") == "image" else "creative"
        system_prompt = str(result.get("system_prompt", "")).strip()
        if not system_prompt:
            system_prompt = "You are Co-Track AI Assistant."
        return CreativeRoutePlan(route=route, system_prompt=system_prompt)

    async def plan_texture_schemes(
        self,
        *,
        provider: OpenAITextImageProvider,
        context: TexturePlanningContext,
    ) -> TexturePlanResult:
        brief_keywords = extract_brief_keywords(context.brief_json)
        payload = _build_texture_context_summary(context)
        system_prompt = (
            "You are Co-Track Model Texture Planning Agent.\n"
            "You create three clearly differentiated model texture prompt schemes for industrial appearance design.\n"
            "You must synthesize the brief keywords, user text, document text, image style keywords, and base model context.\n"
            "Decide the three most valuable differentiated directions by yourself instead of using preset categories.\n"
            "Each scheme must be meaningfully different in concept, visual language, graphic rhythm, material feeling, or color deployment.\n"
            "Prioritize manufacturability, readability on large surfaces, brand consistency, and texture continuity on a 3D model.\n"
            "Return strict JSON only.\n"
        )
        user_prompt = json.dumps(
            {
                "task": "plan_model_texture_schemes",
                "context": payload,
                "output_schema": {
                    "schemes": [
                        {
                            "id": "scheme_1",
                            "title": "string",
                            "strategy": "string",
                            "prompt_text": "string",
                            "key_points": ["string"],
                        }
                    ]
                },
                "rules": [
                    "return exactly 3 schemes in fixed order",
                    "ids must be scheme_1, scheme_2, scheme_3",
                    "do not use markdown",
                    "title and strategy should be short",
                    "prompt_text should be concrete and editable",
                    "key_points should be concise and non-repetitive",
                    "the three schemes must be clearly different, not just light rewrites",
                ],
            },
            ensure_ascii=False,
        )

        parsed = await provider.complete_json(
            system_prompt=system_prompt,
            user_message=user_prompt,
            history=[],
            temperature=0.3,
        )
        schemes = _normalize_texture_schemes(parsed.get("schemes") if isinstance(parsed, dict) else None)

        if not _schemes_are_sufficiently_distinct(schemes):
            retry_prompt = (
                f"{user_prompt}\n\nAdditional requirement: "
                "The previous schemes were too similar. Please regenerate and significantly increase the differences "
                "between the three schemes in concept, visual language, composition rhythm, and prompt wording."
            )
            retry_parsed = await provider.complete_json(
                system_prompt=system_prompt,
                user_message=retry_prompt,
                history=[],
                temperature=0.45,
            )
            retry_schemes = _normalize_texture_schemes(
                retry_parsed.get("schemes") if isinstance(retry_parsed, dict) else None
            )
            if _schemes_are_sufficiently_distinct(retry_schemes):
                schemes = retry_schemes

        if not _schemes_are_sufficiently_distinct(schemes):
            schemes = _fallback_texture_schemes(context)

        return TexturePlanResult(
            schemes=schemes,
            brief_keywords=brief_keywords,
            selected_image_keywords=context.selected_image_keywords[:12],
        )


# Backward-compatible aliases for existing imports.
ChatPlan = CreativeRoutePlan
AgentRuntime = CreativeDialogueAndImageAgent
