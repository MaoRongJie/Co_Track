from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.texture_planning import TEXTURE_SCHEME_IDS, extract_brief_keywords


class AgentRuntimeDependencyError(RuntimeError):
    pass


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
            prompt_text = (
                f"{title}. Build a manufacturable model texture direction with clear theme, "
                "color rhythm, and graphic logic."
            )
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
    theme = _safe_text(brief_keywords.get("theme"), default="工业外观")
    colors = ", ".join(_safe_list(brief_keywords.get("main_colors"), max_items=4))
    styles = ", ".join(_safe_list(brief_keywords.get("style_keywords"), max_items=4))
    elements = ", ".join(_safe_list(brief_keywords.get("design_elements"), max_items=4))
    image_keywords = ", ".join(context.selected_image_keywords[:6])

    prompt_bases = [
        f"围绕 {theme} 建立清晰主方向，强调大尺度识别度和制造可行性。",
        f"围绕 {theme} 建立更具动势的方向，强调节奏变化、速度感和层次过渡。",
        f"围绕 {theme} 建立更具风格化的方向，强调材质氛围、纹理细节和记忆点。",
    ]

    schemes: list[TextureSchemePlan] = []
    for index, prompt_base in enumerate(prompt_bases, start=1):
        prompt_text = (
            f"{prompt_base} 主色参考：{colors or '根据设计简报推导'}。"
            f"风格关键词：{styles or '现代工业'}。"
            f"设计元素：{elements or '保持构图克制'}。"
            f"图像风格强化：{image_keywords or '无'}。"
            "确保纹理方向在大型 3D 模型表面上清晰可读，并具备制造可行性。"
        )
        schemes.append(
            TextureSchemePlan(
                id=f"scheme_{index}",
                title=f"方案 {index}",
                strategy=f"差异化方向 {index}",
                prompt_text=prompt_text,
                key_points=[
                    theme,
                    colors or "清晰主色结构",
                    styles or "现代工业",
                    image_keywords or "未选择图像关键词",
                ],
            )
        )
    return schemes


class CreativeDialogueAndImageAgent:
    async def plan_texture_schemes(
        self,
        *,
        provider: OpenAITextImageProvider,
        context: TexturePlanningContext,
    ) -> TexturePlanResult:
        brief_keywords = extract_brief_keywords(context.brief_json)
        payload = _build_texture_context_summary(context)
        system_prompt = (
            "你是 Co-Track 模型纹理规划 Agent，专注于高速列车、动车组和轨道交通车辆外观的工业设计。\n"
            "你的任务是综合关键词、用户意图、文档内容、图像风格线索和基准模型特征，为高速列车 3D 模型生成三套差异化纹理提示词方案。每个 `prompt_text` 会直接写入 Meshy Retexture API 的 `text_style_prompt` 字段。\n"
            "\n"
            "严格技术约束，请优先遵守：\n"
            "1. 每个 `prompt_text` 不得超过 600 个字符，这是 API 的硬性限制。\n"
            "2. 不要在提示词中使用数字化 PBR 参数。\n"
            "3. 不要使用工程单位、汽车底漆层、清漆层、聚氨酯化学组成等工业或材料科学术语，因为 Meshy 难以稳定解析。\n"
            "4. 高速列车标准外观应主要理解为工业级半光泽或丝缎质感。整体应清晰、平整、致密、均匀，并带有轻微柔和反射。不要生成镜面反射、拉丝金属、强珠光闪烁、电镀效果或改装车质感。\n"
            "5. 材质描述应服务于高速列车整体外观，不要压过涂装结构和图形组织。\n"
            "6. 默认色彩倾向：除非用户文本、上传文档或选中图像关键词明确要求深色外观方向，例如黑色、炭灰、石墨、深海军蓝或其他以深色车身为主的方案，否则避免生成深色主导的列车外观。默认优先使用浅色或中浅色车身色盘。\n"
            "7. 默认饱和度倾向：除非用户输入明确要求大胆、高鲜艳度或节庆感色彩，否则避免过度饱和的车身颜色。优先使用可控、适中、精致、稳定并适合高速列车外观的饱和度。\n"
            "\n"
            "领域知识：高速列车外观设计\n"
            "高速列车涂装设计遵循严格工业标准，方案需要从以下维度推理：\n"
            "涂装结构：全包覆、腰线条带、渐变融合、车头重点装饰。\n"
            "图形语言：硬边几何线条、有机速度曲线、文化来源图案。\n"
            "品牌锚点：标识放置区域、主色线位置、辅助强调带。\n"
            "\n"
            "材质表达：只使用视觉语言\n"
            "请把材质质感转译为 Meshy 能理解、且符合高速列车标准涂装的视觉描述。\n"
            "推荐短语：\n"
            "smooth semi-gloss surface\n"
            "silky satin sheen\n"
            "clean controlled reflections\n"
            "crisp even finish\n"
            "refined soft reflection\n"
            "ultra-smooth body panels\n"
            "tight uniform surface\n"
            "glass-like clarity without mirror shine\n"
            "subtle fine paint texture\n"
            "faint tactile granularity\n"
            "even sprayed finish\n"
            "factory-new, zero wear, pristine surface\n"
            "light service patina, faint dust on undercarriage panels\n"
            "slight UV fade on roof surfaces, sun-softened top panels\n"
            "\n"
            "禁止或严格避免：\n"
            "mirror-polished\n"
            "reflective gloss finish\n"
            "chrome-like\n"
            "brushed metal\n"
            "metallic flake\n"
            "iridescent shimmer\n"
            "sparkling finish\n"
            "anodized\n"
            "electroplated\n"
            "carbon fiber look\n"
            "\n"
            "表面图形必须被明确描述：\n"
            "必须清楚说明方案是否包含明确的表面图形元素，不能只描述颜色或材质。\n"
            "如果某个方案没有具体图案要求，就不要强行提及具体图形元素。\n"
            "如果包含图形元素，必须包含以下一种或多种描述：\n"
            "条带：说明宽度、角度、收束点、在车身上的起止位置。\n"
            "涂装腰线：说明位于车身上部、中部还是下部三分之一，边缘是硬切还是柔和渐变。\n"
            "车头图形：V 形箭头、后掠翼形、放射线、居中标识装饰区域。\n"
            "车窗包围：框线颜色、阴影边线。\n"
            "面板接缝：齐平或内凹、边缘强调、同色或对比色接缝。\n"
            "重复图案：说明图案间距相对于车厢长度的比例，以及跨车厢对齐方式。\n"
            "\n"
            "方案差异化要求：\n"
            "你必须自主判断最有价值的三个差异化方向。不要使用“科技感、自然感、商务感”这类泛化预设类别。\n"
            "三套方案至少需要在以下三个维度上存在实质差异：\n"
            "涂装结构类型\n"
            "图形语言与节奏\n"
            "材质表面质感\n"
            "色温与色彩比例\n"
            "使用痕迹或涂层状态\n"
            "文化叙事或品牌语义\n"
            "\n"
            "提示词自检清单：\n"
            "不超过 600 个字符。\n"
            "包含涂装结构描述。\n"
            "包含至少一个明确图形元素。\n"
            "包含符合高速列车标准的视觉材质表达。\n"
            "包含状态描述，例如全新、轻微使用痕迹或车顶轻微 UV 褪色。\n"
            "不包含镜面反射、拉丝金属、强珠光或电镀描述。\n"
            "不只使用模糊氛围词；任何“速度感、秩序感、力量感”都必须由具体视觉结构支撑。\n"
            "三个 prompt 必须能独立执行，彼此之间不能相互引用。\n"
            "\n"
            "输出格式：\n"
            "只返回严格 JSON。不要使用 Markdown，也不要追加解释性文字。\n"
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
                    "必须按固定顺序返回 exactly 3 schemes",
                    "ids 必须是 scheme_1, scheme_2, scheme_3",
                    "不要使用 markdown",
                    "title 和 strategy 应简短",
                    "prompt_text 应具体且便于编辑",
                    "key_points 应简洁且避免重复",
                    "三套方案必须明显不同，不能只是轻微改写",
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
                f"{user_prompt}\n\n附加要求："
                "上一轮方案过于相似。请重新生成，并显著拉开三套方案在概念、视觉语言、构图节奏和提示词措辞上的差异。"
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


AgentRuntime = CreativeDialogueAndImageAgent
