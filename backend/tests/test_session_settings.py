from app.session_settings import default_session_settings, normalize_session_settings, patch_session_settings


def test_role_prompt_is_preserved_for_session_review_roles() -> None:
    current = default_session_settings(updated_by_user_id=1)
    patched = patch_session_settings(
        current,
        {
            "review_personas": {
                "roles": [
                    {
                        "id": "passenger_commuter",
                        "type": "passenger",
                        "enabled": True,
                        "display_name": "Airport Commuter",
                        "identity_summary": "A passenger focused on quick recognition and low cognitive load.",
                        "role_prompt": "Prefer clarity over decorative richness.",
                        "focus_points": ["platform recognition"],
                        "preference_tags": ["clear hierarchy"],
                        "dislike_tags": ["busy graphics"],
                        "priority_tags": [],
                        "risk_focus": [],
                    },
                    {
                        "id": "engineering_maintenance",
                        "type": "engineering",
                        "enabled": True,
                        "display_name": "Maintenance Supervisor",
                        "identity_summary": "A reviewer focused on repeatable depot maintenance.",
                        "role_prompt": "Reject schemes with unresolved maintenance ambiguity.",
                        "focus_points": ["repair workflow"],
                        "preference_tags": [],
                        "dislike_tags": [],
                        "priority_tags": ["repeatable process"],
                        "risk_focus": ["maintenance ambiguity"],
                    },
                ]
            }
        },
        updated_by_user_id=7,
    )

    normalized = normalize_session_settings(patched)
    roles = {role["id"]: role for role in normalized["review_personas"]["roles"]}

    assert normalized["revision"] == 2
    assert roles["passenger_commuter"]["role_prompt"] == "Prefer clarity over decorative richness."
    assert roles["engineering_maintenance"]["role_prompt"] == "Reject schemes with unresolved maintenance ambiguity."


def test_missing_role_prompt_gets_generated_for_non_custom_roles() -> None:
    settings = normalize_session_settings(
        {
            "review_personas": {
                "roles": [
                    {
                        "id": "engineering_maintenance",
                        "type": "engineering",
                        "enabled": True,
                        "display_name": "Maintenance Supervisor",
                        "identity_summary": "A reviewer focused on repeatable depot maintenance.",
                        "focus_points": ["repair workflow"],
                        "priority_tags": ["repeatable process"],
                        "risk_focus": ["maintenance ambiguity"],
                    }
                ]
            }
        }
    )

    role_prompt = settings["review_personas"]["roles"][0]["role_prompt"]
    assert "Maintenance Supervisor" in role_prompt
    assert "repeatable process" in role_prompt
    assert "maintenance ambiguity" in role_prompt
