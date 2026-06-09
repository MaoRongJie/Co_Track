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


def _safe_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _dedupe_texts(values: list[str], *, max_items: int = 6) -> list[str]:
    picked: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        picked.append(text)
        if len(picked) >= max_items:
            break
    return picked


def _compact_text(value: str, *, max_chars: int = 280) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _combine_lists(*groups: list[str], max_items: int = 6) -> list[str]:
    merged: list[str] = []
    for group in groups:
        merged.extend(group)
    return _dedupe_texts(merged, max_items=max_items)


def _join_parts(parts: list[str], *, separator: str = " | ") -> str:
    normalized = [part.strip() for part in parts if part and part.strip()]
    return separator.join(normalized)


def _split_goal_chunks(goal: str) -> list[str]:
    chunks = re.split(r"[\u3001\uFF0C\uFF1B;,\n]+", goal)
    return [item.strip() for item in chunks if item and item.strip()]


def _heuristic_brief(goal: str, category: str) -> dict[str, object]:
    chunks = _split_goal_chunks(goal)
    lowered = goal.lower()
    train_categories = {"high_speed_train", "intercity_train", "metro_vehicle"}

    style_keywords: list[str] = []
    if any(token in lowered for token in ("streamline", "streamlined", "aerodynamic", "speed", "fast", "swift", "流线", "速度", "高速", "动势")):
        style_keywords.extend(["流线", "方向性", "轻快"])
    if any(token in lowered for token in ("tech", "future", "futur", "digital", "advanced", "科技", "未来", "数字", "先进")):
        style_keywords.extend(["精确", "先进", "干净"])
    if any(token in lowered for token in ("premium", "luxury", "refined", "elegant", "高级", "豪华", "精致", "优雅")):
        style_keywords.extend(["精致", "自信"])
    if any(token in lowered for token in ("calm", "clean", "minimal", "simple", "平静", "干净", "极简", "简洁")):
        style_keywords.extend(["平静", "极简"])
    style_keywords.extend(chunks[1:4])
    style_keywords = _dedupe_texts(style_keywords, max_items=5)

    reference_imagery: list[str] = []
    if any(token in lowered for token in ("winter", "snow", "ice", "frost", "冬", "雪", "冰", "霜")):
        reference_imagery.extend(["雪原风痕", "冰川光感", "冰面风流"])
    if any(token in lowered for token in ("wave", "ocean", "sea", "stream", "river", "波", "海", "流", "河")):
        reference_imagery.extend(["河流流向", "表面尾流"])
    if any(token in lowered for token in ("stripe", "band", "flow", "motion", "条纹", "条带", "流动", "运动")):
        reference_imagery.extend(["方向性 ribbon 图形"])
    if any(token in lowered for token in ("tech", "digital", "future", "科技", "数字", "未来")):
        reference_imagery.extend(["精密线性结构", "工业极简"])
    reference_imagery = _dedupe_texts(
        reference_imagery or ["风塑表面", "安静的工业极简"],
        max_items=4,
    )

    if any(token in lowered for token in ("winter", "snow", "ice", "frost", "blue", "white", "冬", "雪", "冰", "蓝", "白")):
        color_tendency = "冷调、明亮、偏冬季的色彩氛围"
        accent_tendency = "克制的金属对比"
    elif any(token in lowered for token in ("green", "leaf", "eco", "nature", "绿", "叶", "生态", "自然")):
        color_tendency = "清新、干净、偏自然的色彩氛围"
        accent_tendency = "轻量技术感对比"
    elif any(token in lowered for token in ("red", "warm", "energy", "dynamic", "红", "暖", "能量", "动感")):
        color_tendency = "温暖、有能量、具有适度对比的色彩氛围"
        accent_tendency = "可控的深色对比"
    elif any(token in lowered for token in ("black", "silver", "metal", "premium", "黑", "银", "金属", "高级")):
        color_tendency = "中性金属感、克制高级的色彩氛围"
        accent_tendency = "清晰的光感对比"
    else:
        color_tendency = "干净的当代工业色彩氛围"
        accent_tendency = "可控的对比强调"

    theme = chunks[0] if chunks else "工业外观概念"
    core_experience = theme or "快速、可靠且当代"
    if category in train_categories:
        cultural_positioning = "先进公共交通形象，并传达可靠的大型工程信任感"
        craft_constraints = [
            "支持大面积外观涂层，并具备耐候耐久表面",
            "分区应便于长车体遮蔽、补漆和维护",
        ]
        regulatory_constraints = [
            "保留列车识别、安全标识和运营编号的可见性",
            "符合轨道车辆外观涂层耐久性和安全合规要求",
        ]
    elif category == "automobile":
        cultural_positioning = "面向消费者的前瞻移动形象，强调精确感与信任感"
        craft_constraints = [
            "适配汽车涂装流程和耐久外观要求",
            "避免破坏覆盖件逻辑或增加维护脆弱性的图形",
        ]
        regulatory_constraints = [
            "保持法定信号、标记和关键可视区域清晰",
            "符合汽车安全和道路可见性要求",
        ]
    else:
        cultural_positioning = "现代工业可信度，并具有可靠、亲和的品牌性格"
        craft_constraints = [
            "保持表面可制造，涂层过渡稳定，并便于维护接近",
            "优先使用稳健的大尺度图形，避免过度精细装饰",
        ]
        regulatory_constraints = [
            "保持必要安全标签、警示信息和品牌识别的可读性",
            "符合适用的外观安全和耐久性要求",
        ]

    locked_items: list[str] = []
    if any(token in lowered for token in ("winter", "snow", "ice", "frost", "冬", "雪", "冰")):
        locked_items.append("保持冬季叙事清晰可读，但避免装饰过载。")
    if any(token in lowered for token in ("streamline", "streamlined", "speed", "fast", "aerodynamic", "流线", "速度", "高速", "动势")):
        locked_items.append("在外观整体上保留明确的方向感和运动感。")
    if any(token in lowered for token in ("brand", "logo", "identity", "品牌", "标识", "识别")):
        locked_items.append("在运营观看距离下保持品牌和识别信息清晰。")
    locked_items = _dedupe_texts(
        locked_items
        or [
            "保持清晰的品牌识别和功能识别。",
            "确保涂层方向适合大面积外观表面制造。",
        ],
        max_items=5,
    )

    soft_directions = _dedupe_texts(
        [
            "让外观表达更具联想性，而不是停留在直白图案。",
            "优先使用长方向流动，而不是孤立装饰母题。",
            *style_keywords,
        ],
        max_items=5,
    )

    open_narrative = _compact_text(goal or theme)
    constraints_hint = _join_parts(
        [
            f"工艺/技术：{'; '.join(craft_constraints[:2])}",
            f"法规/安全：{'; '.join(regulatory_constraints[:2])}",
        ]
    )

    return {
        "why": {
            "coreExperienceIntent": core_experience,
            "culturalBrandPositioning": cultural_positioning,
        },
        "what": {
            "colorTendency": color_tendency,
            "visualStyleKeywords": style_keywords,
            "referenceImagery": reference_imagery,
        },
        "how": {
            "craftTechConstraints": craft_constraints,
            "regulatoryConstraints": regulatory_constraints,
        },
        "openNarrative": open_narrative,
        "lockedItems": locked_items,
        "softDirections": soft_directions,
        "theme": core_experience,
        "mainColors": [color_tendency],
        "accentColors": [accent_tendency],
        "styleKeywords": style_keywords,
        "designElements": reference_imagery,
        "constraintsHint": constraints_hint,
        "productCategory": category,
    }


def _build_constraints_hint(
    *,
    craft_tech_constraints: list[str],
    regulatory_constraints: list[str],
    locked_items: list[str],
) -> str:
    parts: list[str] = []
    if craft_tech_constraints:
        parts.append(f"工艺/技术：{'; '.join(craft_tech_constraints[:2])}")
    if regulatory_constraints:
        parts.append(f"法规/安全：{'; '.join(regulatory_constraints[:2])}")
    if locked_items:
        parts.append(f"锁定项：{'; '.join(locked_items[:2])}")
    return _join_parts(parts)


def _normalize_brief_payload(*, raw: dict[str, object], design_goal: str, category: str) -> dict[str, object]:
    default_payload = _heuristic_brief(design_goal, category)

    raw_why = _safe_dict(raw.get("why"))
    raw_what = _safe_dict(raw.get("what"))
    raw_how = _safe_dict(raw.get("how"))

    fallback_why = _safe_dict(default_payload.get("why"))
    fallback_what = _safe_dict(default_payload.get("what"))
    fallback_how = _safe_dict(default_payload.get("how"))

    legacy_theme = _safe_text(raw.get("theme"))
    legacy_main_colors = _safe_list(raw.get("mainColors"), max_items=4)
    legacy_accent_colors = _safe_list(raw.get("accentColors"), max_items=4)
    legacy_style_keywords = _safe_list(raw.get("styleKeywords"), max_items=8)
    legacy_design_elements = _safe_list(raw.get("designElements"), max_items=8)
    legacy_constraints = _safe_text(raw.get("constraintsHint"))

    why = {
        "coreExperienceIntent": _safe_text(
            raw_why.get("coreExperienceIntent"),
            default=legacy_theme or _safe_text(fallback_why.get("coreExperienceIntent"), default="Industrial appearance concept"),
        ),
        "culturalBrandPositioning": _safe_text(
            raw_why.get("culturalBrandPositioning"),
            default=_safe_text(fallback_why.get("culturalBrandPositioning"), default=""),
        ),
    }

    visual_style_keywords = _safe_list(raw_what.get("visualStyleKeywords"), max_items=5) or legacy_style_keywords[:5]
    visual_style_keywords = visual_style_keywords or _safe_list(fallback_what.get("visualStyleKeywords"), max_items=5)

    reference_imagery = _safe_list(raw_what.get("referenceImagery"), max_items=4) or legacy_design_elements[:4]
    reference_imagery = reference_imagery or _safe_list(fallback_what.get("referenceImagery"), max_items=4)

    what = {
        "colorTendency": _safe_text(
            raw_what.get("colorTendency"),
            default=(legacy_main_colors[0] if legacy_main_colors else _safe_text(fallback_what.get("colorTendency"), default="")),
        ),
        "visualStyleKeywords": visual_style_keywords,
        "referenceImagery": reference_imagery,
    }

    craft_tech_constraints = _safe_list(raw_how.get("craftTechConstraints"), max_items=5)
    if not craft_tech_constraints and legacy_constraints:
        craft_tech_constraints = [legacy_constraints]
    craft_tech_constraints = craft_tech_constraints or _safe_list(fallback_how.get("craftTechConstraints"), max_items=5)

    regulatory_constraints = _safe_list(raw_how.get("regulatoryConstraints"), max_items=5)
    regulatory_constraints = regulatory_constraints or _safe_list(fallback_how.get("regulatoryConstraints"), max_items=5)

    locked_items = _safe_list(raw.get("lockedItems"), max_items=5)
    locked_items = locked_items or _safe_list(default_payload.get("lockedItems"), max_items=5)

    soft_directions = _safe_list(raw.get("softDirections"), max_items=5)
    soft_directions = soft_directions or _combine_lists(visual_style_keywords, reference_imagery, max_items=5)
    soft_directions = soft_directions or _safe_list(default_payload.get("softDirections"), max_items=5)

    how = {
        "craftTechConstraints": craft_tech_constraints,
        "regulatoryConstraints": regulatory_constraints,
    }

    open_narrative = _compact_text(
        _safe_text(raw.get("openNarrative"), default=_safe_text(default_payload.get("openNarrative"), default=design_goal))
    )

    theme = legacy_theme or why["coreExperienceIntent"] or _safe_text(default_payload.get("theme"), default="Design concept")
    main_colors = legacy_main_colors or ([what["colorTendency"]] if what["colorTendency"] else [])
    main_colors = main_colors or _safe_list(default_payload.get("mainColors"), max_items=4)
    accent_colors = legacy_accent_colors or _safe_list(default_payload.get("accentColors"), max_items=4)
    style_keywords = legacy_style_keywords or visual_style_keywords
    style_keywords = style_keywords or _safe_list(default_payload.get("styleKeywords"), max_items=8)
    design_elements = legacy_design_elements or reference_imagery
    design_elements = design_elements or _safe_list(default_payload.get("designElements"), max_items=8)
    constraints_hint = legacy_constraints or _build_constraints_hint(
        craft_tech_constraints=craft_tech_constraints,
        regulatory_constraints=regulatory_constraints,
        locked_items=locked_items,
    )
    if not constraints_hint:
        constraints_hint = _safe_text(default_payload.get("constraintsHint"), default="")

    return {
        "why": why,
        "what": what,
        "how": how,
        "openNarrative": open_narrative,
        "lockedItems": locked_items,
        "softDirections": soft_directions,
        "theme": theme,
        "mainColors": main_colors,
        "accentColors": accent_colors,
        "styleKeywords": style_keywords,
        "designElements": design_elements,
        "constraintsHint": constraints_hint,
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

        system_prompt = """你是 Co-Track 第一阶段任务识别 Agent，服务于协同式高速铁路外观涂层设计平台。

你的任务是把设计师输入的自然语言简报解析为三层结构化设计模型：

  WHY  - 情感与文化意图：观察者应产生什么感受？方案表达什么身份或文化定位？
  WHAT - 视觉方向：保持相对开放，避免过早锁定具体颜色或元素。
  HOW  - 硬性边界：区分工艺/技术约束与法规/安全约束。

补充字段：
  openNarrative  - 保留原始简报的语气与感受，不要把细节和语义压缩掉。
  lockedItems    - 协作者必须遵守的不可协商约束。
  softDirections - 可以被协作者挑战、延展或重新解释的方向性建议。

设计原则：在探索早期尽量保留方案可能性。
  - colorTendency 应描述总体色相或情绪倾向，而不是具体十六进制颜色或固定色盘名称。
  - referenceImagery 应使用隐喻、自然现象或艺术运动，而不是产品或品牌名称。
  - 优先使用具有启发性、可解释的语言，而不是过早精确的规格描述。

只返回严格 JSON。不要使用 markdown。不要添加额外字段。"""
        user_prompt = json.dumps(
            {
                "task": "parse_brief",
                "design_goal": design_goal,
                "product_category": product_category,
                "output_schema": {
                    "why": {
                        "coreExperienceIntent": "string - 观察者应产生的直观感受",
                        "culturalBrandPositioning": "string - 传达的国家、品牌或时代身份",
                    },
                    "what": {
                        "colorTendency": "string - 宽泛色相或情绪方向，不写具体颜色",
                        "visualStyleKeywords": ["string - 最多 5 个有启发性的形容词"],
                        "referenceImagery": ["string - 隐喻、自然或艺术参考，最多 4 项"],
                    },
                    "how": {
                        "craftTechConstraints": ["string - 材料、工艺、耐久性要求"],
                        "regulatoryConstraints": ["string - 行业标准、安全规则"],
                    },
                    "openNarrative": "string - 保留简报原始语气和细微含义",
                    "lockedItems": ["string - 必须遵守的不可协商事项"],
                    "softDirections": ["string - 可由协作者重新解释的方向性建议"],
                },
                "rules": [
                    "数组保持简洁，每项最多 5 条",
                    "colorTendency 不能包含十六进制颜色或“橙红色”等具体色名",
                    "referenceImagery 应使用隐喻，不要使用产品名或品牌名",
                    "craftTechConstraints 和 regulatoryConstraints 必须分开",
                    "openNarrative 用 1-2 句保留简报原始表达",
                    "不要添加 markdown 或额外字段",
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
        brief_json = _normalize_brief_payload(
            raw=raw if isinstance(raw, dict) else {},
            design_goal=design_goal,
            category=category,
        )
        return {**state, "brief_json": brief_json}

    async def _generation_intent_node(self, state: _ModelState) -> _ModelState:
        product_category = state["product_category"]
        product_profile = state["product_profile"]
        brief_json = state["brief_json"]
        what = _safe_dict(brief_json.get("what"))

        heuristic_intent: dict[str, object] = {
            "shapeKeywords": _safe_list(brief_json.get("designElements"), max_items=6)
            or _safe_list(what.get("referenceImagery"), max_items=6),
            "styleKeywords": _safe_list(brief_json.get("styleKeywords"), max_items=8)
            or _safe_list(what.get("visualStyleKeywords"), max_items=8),
            "surfaceFinish": "适合涂装的平滑外壳",
            "keepSymmetry": bool(product_profile.get("isSymmetric", True)),
            "targetUvSpec": "4096x2048" if product_category in {"high_speed_train", "intercity_train", "metro_vehicle"} else "2048x1024",
        }

        system_prompt = (
            "你是 Co-Track 第一阶段 3D 相似性规划 Agent。"
            "请把产品画像和设计简报转化为 3D 生成意图 JSON，只返回 JSON。"
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
                    "surfaceFinish": _safe_text(parsed.get("surfaceFinish"), default="适合涂装的平滑外壳"),
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
        why = _safe_dict(brief_json.get("why"))
        what = _safe_dict(brief_json.get("what"))

        theme = _safe_text(
            brief_json.get("theme"),
            default=_safe_text(why.get("coreExperienceIntent"), default="工业外观"),
        )
        color_hints = ", ".join(_safe_list(brief_json.get("mainColors"), max_items=4))
        if not color_hints:
            color_hints = _safe_text(what.get("colorTendency"), default="")
        shape_keywords = ", ".join(_safe_list(generation_intent.get("shapeKeywords"), max_items=6))
        style_keywords = ", ".join(_safe_list(generation_intent.get("styleKeywords"), max_items=6))
        surface_finish = _safe_text(generation_intent.get("surfaceFinish"), default="适合涂装的平滑外壳")
        uv_spec = _safe_text(generation_intent.get("targetUvSpec"), default="2048x1024")
        profile_text = _profile_to_text(product_profile)
        narrative = _safe_text(brief_json.get("openNarrative"), default="")
        cultural_positioning = _safe_text(why.get("culturalBrandPositioning"), default="")
        locked_items = ", ".join(_safe_list(brief_json.get("lockedItems"), max_items=4))

        prompt = (
            "请为协同涂层设计创建一个近似的工业产品参考模型。"
            f"产品类别：{product_category}。"
            f"主题：{theme}。"
            f"体验定位：{cultural_positioning or '可靠的工业现代感'}。"
            f"开放叙事：{narrative or theme}。"
            f"形态关键词：{shape_keywords or '干净的流线轮廓'}。"
            f"风格关键词：{style_keywords or '工业现代'}。"
            f"色彩倾向：{color_hints or '干净的当代工业色调'}。"
            f"锁定项：{locked_items or '保持可制造、可协作的基础模型'}。"
            f"表面处理：{surface_finish}。"
            f"产品画像：{profile_text}。"
            "输出应优先采用简单拓扑和稳定 UV 接缝，以服务后续绘制工作流。"
            f"目标 UV 建议：{uv_spec}。"
        )
        negative_prompt = (
            "不要出现人物、背景场景、文字标识、透明外壳或内部细节，避免过多细小零件。"
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
