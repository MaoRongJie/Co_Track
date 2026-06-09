from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ROLE_TYPES = {"passenger", "engineering", "custom"}
MAX_REVIEW_ROLES = 8


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_settings_sections() -> list[dict[str, Any]]:
    return [
        {
            "id": "review_roles",
            "label": "评审角色",
            "description": "增删和编辑阶段三使用的乘客类、工程类和自定义评审角色。",
            "enabled": True,
            "badge": None,
        },
        {
            "id": "collaboration_rules",
            "label": "协作规则",
            "description": "共享讨论规则和主持控制。",
            "enabled": False,
            "badge": "即将开放",
        },
        {
            "id": "meeting_workflow",
            "label": "会议流程",
            "description": "协作空间阶段自动化与评审流程偏好。",
            "enabled": False,
            "badge": "即将开放",
        },
        {
            "id": "export_preferences",
            "label": "导出偏好",
            "description": "导出打包和报告格式设置。",
            "enabled": False,
            "badge": "即将开放",
        },
    ]


def build_settings_permissions(role: str) -> dict[str, Any]:
    normalized_role = role if role in {"host", "designer", "observer"} else "designer"
    return {
        "role": normalized_role,
        "can_edit": normalized_role == "host",
    }


def default_passenger_persona() -> dict[str, Any]:
    return {
        "display_name": "普通乘客",
        "identity_summary": "从第一印象、舒适度、信任感和乘坐意愿判断方案的普通高铁乘客。",
        "preference_tags": ["干净", "可靠", "现代", "舒适"],
        "dislike_tags": ["图形杂乱", "对比刺眼", "质感廉价"],
        "focus_points": ["第一印象", "安全信任", "舒适整洁", "品质感"],
    }


def default_engineering_persona() -> dict[str, Any]:
    return {
        "display_name": "涂装工艺工程师",
        "identity_summary": "从可制造性、遮蔽工序、耐久性和全周期成本评估外观涂装的工程角色。",
        "priority_tags": ["工艺稳定", "涂层耐久", "色区可控", "易维护"],
        "risk_focus": ["色差风险", "渐变复杂度", "遮蔽工作量", "维护周期"],
        "focus_points": ["油漆用量", "工艺步骤", "成本", "耐久性", "曲面贴合"],
    }


def default_review_roles() -> list[dict[str, Any]]:
    return [
        {
            "id": "passenger_default",
            "type": "passenger",
            "enabled": True,
            **default_passenger_persona(),
        },
        {
            "id": "engineering_default",
            "type": "engineering",
            "enabled": True,
            **default_engineering_persona(),
        },
    ]


def default_session_settings(*, updated_by_user_id: int | None = None) -> dict[str, Any]:
    roles = default_review_roles()
    return {
        "revision": 1,
        "updated_at": None,
        "updated_by_user_id": updated_by_user_id,
        "review_personas": _review_personas_from_roles(roles),
    }


def normalize_session_settings(
    value: Any,
    *,
    fallback_updated_by_user_id: int | None = None,
) -> dict[str, Any]:
    defaults = default_session_settings(updated_by_user_id=fallback_updated_by_user_id)
    if not isinstance(value, dict):
        return defaults

    review_personas = value.get("review_personas")
    review_personas = review_personas if isinstance(review_personas, dict) else {}
    default_roles = list(defaults["review_personas"]["roles"])
    roles = _normalize_review_roles(review_personas.get("roles"), default_roles=default_roles, strict=False)

    if "roles" not in review_personas:
        passenger = _normalize_passenger_persona(
            review_personas.get("passenger"),
            defaults["review_personas"]["passenger"],
        )
        engineering = _normalize_engineering_persona(
            review_personas.get("engineering"),
            defaults["review_personas"]["engineering"],
        )
        roles = [
            {"id": "passenger_default", "type": "passenger", "enabled": True, **passenger},
            {"id": "engineering_default", "type": "engineering", "enabled": True, **engineering},
        ]

    revision = _normalize_revision(value.get("revision"))
    updated_at = _normalize_optional_text(value.get("updated_at"), maximum_chars=64)
    updated_by_user_id = _normalize_optional_int(value.get("updated_by_user_id"))

    return {
        "revision": revision,
        "updated_at": updated_at,
        "updated_by_user_id": updated_by_user_id if updated_by_user_id is not None else fallback_updated_by_user_id,
        "review_personas": _review_personas_from_roles(roles),
    }


def patch_session_settings(
    current_value: Any,
    patch_value: Any,
    *,
    updated_by_user_id: int,
) -> dict[str, Any]:
    current = normalize_session_settings(current_value, fallback_updated_by_user_id=updated_by_user_id)
    patch = patch_value if isinstance(patch_value, dict) else {}
    patch_review_personas = patch.get("review_personas") if isinstance(patch.get("review_personas"), dict) else {}

    if "roles" in patch_review_personas:
        next_roles = _normalize_review_roles(
            patch_review_personas.get("roles"),
            default_roles=list(current["review_personas"]["roles"]),
            strict=True,
        )
    else:
        next_passenger = _normalize_passenger_persona(
            patch_review_personas.get("passenger"),
            current["review_personas"]["passenger"],
        )
        next_engineering = _normalize_engineering_persona(
            patch_review_personas.get("engineering"),
            current["review_personas"]["engineering"],
        )
        next_roles = [
            {**current["review_personas"]["roles"][0], "type": "passenger", **next_passenger},
            {**current["review_personas"]["roles"][1], "type": "engineering", **next_engineering},
        ]

    next_review_personas = _review_personas_from_roles(next_roles)
    if next_review_personas == current["review_personas"]:
        return {
            **current,
            "updated_by_user_id": updated_by_user_id if current.get("updated_by_user_id") is None else current.get("updated_by_user_id"),
        }

    return {
        "revision": int(current.get("revision") or 1) + 1,
        "updated_at": utcnow_iso(),
        "updated_by_user_id": updated_by_user_id,
        "review_personas": next_review_personas,
    }


def session_persona_labels(value: Any) -> dict[str, str]:
    settings = normalize_session_settings(value)
    review_personas = settings["review_personas"]
    return {
        "passenger": str(review_personas["passenger"]["display_name"]),
        "engineering": str(review_personas["engineering"]["display_name"]),
    }


def session_review_roles(value: Any) -> list[dict[str, Any]]:
    settings = normalize_session_settings(value)
    return list(settings["review_personas"]["roles"])


def _review_personas_from_roles(roles: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_roles = _normalize_review_roles(roles, default_roles=default_review_roles(), strict=False)
    passenger_role = _first_role_of_type(normalized_roles, "passenger")
    engineering_role = _first_role_of_type(normalized_roles, "engineering")
    return {
        "passenger": _role_to_passenger_persona(passenger_role),
        "engineering": _role_to_engineering_persona(engineering_role),
        "roles": normalized_roles,
    }


def _first_role_of_type(roles: list[dict[str, Any]], role_type: str) -> dict[str, Any]:
    for role in roles:
        if role.get("type") == role_type and role.get("enabled", True):
            return role
    for role in roles:
        if role.get("type") == role_type:
            return role
    return default_review_roles()[0 if role_type == "passenger" else 1]


def _role_to_passenger_persona(role: dict[str, Any]) -> dict[str, Any]:
    defaults = default_passenger_persona()
    return {
        "display_name": _normalize_text(role.get("display_name"), defaults["display_name"], maximum_chars=60),
        "identity_summary": _normalize_text(role.get("identity_summary"), defaults["identity_summary"], maximum_chars=360),
        "preference_tags": _normalize_text_list(role.get("preference_tags"), defaults["preference_tags"], max_items=8, maximum_chars=60),
        "dislike_tags": _normalize_text_list(role.get("dislike_tags"), defaults["dislike_tags"], max_items=8, maximum_chars=60),
        "focus_points": _normalize_text_list(role.get("focus_points"), defaults["focus_points"], max_items=8, maximum_chars=90),
    }


def _role_to_engineering_persona(role: dict[str, Any]) -> dict[str, Any]:
    defaults = default_engineering_persona()
    return {
        "display_name": _normalize_text(role.get("display_name"), defaults["display_name"], maximum_chars=60),
        "identity_summary": _normalize_text(role.get("identity_summary"), defaults["identity_summary"], maximum_chars=360),
        "priority_tags": _normalize_text_list(role.get("priority_tags"), defaults["priority_tags"], max_items=8, maximum_chars=60),
        "risk_focus": _normalize_text_list(role.get("risk_focus"), defaults["risk_focus"], max_items=8, maximum_chars=60),
        "focus_points": _normalize_text_list(role.get("focus_points"), defaults["focus_points"], max_items=8, maximum_chars=90),
    }


def _normalize_review_roles(
    value: Any,
    *,
    default_roles: list[dict[str, Any]],
    strict: bool,
) -> list[dict[str, Any]]:
    source_roles = value if isinstance(value, list) else default_roles
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    defaults_by_type = {
        "passenger": default_review_roles()[0],
        "engineering": default_review_roles()[1],
        "custom": {
            "id": "custom_default",
            "type": "custom",
            "enabled": True,
            "display_name": "自定义评审角色",
            "identity_summary": "根据自定义身份、关注点和项目目标对方案提供参考性评审。",
            "focus_points": ["角色关注点", "方案匹配度", "风险与建议"],
            "preference_tags": [],
            "dislike_tags": [],
            "priority_tags": [],
            "risk_focus": [],
            "role_prompt": "",
        },
    }

    for index, raw_role in enumerate(source_roles[:MAX_REVIEW_ROLES]):
        if not isinstance(raw_role, dict):
            continue
        role_type = _normalize_role_type(raw_role.get("type") or raw_role.get("role_type"))
        if role_type is None:
            role_type = _normalize_role_type(raw_role.get("roleType"))
        if role_type is None:
            continue

        default_role = defaults_by_type[role_type]
        fallback_id = str(raw_role.get("id") or default_role["id"] or f"{role_type}_{index + 1}")
        role_id = _normalize_role_id(fallback_id, fallback=f"{role_type}_{index + 1}")
        while role_id in seen_ids:
            role_id = f"{role_id}_{len(seen_ids) + 1}"
        seen_ids.add(role_id)

        normalized_role = {
            "id": role_id,
            "type": role_type,
            "enabled": _normalize_bool(raw_role.get("enabled"), fallback=True),
            "display_name": _normalize_text(
                _first_present(raw_role, "display_name", "displayName"),
                default_role["display_name"],
                maximum_chars=60,
            ),
            "identity_summary": _normalize_text(
                _first_present(raw_role, "identity_summary", "identitySummary"),
                default_role["identity_summary"],
                maximum_chars=360,
            ),
            "focus_points": _normalize_role_text_list(
                raw_role,
                ("focus_points", "focusPoints"),
                default_role["focus_points"],
                max_items=8,
                maximum_chars=90,
            ),
            "role_prompt": _normalize_optional_role_text(
                _first_present(raw_role, "role_prompt", "rolePrompt"),
                maximum_chars=1200,
            ),
        }
        if role_type == "passenger":
            normalized_role.update(
                {
                    "preference_tags": _normalize_role_text_list(
                        raw_role,
                        ("preference_tags", "preferenceTags"),
                        default_role["preference_tags"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                    "dislike_tags": _normalize_role_text_list(
                        raw_role,
                        ("dislike_tags", "dislikeTags"),
                        default_role["dislike_tags"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                    "priority_tags": [],
                    "risk_focus": [],
                }
            )
        elif role_type == "engineering":
            normalized_role.update(
                {
                    "preference_tags": [],
                    "dislike_tags": [],
                    "priority_tags": _normalize_role_text_list(
                        raw_role,
                        ("priority_tags", "priorityTags"),
                        default_role["priority_tags"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                    "risk_focus": _normalize_role_text_list(
                        raw_role,
                        ("risk_focus", "riskFocus"),
                        default_role["risk_focus"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                }
            )
        else:
            normalized_role.update(
                {
                    "preference_tags": _normalize_role_text_list(
                        raw_role,
                        ("preference_tags", "preferenceTags"),
                        default_role["preference_tags"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                    "dislike_tags": _normalize_role_text_list(
                        raw_role,
                        ("dislike_tags", "dislikeTags"),
                        default_role["dislike_tags"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                    "priority_tags": _normalize_role_text_list(
                        raw_role,
                        ("priority_tags", "priorityTags"),
                        default_role["priority_tags"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                    "risk_focus": _normalize_role_text_list(
                        raw_role,
                        ("risk_focus", "riskFocus"),
                        default_role["risk_focus"],
                        max_items=8,
                        maximum_chars=60,
                    ),
                }
            )
        if not normalized_role["role_prompt"]:
            normalized_role["role_prompt"] = _build_role_prompt(normalized_role)
        normalized.append(normalized_role)

    has_enabled_role = any(role.get("enabled", True) for role in normalized)
    if strict and not has_enabled_role:
        raise ValueError("至少需要保留一个启用的评审角色。")
    if not normalized or not has_enabled_role:
        normalized = default_review_roles()
    return normalized[:MAX_REVIEW_ROLES]


def _normalize_passenger_persona(value: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "display_name": _normalize_text(source.get("display_name"), defaults["display_name"], maximum_chars=60),
        "identity_summary": _normalize_text(source.get("identity_summary"), defaults["identity_summary"], maximum_chars=360),
        "preference_tags": _normalize_text_list(source.get("preference_tags"), defaults["preference_tags"], max_items=8, maximum_chars=60),
        "dislike_tags": _normalize_text_list(source.get("dislike_tags"), defaults["dislike_tags"], max_items=8, maximum_chars=60),
        "focus_points": _normalize_text_list(source.get("focus_points"), defaults["focus_points"], max_items=8, maximum_chars=90),
    }


def _normalize_engineering_persona(value: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "display_name": _normalize_text(source.get("display_name"), defaults["display_name"], maximum_chars=60),
        "identity_summary": _normalize_text(source.get("identity_summary"), defaults["identity_summary"], maximum_chars=360),
        "priority_tags": _normalize_text_list(source.get("priority_tags"), defaults["priority_tags"], max_items=8, maximum_chars=60),
        "risk_focus": _normalize_text_list(source.get("risk_focus"), defaults["risk_focus"], max_items=8, maximum_chars=60),
        "focus_points": _normalize_text_list(source.get("focus_points"), defaults["focus_points"], max_items=8, maximum_chars=90),
    }


def _normalize_role_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in ROLE_TYPES else None


def _normalize_optional_role_text(value: Any, *, maximum_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    normalized = "\n".join(" ".join(line.strip().split()) for line in value.splitlines() if line.strip())
    return normalized[:maximum_chars].rstrip()


def _build_role_prompt(role: dict[str, Any]) -> str:
    display_name = str(role.get("display_name") or role.get("displayName") or "自定义评审角色").strip()
    identity_summary = str(role.get("identity_summary") or role.get("identitySummary") or "根据该角色立场评估方案。").strip()
    focus_points = _normalize_text_list(
        role.get("focus_points") or role.get("focusPoints"),
        [],
        max_items=8,
        maximum_chars=90,
        allow_empty=True,
    )
    preference_tags = _normalize_text_list(
        role.get("preference_tags") or role.get("preferenceTags"),
        [],
        max_items=8,
        maximum_chars=60,
        allow_empty=True,
    )
    dislike_tags = _normalize_text_list(
        role.get("dislike_tags") or role.get("dislikeTags"),
        [],
        max_items=8,
        maximum_chars=60,
        allow_empty=True,
    )
    priority_tags = _normalize_text_list(
        role.get("priority_tags") or role.get("priorityTags"),
        [],
        max_items=8,
        maximum_chars=60,
        allow_empty=True,
    )
    risk_focus = _normalize_text_list(
        role.get("risk_focus") or role.get("riskFocus"),
        [],
        max_items=8,
        maximum_chars=60,
        allow_empty=True,
    )
    parts = [
        f"你将扮演“{display_name}”。",
        f"角色身份与特征：{identity_summary}",
    ]
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
    parts.append("请始终从该角色的真实立场出发，围绕方案是否符合其利益、期待、限制和决策习惯给出具体反馈。")
    return "\n".join(parts)


def _normalize_role_id(value: Any, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip().lower())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized[:80] or fallback


def _normalize_bool(value: Any, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _normalize_role_text_list(
    source: dict[str, Any],
    keys: tuple[str, ...],
    fallback: list[str],
    *,
    max_items: int,
    maximum_chars: int,
) -> list[str]:
    for key in keys:
        if key in source:
            return _normalize_text_list(source.get(key), [], max_items=max_items, maximum_chars=maximum_chars, allow_empty=True)
    return list(fallback)


def _normalize_text(value: Any, fallback: str, *, maximum_chars: int) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.strip().split())
    if not normalized:
        return fallback
    return normalized[:maximum_chars].rstrip()


def _normalize_optional_text(value: Any, *, maximum_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    return normalized[:maximum_chars].rstrip()


def _normalize_text_list(
    value: Any,
    fallback: list[str],
    *,
    max_items: int,
    maximum_chars: int,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = " ".join(item.strip().split())
        if not text:
            continue
        text = text[:maximum_chars].rstrip()
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= max_items:
            break

    if allow_empty:
        return normalized
    return normalized or list(fallback)


def _normalize_revision(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, parsed)


def _normalize_optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
