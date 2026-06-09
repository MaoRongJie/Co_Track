from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TEXTURE_SCHEME_IDS = ("scheme_1", "scheme_2", "scheme_3")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_brief_keywords(brief_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(brief_json, dict):
        return {
            "theme": "",
            "main_colors": [],
            "accent_colors": [],
            "style_keywords": [],
            "design_elements": [],
            "constraints_hint": "",
        }

    def _safe_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""

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
        if isinstance(value, dict):
            return value
        return {}

    def _join_parts(parts: list[str]) -> str:
        normalized = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(normalized)

    why = _safe_dict(brief_json.get("why"))
    what = _safe_dict(brief_json.get("what"))
    how = _safe_dict(brief_json.get("how"))

    theme = _safe_text(brief_json.get("theme")) or _safe_text(why.get("coreExperienceIntent"))
    main_colors = _safe_list(brief_json.get("mainColors"), max_items=6)
    if not main_colors:
        color_tendency = _safe_text(what.get("colorTendency"))
        if color_tendency:
            main_colors = [color_tendency]

    style_keywords = _safe_list(brief_json.get("styleKeywords"), max_items=8)
    if not style_keywords:
        style_keywords = _safe_list(what.get("visualStyleKeywords"), max_items=8)

    design_elements = _safe_list(brief_json.get("designElements"), max_items=8)
    if not design_elements:
        design_elements = _safe_list(what.get("referenceImagery"), max_items=8)

    constraints_hint = _safe_text(brief_json.get("constraintsHint"))
    if not constraints_hint:
        constraints_hint = _join_parts(
            [
                f"Craft/tech: {'; '.join(_safe_list(how.get('craftTechConstraints'), max_items=2))}"
                if _safe_list(how.get("craftTechConstraints"), max_items=2)
                else "",
                f"Regulatory: {'; '.join(_safe_list(how.get('regulatoryConstraints'), max_items=2))}"
                if _safe_list(how.get("regulatoryConstraints"), max_items=2)
                else "",
                f"Locked: {'; '.join(_safe_list(brief_json.get('lockedItems'), max_items=2))}"
                if _safe_list(brief_json.get("lockedItems"), max_items=2)
                else "",
            ]
        )

    return {
        "theme": theme,
        "main_colors": main_colors,
        "accent_colors": _safe_list(brief_json.get("accentColors"), max_items=6),
        "style_keywords": style_keywords,
        "design_elements": design_elements,
        "constraints_hint": constraints_hint,
    }


def build_document_excerpt(text: str, *, max_chars: int = 600) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def build_empty_texture_plan(brief_json: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "source_text": "",
        "document_name": None,
        "document_excerpt": "",
        "image_name": None,
        "image_content_keywords": [],
        "image_style_keywords": [],
        "selected_image_keywords": [],
        "brief_keywords": extract_brief_keywords(brief_json),
        "schemes": [
            {
                "id": scheme_id,
                "title": f"Scheme {index}",
                "strategy": "",
                "prompt_text": "",
                "key_points": [],
            }
            for index, scheme_id in enumerate(TEXTURE_SCHEME_IDS, start=1)
        ],
        "selected_scheme_id": TEXTURE_SCHEME_IDS[0],
        "texture_generation_status": "idle",
        "textured_models": [],
        "textured_models_updated_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }


def normalize_texture_plan_state(
    raw_state: dict[str, Any] | None,
    *,
    brief_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = build_empty_texture_plan(brief_json)
    if not isinstance(raw_state, dict):
        return normalized

    normalized["source_text"] = _safe_text(raw_state.get("source_text"))
    normalized["document_name"] = _safe_optional_text(raw_state.get("document_name"))
    normalized["document_excerpt"] = _safe_text(raw_state.get("document_excerpt"))
    normalized["image_name"] = _safe_optional_text(raw_state.get("image_name"))
    normalized["image_content_keywords"] = _safe_list(raw_state.get("image_content_keywords"), max_items=12)
    normalized["image_style_keywords"] = _safe_list(raw_state.get("image_style_keywords"), max_items=12)
    normalized["selected_image_keywords"] = _safe_list(raw_state.get("selected_image_keywords"), max_items=16)
    normalized["brief_keywords"] = extract_brief_keywords(brief_json)

    raw_schemes = raw_state.get("schemes")
    normalized["schemes"] = _normalize_schemes(raw_schemes)

    selected_scheme_id = _safe_text(raw_state.get("selected_scheme_id"))
    normalized["selected_scheme_id"] = (
        selected_scheme_id if selected_scheme_id in TEXTURE_SCHEME_IDS else TEXTURE_SCHEME_IDS[0]
    )
    texture_generation_status = _safe_text(raw_state.get("texture_generation_status"))
    normalized["texture_generation_status"] = texture_generation_status or "idle"
    normalized["textured_models"] = _normalize_textured_models(raw_state.get("textured_models"))
    textured_models_updated_at = _safe_text(raw_state.get("textured_models_updated_at"))
    normalized["textured_models_updated_at"] = textured_models_updated_at or utcnow_iso()

    updated_at = _safe_text(raw_state.get("updated_at"))
    normalized["updated_at"] = updated_at or utcnow_iso()
    return normalized


def patch_texture_plan_state(
    state: dict[str, Any] | None,
    *,
    brief_json: dict[str, Any] | None = None,
    selected_image_keywords: list[str] | None = None,
    clear_document: bool = False,
    clear_image: bool = False,
) -> dict[str, Any]:
    normalized = normalize_texture_plan_state(state, brief_json=brief_json)

    if selected_image_keywords is not None:
        normalized["selected_image_keywords"] = _safe_list(selected_image_keywords, max_items=16)

    if clear_document:
        normalized["document_name"] = None
        normalized["document_excerpt"] = ""

    if clear_image:
        normalized["image_name"] = None
        normalized["image_content_keywords"] = []
        normalized["image_style_keywords"] = []
        normalized["selected_image_keywords"] = []

    normalized["updated_at"] = utcnow_iso()
    return normalized


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _safe_optional_text(value: Any) -> str | None:
    text = _safe_text(value)
    return text or None


def _safe_list(value: Any, *, max_items: int) -> list[str]:
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


def _normalize_schemes(value: Any) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            scheme_id = _safe_text(item.get("id"))
            if scheme_id not in TEXTURE_SCHEME_IDS:
                continue
            by_id[scheme_id] = {
                "id": scheme_id,
                "title": _safe_text(item.get("title")),
                "strategy": _safe_text(item.get("strategy")),
                "prompt_text": _safe_text(item.get("prompt_text")),
                "key_points": _safe_list(item.get("key_points"), max_items=8),
            }

    normalized: list[dict[str, Any]] = []
    for index, scheme_id in enumerate(TEXTURE_SCHEME_IDS, start=1):
        existing = by_id.get(scheme_id)
        if existing is None:
            normalized.append(
                {
                    "id": scheme_id,
                    "title": f"Scheme {index}",
                    "strategy": "",
                    "prompt_text": "",
                    "key_points": [],
                }
            )
            continue
        if not existing["title"]:
            existing["title"] = f"Scheme {index}"
        normalized.append(existing)
    return normalized


def _normalize_textured_models(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result_id = _safe_optional_text(item.get("result_id")) or _safe_text(item.get("scheme_id"))
        source_type = _safe_text(item.get("source_type")).lower()
        created_at = (
            _safe_optional_text(item.get("created_at"))
            or _safe_optional_text(item.get("updated_at"))
            or utcnow_iso()
        )
        normalized.append(
            {
                "result_id": result_id or f"legacy_{len(normalized) + 1}",
                "batch_id": _safe_optional_text(item.get("batch_id")),
                "source_type": source_type if source_type in {"generated", "uploaded", "imported"} else "generated",
                "created_at": created_at,
                "family_id": _safe_optional_text(item.get("family_id")) or result_id or f"legacy_{len(normalized) + 1}",
                "parent_result_id": _safe_optional_text(item.get("parent_result_id")),
                "scheme_id": _safe_text(item.get("scheme_id")),
                "title": _safe_text(item.get("title")),
                "prompt_text": _safe_text(item.get("prompt_text")),
                "status": _safe_text(item.get("status")) or "pending",
                "textured_model_url": _safe_optional_text(item.get("textured_model_url")),
                "texture_maps": _normalize_texture_maps(item.get("texture_maps")),
                "edited_variant": _normalize_edited_variant(item.get("edited_variant")),
                "review_assessment": _normalize_review_assessment(item.get("review_assessment")),
                "meshy_task_id": _safe_optional_text(item.get("meshy_task_id")),
                "error_message": _safe_optional_text(item.get("error_message")),
                "shared_origin": _normalize_shared_origin(item.get("shared_origin")),
            }
        )
    return normalized


def _normalize_texture_maps(value: Any) -> dict[str, str | None] | None:
    if not isinstance(value, dict):
        return None
    normalized = {
        "base_color": _safe_optional_text(value.get("base_color")),
        "metallic": _safe_optional_text(value.get("metallic")),
        "normal": _safe_optional_text(value.get("normal")),
        "roughness": _safe_optional_text(value.get("roughness")),
    }
    if not any(normalized.values()):
        return None
    return normalized


def _normalize_edited_variant(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    model_url = _safe_optional_text(value.get("model_url"))
    base_color_url = _safe_optional_text(value.get("base_color_url"))
    applied_at = _safe_optional_text(value.get("applied_at"))
    if not model_url or not base_color_url or not applied_at:
        return None
    return {
        "model_url": model_url,
        "base_color_url": base_color_url,
        "applied_at": applied_at,
    }


def _normalize_review_assessment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    status = _safe_text(value.get("status")).lower()
    source = _safe_text(value.get("source")).lower()
    model_name = _safe_optional_text(value.get("model_name"))
    error_message = _safe_optional_text(value.get("error_message"))
    settings_revision_used = _safe_int(value.get("settings_revision_used"))
    overall_narrative = _safe_optional_text(value.get("overall_narrative"))
    raw_persona_labels = value.get("persona_labels_used")
    raw_role_reviews = value.get("role_reviews")
    engineering = value.get("engineering")
    passenger = value.get("passenger")
    recommendation = _safe_optional_text(value.get("recommendation"))
    persona_labels_used = _normalize_review_persona_labels(raw_persona_labels)
    role_reviews = _normalize_role_reviews(raw_role_reviews)
    passenger_scores = passenger.get("scores") if isinstance(passenger, dict) else None
    has_metrics = (
        isinstance(engineering, dict)
        and isinstance(passenger, dict)
        and isinstance(passenger_scores, dict)
        and bool(recommendation)
    )

    if status not in {"completed", "failed"}:
        status = "completed" if source == "llm" and has_metrics else "failed"

    normalized_source = source if source in {"llm", "failed"} else "failed"

    if status == "completed" and has_metrics and normalized_source == "llm":
        normalized = {
            "status": "completed",
            "engineering": {
                "paint_volume_kg": _safe_float(engineering.get("paint_volume_kg")),
                "color_zone_count": _safe_int(engineering.get("color_zone_count")),
                "masking_steps": _safe_int(engineering.get("masking_steps")),
                "gradient_ratio_percent": _safe_float(engineering.get("gradient_ratio_percent")),
                "labor_hours": _safe_int(engineering.get("labor_hours")),
                "process_steps": _safe_int(engineering.get("process_steps")),
                "curve_conformance_score": _safe_int(engineering.get("curve_conformance_score")),
                "material_cost_yuan": _safe_int(engineering.get("material_cost_yuan")),
                "labor_cost_yuan": _safe_int(engineering.get("labor_cost_yuan")),
                "total_cost_yuan": _safe_int(engineering.get("total_cost_yuan")),
                "color_variance_risk": _safe_text(engineering.get("color_variance_risk")) or "MEDIUM",
                "weather_durability": _safe_text(engineering.get("weather_durability")) or "B",
                "maintenance_cycle_years": _safe_int(engineering.get("maintenance_cycle_years")),
                "summary": _safe_optional_text(engineering.get("summary")),
                "quick_comment": _safe_optional_text(engineering.get("quick_comment")),
            },
            "passenger": {
                "scores": {
                    "first_impression": _safe_int(passenger_scores.get("first_impression")),
                    "safety_trust": _safe_int(passenger_scores.get("safety_trust")),
                    "comfort_cleanliness": _safe_int(passenger_scores.get("comfort_cleanliness")),
                    "perceived_quality": _safe_int(passenger_scores.get("perceived_quality")),
                    "speed_motion": _safe_int(passenger_scores.get("speed_motion")),
                    "emotion_character": _safe_int(passenger_scores.get("emotion_character")),
                },
                "overall_score": round(_safe_float(passenger.get("overall_score")), 1),
                "summary": _safe_optional_text(passenger.get("summary")) or "",
                "quick_comment": _safe_optional_text(passenger.get("quick_comment")),
                "strengths": _safe_text_list(passenger.get("strengths"), max_items=4),
                "issues": _safe_text_list(passenger.get("issues"), max_items=4),
                "suggestions": _safe_text_list(passenger.get("suggestions"), max_items=4),
            },
            "role_reviews": role_reviews,
            "recommendation": recommendation,
            "overall_narrative": overall_narrative,
            "source": normalized_source,
            "model_name": model_name,
            "error_message": None,
            "settings_revision_used": settings_revision_used or None,
            "persona_labels_used": persona_labels_used,
        }

        if (
            normalized["engineering"]["color_zone_count"] <= 0
            or normalized["passenger"]["scores"]["first_impression"] <= 0
            or not normalized["passenger"]["summary"]
        ):
            return None
        return normalized

    return {
        "status": "failed",
        "engineering": None,
        "passenger": None,
        "role_reviews": role_reviews,
        "recommendation": None,
        "overall_narrative": overall_narrative,
        "source": "failed",
        "model_name": model_name,
        "error_message": error_message or "Stage 3 review failed.",
        "settings_revision_used": settings_revision_used or None,
        "persona_labels_used": persona_labels_used,
    }


def _normalize_review_persona_labels(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    passenger = _safe_optional_text(value.get("passenger"))
    engineering = _safe_optional_text(value.get("engineering"))
    if not passenger or not engineering:
        return None
    return {
        "passenger": passenger,
        "engineering": engineering,
    }


def _normalize_role_reviews(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        role_id = _safe_optional_text(item.get("role_id")) or _safe_optional_text(item.get("id"))
        role_type = _safe_optional_text(item.get("role_type")) or _safe_optional_text(item.get("type"))
        role_name = _safe_optional_text(item.get("role_name")) or _safe_optional_text(item.get("display_name"))
        assessment = item.get("assessment")
        if role_type not in {"passenger", "engineering"} or not role_id or not role_name or not isinstance(assessment, dict):
            continue
        normalized.append(
            {
                "role_id": role_id,
                "role_type": role_type,
                "role_name": role_name,
                "assessment": assessment,
            }
        )
    return normalized


def _normalize_shared_origin(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    user_id = _safe_int(value.get("user_id"))
    user_name = _safe_optional_text(value.get("user_name"))
    source_result_id = _safe_optional_text(value.get("source_result_id"))
    if user_id <= 0 or not user_name or not source_result_id:
        return None
    return {
        "user_id": user_id,
        "user_name": user_name,
        "source_result_id": source_result_id,
    }


def _safe_float(value: Any) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except ValueError:
            return 0
    return 0


def _safe_text_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        text = _safe_optional_text(item)
        if not text:
            continue
        normalized.append(text)
        if len(normalized) >= max_items:
            break
    return normalized
