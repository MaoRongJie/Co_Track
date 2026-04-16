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

    return {
        "theme": _safe_text(brief_json.get("theme")),
        "main_colors": _safe_list(brief_json.get("mainColors"), max_items=6),
        "accent_colors": _safe_list(brief_json.get("accentColors"), max_items=6),
        "style_keywords": _safe_list(brief_json.get("styleKeywords"), max_items=8),
        "design_elements": _safe_list(brief_json.get("designElements"), max_items=8),
        "constraints_hint": _safe_text(brief_json.get("constraintsHint")),
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
        normalized.append(
            {
                "scheme_id": _safe_text(item.get("scheme_id")),
                "title": _safe_text(item.get("title")),
                "prompt_text": _safe_text(item.get("prompt_text")),
                "status": _safe_text(item.get("status")) or "pending",
                "textured_model_url": _safe_optional_text(item.get("textured_model_url")),
                "texture_maps": _normalize_texture_maps(item.get("texture_maps")),
                "edited_variant": _normalize_edited_variant(item.get("edited_variant")),
                "meshy_task_id": _safe_optional_text(item.get("meshy_task_id")),
                "error_message": _safe_optional_text(item.get("error_message")),
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
