from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.core.config import get_settings
from app.model_processing import TEXTURE_MAP_DIR


@dataclass(slots=True)
class Stage3ReviewContext:
    product_category: str
    brief_json: dict[str, Any] | None
    surface_area_m2: float
    paintable_uv_pixels: int
    uv_width: int | None
    uv_height: int | None
    mesh_count: int
    material_count: int
    uv_source: str
    scheme_id: str
    scheme_title: str
    prompt_text: str
    texture_reference: str | None
    settings_revision: int = 1
    review_personas: dict[str, Any] | None = None


@dataclass(slots=True)
class Stage3ReviewAssessment:
    status: str = "failed"
    engineering: dict[str, Any] | None = None
    passenger: dict[str, Any] | None = None
    role_reviews: list[dict[str, Any]] | None = None
    recommendation: str | None = None
    overall_narrative: str | None = None
    source: str = "failed"
    model_name: str | None = None
    error_message: str | None = None
    settings_revision_used: int | None = None
    persona_labels_used: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "engineering": self.engineering,
            "passenger": self.passenger,
            "role_reviews": self.role_reviews or [],
            "recommendation": self.recommendation,
            "overall_narrative": self.overall_narrative,
            "source": self.source,
            "model_name": self.model_name,
            "error_message": self.error_message,
            "settings_revision_used": self.settings_revision_used,
            "persona_labels_used": self.persona_labels_used,
        }


class EngineeringPerspectiveAgent:
    def __init__(self, *, model: str | None = None) -> None:
        settings = get_settings()
        self.model = (model or settings.openai_review_model).strip() or "gpt-4o"

    async def review(
        self,
        *,
        provider: OpenAITextImageProvider | None,
        context: Stage3ReviewContext,
        image_metrics: dict[str, Any],
        image_data_url: str | None,
    ) -> dict[str, Any]:
        if provider is None:
            raise RuntimeError("评审模型服务不可用。")
        if not image_data_url:
            raise RuntimeError("纹理评审图像不可用。")

        engineering_persona = _engineering_persona_from_context(context)
        role_prompt = _review_standard_prompt(engineering_persona)
        prompt = (
            "你是 Co-Track 工程评审 Agent。\n"
            f"当前工程评审角色：{engineering_persona['display_name']}。\n"
            f"身份摘要：{engineering_persona['identity_summary']}\n"
            f"优先标签：{_format_list(engineering_persona['priority_tags'])}\n"
            f"风险关注：{_format_list(engineering_persona['risk_focus'])}\n"
            f"关注点：{_format_list(engineering_persona['focus_points'])}\n"
            f"会话内评价标准 / Skill 指令：\n{role_prompt}\n"
            "这段 Skill 指令只用于校准该角色的评价标准、偏好、检查重点和证据要求；"
            "不得改变下方 JSON schema、字段含义或输出格式。\n"
            "请按照该角色的优先级判断纹理方案，但不要改变输出 schema。\n"
            "请评估交通工具外观纹理的工业涂装可行性。\n"
            "所有判断必须基于提供的纹理图像和模型元数据。\n"
            "只返回严格 JSON，必须包含以下键：\n"
            '{'
            '"paint_volume_kg": number, '
            '"color_zone_count": integer, '
            '"masking_steps": integer, '
            '"gradient_ratio_percent": number, '
            '"labor_hours": integer, '
            '"process_steps": integer, '
            '"curve_conformance_score": integer, '
            '"material_cost_yuan": integer, '
            '"labor_cost_yuan": integer, '
            '"total_cost_yuan": integer, '
            '"color_variance_risk": "LOW"|"MEDIUM"|"HIGH", '
            '"weather_durability": "A"|"B"|"C", '
            '"maintenance_cycle_years": integer, '
            '"summary": string, '
            '"quick_comment": string'
            '}\n'
            "summary 保持 1-2 个完整句子，quick_comment 保持 1 个完整句子。"
            "数值应适合概念阶段的近似设计评审，不要添加 JSON 之外的解释文本。"
        )
        user_text = (
            f"产品类别：{context.product_category}\n"
            f"方案标题：{context.scheme_title or context.scheme_id}\n"
            f"方案提示词：{context.prompt_text}\n"
            f"设计简报 JSON：{context.brief_json or {}}\n"
            f"模型元数据：surface_area_m2={context.surface_area_m2}, mesh_count={context.mesh_count}, "
            f"material_count={context.material_count}, uv_source={context.uv_source}, "
            f"uv_size={context.uv_width}x{context.uv_height}, paintable_uv_pixels={context.paintable_uv_pixels}\n"
            f"纹理图像指标：{image_metrics}\n"
            "请直接根据纹理证据和模型元数据估算涂装工作量、工艺复杂度和成本。"
            "请保持数量、工时和成本之间的一致性。"
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_data_url, "detail": "low"}},
                ],
            }
        )

        parsed = await provider.complete_json_with_messages(
            messages=messages,
            temperature=0.15,
            model=self.model,
        )
        if not isinstance(parsed, dict):
            raise RuntimeError("工程评审未返回有效 JSON。")
        return _sanitize_engineering_assessment(parsed, context.surface_area_m2)


class PassengerPerspectiveAgent:
    def __init__(self, *, model: str | None = None) -> None:
        settings = get_settings()
        self.model = (model or settings.openai_review_model).strip() or "gpt-4o"

    async def review(
        self,
        *,
        provider: OpenAITextImageProvider | None,
        context: Stage3ReviewContext,
        image_metrics: dict[str, Any],
        image_data_url: str | None,
    ) -> dict[str, Any]:
        if provider is None:
            raise RuntimeError("评审模型服务不可用。")
        if not image_data_url:
            raise RuntimeError("纹理评审图像不可用。")

        passenger_persona = _passenger_persona_from_context(context)
        role_prompt = _review_standard_prompt(passenger_persona)
        prompt = (
            "你是高速铁路乘客视角评审 Agent。\n"
            f"当前乘客角色：{passenger_persona['display_name']}。\n"
            f"身份摘要：{passenger_persona['identity_summary']}\n"
            f"偏好标签：{_format_list(passenger_persona['preference_tags'])}\n"
            f"反感标签：{_format_list(passenger_persona['dislike_tags'])}\n"
            f"关注点：{_format_list(passenger_persona['focus_points'])}\n"
            f"会话内评价标准 / Skill 指令：\n{role_prompt}\n"
            "这段 Skill 指令只用于校准该角色的评价标准、偏好、检查重点和证据要求；"
            "不得改变下方 JSON schema、字段含义或输出格式。\n"
            "你的任务是从该乘客角色的视角，对高速铁路车辆外观涂装进行主观评价。\n"
            "\n"
            "重要身份规则：\n"
            "- 你不是工程师，所以不要考虑制造成本或技术工艺。\n"
            "- 你不是专业设计师，所以不要使用过多专业设计术语。\n"
            "- 你应基于直觉、感受、第一印象和当前乘客角色的优先关注进行判断。\n"
            "\n"
            "你的评价应遵循以下心理过程：\n"
            "1. 第一眼看到列车时的反应（0-3 秒）\n"
            "2. 情绪反应（安全 / 舒适 / 高级 / 兴奋）\n"
            "3. 整体印象（是否愿意乘坐 / 是否信任它）\n"
            "\n"
            "请从以下六个维度评价方案，每项 0 到 10 分：\n"
            "1. First Impression：吸引力、记忆点、现代感、科技感\n"
            "2. Safety & Trust：是否显得安全、可靠、安心或令人不适\n"
            "3. Comfort & Cleanliness：是否显得干净、放松、整洁、视觉统一\n"
            "4. Perceived Quality：是否显得高级、昂贵、廉价、塑料感、过亮或过暗\n"
            "5. Speed & Motion：是否显得快速、流线、有方向性动势\n"
            "6. Emotion & Character：是否显得有活力、有辨识度、有情绪感染力\n"
            "\n"
            "同时提供：\n"
            "- 2 到 4 条乘客能直接感知到的具体优点\n"
            "- 2 到 4 条乘客视角的问题\n"
            "- 使用非技术语言给出可理解的实践建议\n"
            "\n"
            "评分参考：\n"
            "- 9 到 10：优秀且令人记忆深刻\n"
            "- 7 到 8：良好，具有较广泛吸引力\n"
            "- 5 到 6：可以接受，但不突出\n"
            "- 3 到 4：明显偏弱或让人不舒服\n"
            "- 0 到 2：强烈负面印象\n"
            "\n"
            "限制：\n"
            "- 不要提及 roughness、specular、材料参数或其他技术术语\n"
            "- 不要讨论成本、施工或技术可行性\n"
            "- 使用真实乘客式的自然语言\n"
            "- 所有判断都基于它看起来如何，而不是它实际是什么\n"
            "\n"
            "输入：\n"
            "- 你可能会收到一张或多张高速铁路车辆纹理图或渲染图\n"
            "- 你也可能会收到关于颜色和风格的描述文本\n"
            "- 请基于提供的视觉证据和文字证据进行评价\n"
            "\n"
            "只返回严格 JSON，必须使用以下精确 schema：\n"
            '{'
            '"scores": {'
            '"first_impression": integer, '
            '"safety_trust": integer, '
            '"comfort_cleanliness": integer, '
            '"perceived_quality": integer, '
            '"speed_motion": integer, '
            '"emotion_character": integer'
            '}, '
            '"overall_score": number, '
            '"summary": string, '
            '"quick_comment": string, '
            '"strengths": ["string"], '
            '"issues": ["string"], '
            '"suggestions": ["string"]'
            '}\n'
            "summary 保持 1-2 个完整句子，quick_comment 保持 1 个完整句子。"
            "strengths、issues、suggestions 每类最多 3 条简洁内容。"
            "所有分数保持在 0 到 10 之间。不要在 JSON 对象之外添加 markdown 或解释。"
        )
        user_text = (
            f"产品类别：{context.product_category}\n"
            f"方案标题：{context.scheme_title or context.scheme_id}\n"
            f"方案提示词：{context.prompt_text}\n"
            f"设计简报 JSON：{context.brief_json or {}}\n"
            f"模型元数据：surface_area_m2={context.surface_area_m2}, mesh_count={context.mesh_count}, "
            f"material_count={context.material_count}, uv_source={context.uv_source}\n"
            f"纹理图像指标：{image_metrics}\n"
            "请直接根据纹理证据、方案提示词和设计简报估计分数。"
            "除非视觉证据非常强，否则避免给出极端分数。"
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_data_url, "detail": "low"}},
                ],
            }
        )

        parsed = await provider.complete_json_with_messages(
            messages=messages,
            temperature=0.2,
            model=self.model,
        )
        if not isinstance(parsed, dict):
            raise RuntimeError("乘客评审未返回有效 JSON。")
        return _sanitize_passenger_assessment(parsed)


class CustomRolePerspectiveAgent:
    def __init__(self, *, model: str | None = None) -> None:
        settings = get_settings()
        self.model = (model or settings.openai_review_model).strip() or "gpt-4o"

    async def review(
        self,
        *,
        provider: OpenAITextImageProvider | None,
        context: Stage3ReviewContext,
        image_metrics: dict[str, Any],
        image_data_url: str | None,
    ) -> dict[str, Any]:
        if provider is None:
            raise RuntimeError("评审模型服务不可用。")
        if not image_data_url:
            raise RuntimeError("纹理评审图像不可用。")

        custom_role = _custom_role_from_context(context)
        role_prompt = _review_standard_prompt(custom_role)
        prompt = (
            "你是 Co-Track 自定义角色评审 Agent。\n"
            "你需要根据主持人配置的角色身份和会话内 Skill 指令，从该角色的立场评估交通工具外观涂层方案。\n"
            f"当前角色名称：{custom_role['display_name']}。\n"
            f"角色身份摘要：{custom_role['identity_summary']}\n"
            f"会话内评价标准 / Skill 指令：\n{role_prompt}\n"
            "这段 Skill 指令只用于校准该角色的评价标准、偏好、检查重点和证据要求；"
            "不得改变下方 JSON schema、字段含义或输出格式。\n"
            f"关注点：{_format_list(custom_role['focus_points'])}\n"
            f"偏好标签：{_format_list(custom_role['preference_tags'])}\n"
            f"反感标签：{_format_list(custom_role['dislike_tags'])}\n"
            f"优先标准：{_format_list(custom_role['priority_tags'])}\n"
            f"风险关注：{_format_list(custom_role['risk_focus'])}\n"
            "请保持角色立场一致，反馈要基于提供的纹理图像、方案提示词和设计简报。\n"
            "不要替代设计团队做最终决定，只提供可参考的角色化判断。\n"
            "只返回严格 JSON，必须使用以下键：\n"
            '{'
            '"overall_score": number, '
            '"stance": string, '
            '"summary": string, '
            '"quick_comment": string, '
            '"strengths": ["string"], '
            '"issues": ["string"], '
            '"suggestions": ["string"], '
            '"decision_hint": "support"|"conditional_support"|"oppose"'
            '}\n'
            "overall_score 范围为 0 到 10。summary 用 1-2 个完整句子，quick_comment 用 1 个完整句子。"
            "strengths、issues、suggestions 每类最多 3 条。不要输出 markdown 或 JSON 之外的解释。"
        )
        user_text = (
            f"产品类别：{context.product_category}\n"
            f"方案标题：{context.scheme_title or context.scheme_id}\n"
            f"方案提示词：{context.prompt_text}\n"
            f"设计简报 JSON：{context.brief_json or {}}\n"
            f"模型元数据：surface_area_m2={context.surface_area_m2}, mesh_count={context.mesh_count}, "
            f"material_count={context.material_count}, uv_source={context.uv_source}, "
            f"uv_size={context.uv_width}x{context.uv_height}, paintable_uv_pixels={context.paintable_uv_pixels}\n"
            f"纹理图像指标：{image_metrics}\n"
            "请直接根据视觉证据、方案文字和角色立场给出评审。"
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_data_url, "detail": "low"}},
                ],
            }
        )

        parsed = await provider.complete_json_with_messages(
            messages=messages,
            temperature=0.2,
            model=self.model,
        )
        if not isinstance(parsed, dict):
            raise RuntimeError("自定义角色评审未返回有效 JSON。")
        return _sanitize_custom_assessment(parsed)


class Stage3ReviewService:
    def __init__(
        self,
        *,
        engineering_agent: EngineeringPerspectiveAgent | None = None,
        passenger_agent: PassengerPerspectiveAgent | None = None,
        custom_role_agent: CustomRolePerspectiveAgent | None = None,
    ) -> None:
        self.engineering_agent = engineering_agent or EngineeringPerspectiveAgent()
        self.passenger_agent = passenger_agent or PassengerPerspectiveAgent()
        self.custom_role_agent = custom_role_agent or CustomRolePerspectiveAgent()

    async def analyze_scheme(
        self,
        *,
        provider: OpenAITextImageProvider | None,
        context: Stage3ReviewContext,
    ) -> Stage3ReviewAssessment:
        image_data_url = _texture_reference_to_data_url(context.texture_reference)
        persona_labels = _persona_labels(context)

        if provider is None:
            return Stage3ReviewAssessment(
                status="failed",
                source="failed",
                model_name=self.engineering_agent.model,
                error_message="评审模型服务不可用。",
                settings_revision_used=context.settings_revision,
                persona_labels_used=persona_labels,
            )
        if not image_data_url:
            return Stage3ReviewAssessment(
                status="failed",
                source="failed",
                model_name=self.engineering_agent.model,
                error_message="纹理评审图像不可用。",
                settings_revision_used=context.settings_revision,
                persona_labels_used=persona_labels,
            )

        image_metrics = _extract_texture_metrics(context.texture_reference)

        try:
            engineering, passenger, role_reviews = await self._run_reviews(
                provider=provider,
                context=context,
                image_metrics=image_metrics,
                image_data_url=image_data_url,
            )
        except Exception as exc:
            return Stage3ReviewAssessment(
                status="failed",
                source="failed",
                model_name=self.engineering_agent.model,
                error_message=str(exc) or "第三阶段评审请求失败。",
                settings_revision_used=context.settings_revision,
                persona_labels_used=persona_labels,
            )

        recommendation = _compute_recommendation(engineering=engineering, passenger=passenger)
        overall_narrative = _build_overall_narrative(
            engineering=engineering,
            passenger=passenger,
            recommendation=recommendation,
        )
        return Stage3ReviewAssessment(
            status="completed",
            engineering=engineering,
            passenger=passenger,
            role_reviews=role_reviews,
            recommendation=recommendation,
            overall_narrative=overall_narrative,
            source="llm",
            model_name=self.engineering_agent.model,
            error_message=None,
            settings_revision_used=context.settings_revision,
            persona_labels_used=persona_labels,
        )

    async def _run_reviews(
        self,
        *,
        provider: OpenAITextImageProvider,
        context: Stage3ReviewContext,
        image_metrics: dict[str, Any],
        image_data_url: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        roles = _review_roles_from_context(context)
        role_reviews: list[dict[str, Any]] = []
        engineering_assessments: list[dict[str, Any]] = []
        passenger_assessments: list[dict[str, Any]] = []

        for role in roles:
            role_type = str(role.get("type") or "").strip().lower()
            role_context = _context_for_role(context, role)
            if role_type == "engineering":
                assessment = await self.engineering_agent.review(
                    provider=provider,
                    context=role_context,
                    image_metrics=image_metrics,
                    image_data_url=image_data_url,
                )
                engineering_assessments.append(assessment)
            elif role_type == "passenger":
                assessment = await self.passenger_agent.review(
                    provider=provider,
                    context=role_context,
                    image_metrics=image_metrics,
                    image_data_url=image_data_url,
                )
                passenger_assessments.append(assessment)
            else:
                assessment = await self.custom_role_agent.review(
                    provider=provider,
                    context=role_context,
                    image_metrics=image_metrics,
                    image_data_url=image_data_url,
                )

            role_reviews.append(
                {
                    "role_id": str(role.get("id") or f"{role_type}_{len(role_reviews) + 1}"),
                    "role_type": role_type if role_type in {"engineering", "passenger", "custom"} else "custom",
                    "role_name": str(role.get("display_name") or role.get("displayName") or ""),
                    "assessment": assessment,
                }
            )

        if not engineering_assessments:
            engineering_assessments.append(
                await self.engineering_agent.review(
                    provider=provider,
                    context=_context_for_role(
                        context,
                        {"id": "engineering_default", "type": "engineering", **_engineering_persona_from_context(context)},
                    ),
                    image_metrics=image_metrics,
                    image_data_url=image_data_url,
                )
            )
        if not passenger_assessments:
            passenger_assessments.append(
                await self.passenger_agent.review(
                    provider=provider,
                    context=_context_for_role(
                        context,
                        {"id": "passenger_default", "type": "passenger", **_passenger_persona_from_context(context)},
                    ),
                    image_metrics=image_metrics,
                    image_data_url=image_data_url,
                )
            )

        engineering = _aggregate_engineering_assessments(engineering_assessments)
        passenger = _aggregate_passenger_assessments(passenger_assessments)
        return engineering, passenger, role_reviews


def _review_roles_from_context(context: Stage3ReviewContext) -> list[dict[str, Any]]:
    review_personas = context.review_personas if isinstance(context.review_personas, dict) else {}
    raw_roles = review_personas.get("roles")
    roles: list[dict[str, Any]] = []
    if isinstance(raw_roles, list):
        for index, raw_role in enumerate(raw_roles):
            if not isinstance(raw_role, dict):
                continue
            role_type = str(raw_role.get("type") or raw_role.get("role_type") or raw_role.get("roleType") or "").strip().lower()
            if role_type not in {"passenger", "engineering", "custom"}:
                continue
            if raw_role.get("enabled") is False:
                continue
            roles.append(
                {
                    **raw_role,
                    "id": str(raw_role.get("id") or f"{role_type}_{index + 1}"),
                    "type": role_type,
                }
            )

    if roles:
        return roles

    return [
        {"id": "passenger_default", "type": "passenger", "enabled": True, **_passenger_persona_from_context(context)},
        {"id": "engineering_default", "type": "engineering", "enabled": True, **_engineering_persona_from_context(context)},
    ]


def _context_for_role(context: Stage3ReviewContext, role: dict[str, Any]) -> Stage3ReviewContext:
    role_type = str(role.get("type") or "").strip().lower()
    review_personas = {
        "passenger": role if role_type == "passenger" else _passenger_persona_from_context(context),
        "engineering": role if role_type == "engineering" else _engineering_persona_from_context(context),
        "custom": role if role_type == "custom" else _custom_role_from_context(context),
    }
    return Stage3ReviewContext(
        product_category=context.product_category,
        brief_json=context.brief_json,
        surface_area_m2=context.surface_area_m2,
        paintable_uv_pixels=context.paintable_uv_pixels,
        uv_width=context.uv_width,
        uv_height=context.uv_height,
        mesh_count=context.mesh_count,
        material_count=context.material_count,
        uv_source=context.uv_source,
        scheme_id=context.scheme_id,
        scheme_title=context.scheme_title,
        prompt_text=context.prompt_text,
        texture_reference=context.texture_reference,
        settings_revision=context.settings_revision,
        review_personas=review_personas,
    )


def _aggregate_engineering_assessments(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise ValueError("工程评审未返回有效角色评估。")
    if len(items) == 1:
        return dict(items[0])

    int_fields = [
        "color_zone_count",
        "masking_steps",
        "labor_hours",
        "process_steps",
        "curve_conformance_score",
        "material_cost_yuan",
        "labor_cost_yuan",
        "total_cost_yuan",
        "maintenance_cycle_years",
    ]
    float_fields = ["paint_volume_kg", "gradient_ratio_percent"]
    aggregated: dict[str, Any] = {}
    for field in float_fields:
        aggregated[field] = round(sum(float(item[field]) for item in items) / len(items), 1)
    for field in int_fields:
        aggregated[field] = int(round(sum(int(item[field]) for item in items) / len(items)))

    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    durability_order = {"A": 0, "B": 1, "C": 2}
    aggregated["color_variance_risk"] = max(
        (str(item.get("color_variance_risk") or "MEDIUM") for item in items),
        key=lambda value: risk_order.get(value, 1),
    )
    aggregated["weather_durability"] = max(
        (str(item.get("weather_durability") or "B") for item in items),
        key=lambda value: durability_order.get(value, 1),
    )
    aggregated["summary"] = _join_assessment_summaries(items, prefix="工程角色")
    aggregated["quick_comment"] = _join_quick_comments(items)
    return aggregated


def _aggregate_passenger_assessments(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise ValueError("乘客评审未返回有效角色评估。")
    if len(items) == 1:
        return dict(items[0])

    score_fields = [
        "first_impression",
        "safety_trust",
        "comfort_cleanliness",
        "perceived_quality",
        "speed_motion",
        "emotion_character",
    ]
    scores = {
        field: int(round(sum(int(item["scores"][field]) for item in items) / len(items)))
        for field in score_fields
    }
    return {
        "scores": scores,
        "overall_score": round(sum(float(item.get("overall_score") or 0.0) for item in items) / len(items), 1),
        "summary": _join_assessment_summaries(items, prefix="乘客角色"),
        "quick_comment": _join_quick_comments(items),
        "strengths": _dedupe_role_items(items, "strengths", max_items=4),
        "issues": _dedupe_role_items(items, "issues", max_items=4),
        "suggestions": _dedupe_role_items(items, "suggestions", max_items=4),
    }


def _join_assessment_summaries(items: list[dict[str, Any]], *, prefix: str) -> str:
    summaries = [str(item.get("summary") or "").strip() for item in items if str(item.get("summary") or "").strip()]
    if not summaries:
        return f"{prefix}形成了较一致的评审结果。"
    joined = " ".join(summaries)
    return _sentence_safe_trim(joined, maximum_chars=360)


def _join_quick_comments(items: list[dict[str, Any]]) -> str:
    comments = [str(item.get("quick_comment") or "").strip() for item in items if str(item.get("quick_comment") or "").strip()]
    if not comments:
        return "各角色评审基本一致，可支持综合判断。"
    return _sentence_safe_trim(" ".join(comments), maximum_chars=180)


def _dedupe_role_items(items: list[dict[str, Any]], field: str, *, max_items: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        raw_values = item.get(field)
        if not isinstance(raw_values, list):
            continue
        for raw_value in raw_values:
            text = str(raw_value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(_sentence_safe_trim(text, maximum_chars=180))
            if len(normalized) >= max_items:
                return normalized
    return normalized


def _passenger_persona_from_context(context: Stage3ReviewContext) -> dict[str, Any]:
    review_personas = context.review_personas if isinstance(context.review_personas, dict) else {}
    passenger = review_personas.get("passenger") if isinstance(review_personas.get("passenger"), dict) else {}
    return {
        "display_name": _text_or_fallback(passenger.get("display_name"), "普通乘客"),
        "identity_summary": _text_or_fallback(
            passenger.get("identity_summary"),
            "从第一印象、舒适度、信任感和情绪反应判断方案的普通乘客。",
        ),
        "preference_tags": _list_or_fallback(
            passenger.get("preference_tags"),
            ["干净", "可靠", "现代", "舒适"],
        ),
        "dislike_tags": _list_or_fallback(
            passenger.get("dislike_tags"),
            ["图形杂乱", "对比刺眼", "质感廉价"],
        ),
        "focus_points": _list_or_fallback(
            passenger.get("focus_points"),
            ["第一印象", "安全信任", "舒适整洁", "品质感"],
        ),
        "role_prompt": _text_or_fallback(passenger.get("role_prompt") or passenger.get("rolePrompt"), ""),
    }


def _engineering_persona_from_context(context: Stage3ReviewContext) -> dict[str, Any]:
    review_personas = context.review_personas if isinstance(context.review_personas, dict) else {}
    engineering = review_personas.get("engineering") if isinstance(review_personas.get("engineering"), dict) else {}
    return {
        "display_name": _text_or_fallback(engineering.get("display_name"), "涂装工艺工程师"),
        "identity_summary": _text_or_fallback(
            engineering.get("identity_summary"),
            "从工艺稳定性、耐久性和全生命周期成本平衡方案的涂装制造评审角色。",
        ),
        "priority_tags": _list_or_fallback(
            engineering.get("priority_tags"),
            ["工艺稳定", "涂层耐久", "色区可控", "易维护"],
        ),
        "risk_focus": _list_or_fallback(
            engineering.get("risk_focus"),
            ["色差风险", "渐变复杂度", "遮蔽工作量", "维护周期"],
        ),
        "focus_points": _list_or_fallback(
            engineering.get("focus_points"),
            ["油漆用量", "工艺步骤", "成本", "耐久性", "曲面贴合"],
        ),
        "role_prompt": _text_or_fallback(engineering.get("role_prompt") or engineering.get("rolePrompt"), ""),
    }


def _custom_role_from_context(context: Stage3ReviewContext) -> dict[str, Any]:
    review_personas = context.review_personas if isinstance(context.review_personas, dict) else {}
    custom = review_personas.get("custom") if isinstance(review_personas.get("custom"), dict) else {}
    return {
        "display_name": _text_or_fallback(custom.get("display_name") or custom.get("displayName"), "自定义评审角色"),
        "identity_summary": _text_or_fallback(
            custom.get("identity_summary") or custom.get("identitySummary"),
            "根据自定义身份、关注点和项目目标对方案提供参考性评审。",
        ),
        "role_prompt": _text_or_fallback(custom.get("role_prompt") or custom.get("rolePrompt"), ""),
        "focus_points": _list_or_fallback(
            custom.get("focus_points") or custom.get("focusPoints"),
            ["角色关注点", "方案匹配度", "风险与建议"],
        ),
        "preference_tags": _list_or_fallback(custom.get("preference_tags") or custom.get("preferenceTags"), []),
        "dislike_tags": _list_or_fallback(custom.get("dislike_tags") or custom.get("dislikeTags"), []),
        "priority_tags": _list_or_fallback(custom.get("priority_tags") or custom.get("priorityTags"), []),
        "risk_focus": _list_or_fallback(custom.get("risk_focus") or custom.get("riskFocus"), []),
    }


def _review_standard_prompt(role: dict[str, Any]) -> str:
    explicit_prompt = _text_or_fallback(role.get("role_prompt") or role.get("rolePrompt"), "")
    if explicit_prompt:
        return explicit_prompt
    display_name = _text_or_fallback(role.get("display_name") or role.get("displayName"), "自定义评审角色")
    identity_summary = _text_or_fallback(role.get("identity_summary") or role.get("identitySummary"), "根据该角色立场评估方案。")
    parts = [
        f"你将扮演“{display_name}”。",
        f"角色身份与特征：{identity_summary}",
    ]
    focus_points = _list_or_fallback(role.get("focus_points") or role.get("focusPoints"), [])
    preference_tags = _list_or_fallback(role.get("preference_tags") or role.get("preferenceTags"), [])
    dislike_tags = _list_or_fallback(role.get("dislike_tags") or role.get("dislikeTags"), [])
    priority_tags = _list_or_fallback(role.get("priority_tags") or role.get("priorityTags"), [])
    risk_focus = _list_or_fallback(role.get("risk_focus") or role.get("riskFocus"), [])
    if focus_points:
        parts.append(f"重点关注：{'、'.join(focus_points)}。")
    if preference_tags:
        parts.append(f"偏好倾向：{'、'.join(preference_tags)}。")
    if dislike_tags:
        parts.append(f"反感或警惕：{'、'.join(dislike_tags)}。")
    if priority_tags:
        parts.append(f"优先判断标准：{'、'.join(priority_tags)}。")
    if risk_focus:
        parts.append(f"风险关注：{'、'.join(risk_focus)}。")
    parts.append("判断时优先依据该团队或角色的标准、偏好、限制、风险关注和证据要求。")
    parts.append("请从该角色的真实立场出发，围绕方案是否符合其利益、期待、限制和决策习惯给出具体反馈。")
    return "\n".join(parts)


def _custom_role_prompt(role: dict[str, Any]) -> str:
    return _review_standard_prompt(role)


def _persona_labels(context: Stage3ReviewContext) -> dict[str, str]:
    roles = _review_roles_from_context(context)
    passenger = next((role for role in roles if role.get("type") == "passenger"), _passenger_persona_from_context(context))
    engineering = next((role for role in roles if role.get("type") == "engineering"), _engineering_persona_from_context(context))
    return {
        "passenger": str(passenger.get("display_name") or "普通乘客"),
        "engineering": str(engineering.get("display_name") or "涂装工艺工程师"),
    }


def _text_or_fallback(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.strip().split())
    return normalized or fallback


def _list_or_fallback(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = " ".join(item.strip().split())
        if not text:
            continue
        normalized.append(text)
    return normalized or list(fallback)


def _format_list(value: list[str]) -> str:
    return "、".join(item for item in value if item.strip()) or "未指定"


def _extract_texture_metrics(texture_reference: str | None) -> dict[str, Any]:
    width = 1024
    height = 1024
    if not texture_reference:
        return {
            "width": width,
            "height": height,
            "opaque_ratio_percent": 100.0,
            "dominant_colors": ["#cbd5e1", "#94a3b8"],
            "dominant_color_shares": [64.0, 36.0],
            "estimated_color_zones": 2,
            "gradient_ratio_percent": 12.0,
            "contrast_score": 48,
            "saturation_score": 36,
            "vibrant_ratio_percent": 10.0,
            "dark_ratio_percent": 12.0,
            "bright_ratio_percent": 26.0,
            "edge_complexity_score": 38,
        }

    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {
            "width": width,
            "height": height,
            "opaque_ratio_percent": 100.0,
            "dominant_colors": ["#cbd5e1", "#94a3b8"],
            "dominant_color_shares": [64.0, 36.0],
            "estimated_color_zones": 2,
            "gradient_ratio_percent": 12.0,
            "contrast_score": 48,
            "saturation_score": 36,
            "vibrant_ratio_percent": 10.0,
            "dark_ratio_percent": 12.0,
            "bright_ratio_percent": 26.0,
            "edge_complexity_score": 38,
        }

    local_path = _resolve_local_texture_path(texture_reference)
    if local_path is None or not local_path.is_file():
        return {
            "width": width,
            "height": height,
            "opaque_ratio_percent": 100.0,
            "dominant_colors": ["#cbd5e1", "#94a3b8"],
            "dominant_color_shares": [64.0, 36.0],
            "estimated_color_zones": 2,
            "gradient_ratio_percent": 12.0,
            "contrast_score": 48,
            "saturation_score": 36,
            "vibrant_ratio_percent": 10.0,
            "dark_ratio_percent": 12.0,
            "bright_ratio_percent": 26.0,
            "edge_complexity_score": 38,
        }

    with Image.open(local_path) as raw_image:
        rgba_image = raw_image.convert("RGBA")
        width, height = rgba_image.size
        sample = rgba_image.resize((min(256, width), min(256, height)))
        sample_array = np.asarray(sample, dtype=np.float32)

    alpha = sample_array[:, :, 3] / 255.0
    opaque_mask = alpha > 0.05
    rgb = sample_array[:, :, :3] / 255.0
    if not opaque_mask.any():
        opaque_mask = np.ones(alpha.shape, dtype=bool)

    pixels = rgb[opaque_mask]
    maxc = pixels.max(axis=1)
    minc = pixels.min(axis=1)
    value = maxc
    saturation = np.where(maxc <= 1e-6, 0.0, (maxc - minc) / np.maximum(maxc, 1e-6))
    luma = pixels[:, 0] * 0.2126 + pixels[:, 1] * 0.7152 + pixels[:, 2] * 0.0722

    opaque_ratio_percent = round(float(opaque_mask.mean() * 100.0), 1)
    saturation_score = int(round(float(np.clip(saturation.mean() * 100.0, 0.0, 100.0))))
    contrast_score = int(round(float(np.clip(luma.std() * 320.0, 0.0, 100.0))))
    vibrant_ratio_percent = round(float(((saturation > 0.55) & (value > 0.22) & (value < 0.92)).mean() * 100.0), 1)
    dark_ratio_percent = round(float((luma < 0.25).mean() * 100.0), 1)
    bright_ratio_percent = round(float((luma > 0.78).mean() * 100.0), 1)

    diff_candidates: list[np.ndarray] = []
    if sample_array.shape[1] > 1:
        right_mask = opaque_mask[:, 1:] & opaque_mask[:, :-1]
        right_diff = np.linalg.norm(sample_array[:, 1:, :3] - sample_array[:, :-1, :3], axis=2)
        diff_candidates.append(right_diff[right_mask])
    if sample_array.shape[0] > 1:
        down_mask = opaque_mask[1:, :] & opaque_mask[:-1, :]
        down_diff = np.linalg.norm(sample_array[1:, :, :3] - sample_array[:-1, :, :3], axis=2)
        diff_candidates.append(down_diff[down_mask])

    if diff_candidates:
        diffs = np.concatenate([item for item in diff_candidates if item.size > 0], axis=0)
    else:
        diffs = np.asarray([], dtype=np.float32)

    if diffs.size == 0:
        gradient_ratio_percent = 0.0
        edge_complexity_score = 0
    else:
        smooth_gradient_ratio = ((diffs >= 6.0) & (diffs <= 52.0)).mean()
        sharp_edge_ratio = (diffs > 58.0).mean()
        gradient_ratio_percent = round(float(np.clip(smooth_gradient_ratio * 100.0, 0.0, 100.0)), 1)
        edge_complexity_score = int(round(float(np.clip(sharp_edge_ratio * 180.0, 0.0, 100.0))))

    quantized = sample.convert("RGB").quantize(colors=6)
    palette = quantized.getpalette() or []
    color_counts = quantized.getcolors(maxcolors=256) or []
    total_count = sum(count for count, _ in color_counts) or 1
    dominant_colors: list[str] = []
    dominant_shares: list[float] = []
    for count, palette_index in sorted(color_counts, reverse=True)[:5]:
        offset = palette_index * 3
        if offset + 2 >= len(palette):
            continue
        rgb_triplet = palette[offset : offset + 3]
        dominant_colors.append(f"#{rgb_triplet[0]:02x}{rgb_triplet[1]:02x}{rgb_triplet[2]:02x}")
        dominant_shares.append(round(count / total_count * 100.0, 1))

    estimated_color_zones = max(1, min(8, sum(1 for share in dominant_shares if share >= 7.5)))
    if vibrant_ratio_percent >= 18.0 and estimated_color_zones < 6:
        estimated_color_zones += 1

    return {
        "width": width,
        "height": height,
        "opaque_ratio_percent": opaque_ratio_percent,
        "dominant_colors": dominant_colors or ["#cbd5e1"],
        "dominant_color_shares": dominant_shares or [100.0],
        "estimated_color_zones": estimated_color_zones,
        "gradient_ratio_percent": gradient_ratio_percent,
        "contrast_score": contrast_score,
        "saturation_score": saturation_score,
        "vibrant_ratio_percent": vibrant_ratio_percent,
        "dark_ratio_percent": dark_ratio_percent,
        "bright_ratio_percent": bright_ratio_percent,
        "edge_complexity_score": edge_complexity_score,
    }


def _sanitize_engineering_assessment(
    raw_value: Any,
    surface_area_m2: float,
) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        raise ValueError("Engineering review payload is not a JSON object.")

    payload = raw_value
    max_paint_volume = max(80.0, surface_area_m2 * 4.5)
    paint_volume_kg = _require_float(payload.get("paint_volume_kg"), "paint_volume_kg", 1.0, max_paint_volume)
    color_zone_count = _require_int(payload.get("color_zone_count"), "color_zone_count", 1, 8)
    masking_steps = _require_int(payload.get("masking_steps"), "masking_steps", 1, 10)
    gradient_ratio_percent = _require_float(
        payload.get("gradient_ratio_percent"),
        "gradient_ratio_percent",
        0.0,
        100.0,
    )
    labor_hours = _require_int(payload.get("labor_hours"), "labor_hours", 20, 2400)
    process_steps = _require_int(payload.get("process_steps"), "process_steps", 3, 12)
    curve_conformance_score = _require_int(
        payload.get("curve_conformance_score"),
        "curve_conformance_score",
        0,
        100,
    )
    material_cost_yuan = _require_int(payload.get("material_cost_yuan"), "material_cost_yuan", 1000, 5_000_000)
    labor_cost_yuan = _require_int(payload.get("labor_cost_yuan"), "labor_cost_yuan", 1000, 5_000_000)
    parsed_total_cost_yuan = _require_int(payload.get("total_cost_yuan"), "total_cost_yuan", 2000, 10_000_000)
    total_cost_yuan = max(material_cost_yuan + labor_cost_yuan, parsed_total_cost_yuan)
    color_variance_risk = _require_choice(payload.get("color_variance_risk"), "color_variance_risk", {"LOW", "MEDIUM", "HIGH"})
    weather_durability = _require_choice(payload.get("weather_durability"), "weather_durability", {"A", "B", "C"})
    maintenance_cycle_years = _require_int(
        payload.get("maintenance_cycle_years"),
        "maintenance_cycle_years",
        2,
        12,
    )
    summary = _require_short_text(payload.get("summary"), "summary", minimum_chars=12, maximum_chars=360)
    quick_comment = _require_short_text(
        payload.get("quick_comment"),
        "quick_comment",
        minimum_chars=12,
        maximum_chars=180,
    )

    return {
        "paint_volume_kg": round(paint_volume_kg, 1),
        "color_zone_count": color_zone_count,
        "masking_steps": masking_steps,
        "gradient_ratio_percent": round(gradient_ratio_percent, 1),
        "labor_hours": labor_hours,
        "process_steps": process_steps,
        "curve_conformance_score": curve_conformance_score,
        "material_cost_yuan": material_cost_yuan,
        "labor_cost_yuan": labor_cost_yuan,
        "total_cost_yuan": total_cost_yuan,
        "color_variance_risk": color_variance_risk,
        "weather_durability": weather_durability,
        "maintenance_cycle_years": maintenance_cycle_years,
        "summary": summary,
        "quick_comment": quick_comment,
    }


def _sanitize_passenger_assessment(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        raise ValueError("Passenger review payload is not a JSON object.")

    payload = raw_value
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("Missing or invalid field: scores.")

    return {
        "scores": {
            "first_impression": _require_int(scores.get("first_impression"), "scores.first_impression", 0, 10),
            "safety_trust": _require_int(scores.get("safety_trust"), "scores.safety_trust", 0, 10),
            "comfort_cleanliness": _require_int(
                scores.get("comfort_cleanliness"),
                "scores.comfort_cleanliness",
                0,
                10,
            ),
            "perceived_quality": _require_int(scores.get("perceived_quality"), "scores.perceived_quality", 0, 10),
            "speed_motion": _require_int(scores.get("speed_motion"), "scores.speed_motion", 0, 10),
            "emotion_character": _require_int(scores.get("emotion_character"), "scores.emotion_character", 0, 10),
        },
        "overall_score": round(
            _require_float(payload.get("overall_score"), "overall_score", 0.0, 10.0),
            1,
        ),
        "summary": _require_short_text(payload.get("summary"), "summary", minimum_chars=12, maximum_chars=360),
        "quick_comment": _require_short_text(
            payload.get("quick_comment"),
            "quick_comment",
            minimum_chars=12,
            maximum_chars=180,
        ),
        "strengths": _require_short_text_list(payload.get("strengths"), "strengths", min_items=2, max_items=3),
        "issues": _require_short_text_list(payload.get("issues"), "issues", min_items=2, max_items=3),
        "suggestions": _require_short_text_list(payload.get("suggestions"), "suggestions", min_items=2, max_items=3),
    }


def _sanitize_custom_assessment(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        raise ValueError("Custom role review payload is not a JSON object.")

    decision_hint = _require_choice(
        raw_value.get("decision_hint"),
        "decision_hint",
        {"SUPPORT", "CONDITIONAL_SUPPORT", "OPPOSE"},
    ).lower()
    return {
        "overall_score": round(_require_float(raw_value.get("overall_score"), "overall_score", 0.0, 10.0), 1),
        "stance": _require_short_text(raw_value.get("stance"), "stance", minimum_chars=4, maximum_chars=160),
        "summary": _require_short_text(raw_value.get("summary"), "summary", minimum_chars=12, maximum_chars=360),
        "quick_comment": _require_short_text(
            raw_value.get("quick_comment"),
            "quick_comment",
            minimum_chars=8,
            maximum_chars=180,
        ),
        "strengths": _require_short_text_list(raw_value.get("strengths"), "strengths", min_items=1, max_items=3),
        "issues": _require_short_text_list(raw_value.get("issues"), "issues", min_items=1, max_items=3),
        "suggestions": _require_short_text_list(raw_value.get("suggestions"), "suggestions", min_items=1, max_items=3),
        "decision_hint": decision_hint,
    }


def _compute_recommendation(*, engineering: dict[str, Any], passenger: dict[str, Any]) -> str:
    passenger_scores = passenger.get("scores")
    if not isinstance(passenger_scores, dict):
        raise ValueError("Passenger assessment is missing scores.")

    passenger_values = [
        int(passenger_scores["first_impression"]),
        int(passenger_scores["safety_trust"]),
        int(passenger_scores["comfort_cleanliness"]),
        int(passenger_scores["perceived_quality"]),
        int(passenger_scores["speed_motion"]),
        int(passenger_scores["emotion_character"]),
    ]
    passenger_average = sum(passenger_values) / max(1, len(passenger_values))
    overall_score = float(passenger.get("overall_score") or 0.0)
    all_passenger_above_7 = all(value >= 7 for value in passenger_values)
    engineering_looks_safe = (
        int(engineering["color_zone_count"]) <= 4
        and float(engineering["gradient_ratio_percent"]) <= 25.0
        and int(engineering["curve_conformance_score"]) >= 65
    )

    if engineering["color_variance_risk"] == "HIGH" and int(engineering["total_cost_yuan"]) > 120_000:
        return "not_recommended"
    if engineering_looks_safe and all_passenger_above_7 and passenger_average >= 8.0 and overall_score >= 8.0:
        return "highly_recommended"
    if passenger_average >= 6.8 and overall_score >= 6.8 and engineering["color_variance_risk"] != "HIGH":
        return "recommended"
    if passenger_average < 4.5 or overall_score < 4.5:
        return "not_recommended"
    return "acceptable"


def _build_overall_narrative(
    *,
    engineering: dict[str, Any],
    passenger: dict[str, Any],
    recommendation: str,
) -> str:
    recommendation_opening = {
        "highly_recommended": "该方向已经具备较强推进价值，可以作为重点方案继续深化。",
        "recommended": "该方向整体较稳妥，经过少量针对性调整后可以继续推进。",
        "acceptable": "该方向具备一定可行性，但仍需要更清晰的一轮优化才能形成说服力。",
        "not_recommended": "该方向以当前状态来看不适合作为后续主推方案。",
    }.get(recommendation, "该方向仍需要更充分的综合判断。")

    passenger_summary = str(passenger.get("summary") or "").strip()
    engineering_summary = str(engineering.get("summary") or "").strip()
    passenger_comment = str(passenger.get("quick_comment") or "").strip()
    engineering_comment = str(engineering.get("quick_comment") or "").strip()

    parts = [recommendation_opening]
    if passenger_summary:
        parts.append(f"从乘客视角看，{passenger_summary}")
    elif passenger_comment:
        parts.append(passenger_comment)
    if engineering_summary:
        parts.append(f"从工程视角看，{engineering_summary}")
    elif engineering_comment:
        parts.append(engineering_comment)

    normalized = " ".join(part.strip() for part in parts if part.strip())
    return _sentence_safe_trim(normalized, maximum_chars=900)


def _texture_reference_to_data_url(texture_reference: str | None) -> str | None:
    local_path = _resolve_local_texture_path(texture_reference)
    if local_path is None or not local_path.is_file():
        return None

    try:
        from PIL import Image, ImageOps
    except ImportError:
        suffix = local_path.suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    with Image.open(local_path) as raw_image:
        image = ImageOps.exif_transpose(raw_image).convert("RGBA")
        target_longest_edge = 512
        longest_edge = max(image.size)
        if longest_edge > target_longest_edge:
            scale = target_longest_edge / float(longest_edge)
            resized_size = (
                max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))),
            )
            image = image.resize(resized_size, Image.Resampling.LANCZOS)

        output = BytesIO()
        rgb_background = Image.new("RGB", image.size, (255, 255, 255))
        rgb_background.paste(image, mask=image.getchannel("A"))
        rgb_background.save(
            output,
            format="JPEG",
            quality=72,
            optimize=True,
            progressive=True,
        )
        mime_type = "image/jpeg"

    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _resolve_local_texture_path(texture_reference: str | None) -> Path | None:
    reference = (texture_reference or "").strip()
    if not reference:
        return None

    direct_path = Path(reference)
    if direct_path.is_file():
        return direct_path

    if reference.startswith("/files/textures/"):
        candidate = (TEXTURE_MAP_DIR / Path(reference).name).resolve()
        try:
            candidate.relative_to(TEXTURE_MAP_DIR.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    return None


def _require_float(value: Any, field_name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Missing or invalid field: {field_name}.") from None
    return _clamp(parsed, minimum, maximum)


def _require_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError(f"Missing or invalid field: {field_name}.") from None
    return int(_clamp(parsed, minimum, maximum))


def _require_choice(value: Any, field_name: str, options: set[str]) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in options:
            return normalized
    raise ValueError(f"Missing or invalid field: {field_name}.")


def _require_short_text(
    value: Any,
    field_name: str,
    *,
    minimum_chars: int,
    maximum_chars: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Missing or invalid field: {field_name}.")

    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum_chars:
        raise ValueError(f"Missing or invalid field: {field_name}.")
    if len(normalized) > maximum_chars:
        normalized = _sentence_safe_trim(normalized, maximum_chars=maximum_chars)
    return normalized


def _sentence_safe_trim(value: str, *, maximum_chars: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) <= maximum_chars:
        return normalized
    candidate = normalized[:maximum_chars].rstrip()
    sentence_breaks = [candidate.rfind(mark) for mark in (".", "!", "?", "。", "！", "？", ";", "；")]
    sentence_end = max(sentence_breaks)
    if sentence_end >= max(40, int(maximum_chars * 0.55)):
        return candidate[: sentence_end + 1].rstrip()
    word_break = candidate.rfind(" ")
    if word_break >= max(24, int(maximum_chars * 0.7)):
        return f"{candidate[:word_break].rstrip()}..."
    return f"{candidate.rstrip()}..."


def _require_short_text_list(value: Any, field_name: str, *, min_items: int, max_items: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Missing or invalid field: {field_name}.")

    normalized_items: list[str] = []
    for item in value:
        normalized_items.append(
            _require_short_text(
                item,
                field_name,
                minimum_chars=6,
                maximum_chars=180,
            )
        )

    if len(normalized_items) < min_items:
        raise ValueError(f"Missing or invalid field: {field_name}.")
    return normalized_items[:max_items]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
