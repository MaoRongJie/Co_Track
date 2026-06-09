from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agents.providers.pattern_image_provider import PatternImageProvider
from app.image_analysis import extract_image_metrics, image_reference_to_data_url


@dataclass(slots=True)
class PatternAssetContext:
    session_id: int
    result_id: str
    preview_mode: str
    workspace_id: str
    pattern_prompt_text: str
    brief_json: dict[str, Any] | None
    brief_keywords: dict[str, Any]
    selected_image_keywords: list[str]
    texture_prompt_text: str
    texture_reference: str | None
    canvas_snapshot_data_url: str | None


@dataclass(slots=True)
class PatternAssetResult:
    prompt: str
    style_hint: str | None
    revised_prompt: str | None
    image_url: str
    analysis_summary: str
    dominant_colors: list[str]
    provider_payload: dict[str, Any] | None


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


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class PatternAssetAgent:
    async def generate_pattern_asset(
        self,
        *,
        provider: PatternImageProvider,
        context: PatternAssetContext,
    ) -> PatternAssetResult:
        texture_metrics = extract_image_metrics(context.texture_reference)
        primary_visual_reference = context.canvas_snapshot_data_url or context.texture_reference
        visual_metrics = extract_image_metrics(primary_visual_reference)
        visual_source_data_url = image_reference_to_data_url(primary_visual_reference)

        visual_analysis = await self._analyze_visual_source(
            provider=provider,
            context=context,
            visual_source_data_url=visual_source_data_url,
            texture_metrics=texture_metrics,
            visual_metrics=visual_metrics,
        )
        prompt_bundle = await self._compose_generation_prompt(
            provider=provider,
            context=context,
            texture_metrics=texture_metrics,
            visual_metrics=visual_metrics,
            visual_analysis=visual_analysis,
        )

        generated_items = await provider.generate_image(
            prompt=prompt_bundle["prompt"],
            style_hint=prompt_bundle.get("style_hint"),
            background="transparent",
            output_format="png",
        )
        generated = generated_items[0]
        return PatternAssetResult(
            prompt=prompt_bundle["prompt"],
            style_hint=prompt_bundle.get("style_hint"),
            revised_prompt=generated.revised_prompt,
            image_url=generated.image_url,
            analysis_summary=prompt_bundle["analysis_summary"],
            dominant_colors=_safe_list(prompt_bundle.get("dominant_colors"), max_items=4),
            provider_payload=generated.provider_payload,
        )

    async def _analyze_visual_source(
        self,
        *,
        provider: PatternImageProvider,
        context: PatternAssetContext,
        visual_source_data_url: str | None,
        texture_metrics: dict[str, Any],
        visual_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        if not visual_source_data_url:
            return self._fallback_visual_analysis(context=context, texture_metrics=texture_metrics, visual_metrics=visual_metrics)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Co-Track 图案素材视觉分析 Agent。"
                    "请分析列车纹理或 UV 画布截图，并提取简单、可制造的图案线索。"
                    "只返回严格 JSON。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请分析该视觉参考，用于生成一个简单贴花/图案素材，而不是完整车辆渲染图。\n"
                            f"用户图案意图：{_safe_text(context.pattern_prompt_text, default='无')}\n"
                            f"纹理方案提示词：{_safe_text(context.texture_prompt_text, default='无')}\n"
                            f"设计简报关键词：{json.dumps(context.brief_keywords, ensure_ascii=False)}\n"
                            f"纹理指标：{json.dumps(texture_metrics, ensure_ascii=False)}\n"
                            f"视觉指标：{json.dumps(visual_metrics, ensure_ascii=False)}\n"
                            '请按以下 schema 返回 JSON：{"shape_motifs":["string"],"line_quality":"string","composition_rhythm":"string","complexity":"low|medium|high","palette_advice":["string"],"negative_constraints":["string"],"visual_summary":"string"}。'
                            "图形母题应简洁、工业化，并便于制造。"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": visual_source_data_url, "detail": "low"}},
                ],
            },
        ]
        parsed = await provider.complete_json_with_messages(
            messages=messages,
            temperature=0.15,
            model=provider.vision_model,
        )
        if isinstance(parsed, dict) and parsed:
            return {
                "shape_motifs": _safe_list(parsed.get("shape_motifs"), max_items=5),
                "line_quality": _safe_text(parsed.get("line_quality"), default="干净且具有方向性的曲线"),
                "composition_rhythm": _safe_text(parsed.get("composition_rhythm"), default="有层次但克制"),
                "complexity": _safe_text(parsed.get("complexity"), default="low"),
                "palette_advice": _safe_list(parsed.get("palette_advice"), max_items=4),
                "negative_constraints": _safe_list(parsed.get("negative_constraints"), max_items=6),
                "visual_summary": _safe_text(parsed.get("visual_summary"), default="保持图案紧凑，并与现有纹理兼容。"),
            }
        return self._fallback_visual_analysis(context=context, texture_metrics=texture_metrics, visual_metrics=visual_metrics)

    async def _compose_generation_prompt(
        self,
        *,
        provider: PatternImageProvider,
        context: PatternAssetContext,
        texture_metrics: dict[str, Any],
        visual_metrics: dict[str, Any],
        visual_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        brief_payload = {
            "pattern_prompt_text": _safe_text(context.pattern_prompt_text),
            "texture_prompt_text": _safe_text(context.texture_prompt_text),
            "brief_keywords": context.brief_keywords,
            "selected_image_keywords": context.selected_image_keywords[:8],
            "texture_metrics": texture_metrics,
            "visual_metrics": visual_metrics,
            "visual_analysis": visual_analysis,
        }
        system_prompt = (
            "你是 Co-Track 图案素材生成 Agent。"
            "请为一个可粘贴到 UV 画布上的独立图案/贴花素材生成最终图像生成提示词。"
            "素材必须保持简单、可制造，并与当前列车纹理紧密匹配。"
            "只返回严格 JSON。"
        )
        user_prompt = json.dumps(
            {
                "task": "compose_pattern_asset_prompt",
                "context": brief_payload,
                "output_schema": {
                    "prompt": "string",
                    "styleHint": "string",
                    "analysisSummary": "string",
                    "dominantColors": ["string"],
                },
                "rules": [
                    "描述一个单独的独立图案素材，不要描述列车车身或样机",
                    "只使用透明背景",
                    "不要出现文字、标识、阴影、场景或写实物体摆拍",
                    "保持低复杂度，并控制颜色数量",
                    "图案语言应与当前方案和用户图案提示词保持一致",
                    "优先使用 2-3 个主导色",
                ],
            },
            ensure_ascii=False,
        )
        parsed = await provider.complete_json(
            system_prompt=system_prompt,
            user_message=user_prompt,
            history=[],
            temperature=0.2,
        )
        if isinstance(parsed, dict) and _safe_text(parsed.get("prompt")):
            return {
                "prompt": _safe_text(parsed.get("prompt")),
                "style_hint": _safe_text(parsed.get("styleHint")) or None,
                "analysis_summary": _safe_text(parsed.get("analysisSummary"), default=self._fallback_analysis_summary(context=context, visual_analysis=visual_analysis)),
                "dominant_colors": _safe_list(parsed.get("dominantColors"), max_items=4)
                or _safe_list(visual_metrics.get("dominant_colors"), max_items=4),
            }
        return self._fallback_prompt_bundle(context=context, visual_metrics=visual_metrics, visual_analysis=visual_analysis)

    def _fallback_visual_analysis(
        self,
        *,
        context: PatternAssetContext,
        texture_metrics: dict[str, Any],
        visual_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        prompt_hint = _safe_text(context.pattern_prompt_text).lower()
        motifs = _safe_list(_safe_dict(context.brief_json).get("designElements"), max_items=3)
        if not motifs:
            motifs = _safe_list(context.brief_keywords.get("design_elements"), max_items=3)
        if "snow" in prompt_hint or "ice" in prompt_hint or "雪" in prompt_hint or "冰" in prompt_hint:
            motifs = ["收束晶体碎片", "方向性速度线", "切面 ribbon 图形"]
        elif "wave" in prompt_hint or "flow" in prompt_hint or "波" in prompt_hint or "流" in prompt_hint:
            motifs = ["流线曲线", "尾流状条带", "分层 ribbon 图形"]
        elif not motifs:
            motifs = ["方向性 ribbon 图形", "几何条带", "收束强调元素"]
        complexity = "low" if int(visual_metrics.get("edge_complexity_score") or texture_metrics.get("edge_complexity_score") or 0) < 42 else "medium"
        return {
            "shape_motifs": motifs,
            "line_quality": "干净、具有方向性和工业感的线条",
            "composition_rhythm": "克制的分层节奏，并保留一个主要动势",
            "complexity": complexity,
            "palette_advice": _safe_list(visual_metrics.get("dominant_colors"), max_items=3),
            "negative_constraints": [
                "不要写实阴影",
                "不要过密装饰",
                "不要文字或品牌标记",
            ],
            "visual_summary": "保持生成图案紧凑、清晰，并与当前纹理节奏一致。",
        }

    def _fallback_prompt_bundle(
        self,
        *,
        context: PatternAssetContext,
        visual_metrics: dict[str, Any],
        visual_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        dominant_colors = _safe_list(visual_metrics.get("dominant_colors"), max_items=3) or ["#cbd5e1", "#94a3b8"]
        motifs = "、".join(_safe_list(visual_analysis.get("shape_motifs"), max_items=3) or ["方向性 ribbon 图形"])
        user_prompt = _safe_text(context.pattern_prompt_text)
        texture_prompt = _safe_text(context.texture_prompt_text, default="当前列车外观纹理")
        palette_advice = "、".join(_safe_list(visual_analysis.get("palette_advice"), max_items=3) or dominant_colors)
        prompt = (
            "请为高速列车外观纹理创建一个独立工业贴花/图案素材。"
            f"用户图案意图：{user_prompt or '从当前方案推导'}。"
            f"纹理方案方向：{texture_prompt}。"
            f"形态母题：{motifs}。"
            f"主导颜色应贴近：{'、'.join(dominant_colors)}。"
            f"色彩建议：{palette_advice}。"
            "保持图案简单、平面、干净、可制造，并适合 UV 画布合成。"
            "透明背景。不要出现列车车身、样机、场景、文字、标识、投影或复杂装饰。"
        )
        return {
            "prompt": prompt,
            "style_hint": "极简工业贴花素材，控制颜色数量，边缘清晰并接近矢量质感。",
            "analysis_summary": self._fallback_analysis_summary(context=context, visual_analysis=visual_analysis),
            "dominant_colors": dominant_colors,
        }

    def _fallback_analysis_summary(self, *, context: PatternAssetContext, visual_analysis: dict[str, Any]) -> str:
        motifs = _safe_list(visual_analysis.get("shape_motifs"), max_items=3)
        motif_text = "、".join(motifs) if motifs else "方向性图案线索"
        if _safe_text(context.pattern_prompt_text):
            return f"图案使用 {motif_text}，并与用户提示词和当前纹理色盘保持一致。"
        return f"图案使用 {motif_text}，并与当前纹理色盘和表面节奏保持一致。"
