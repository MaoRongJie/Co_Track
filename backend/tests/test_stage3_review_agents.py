import asyncio

import app.agents.stage3_review_agents as review_module
from app.agents.providers.provider_protocols import ModelProviderError
from app.agents.stage3_review_agents import Stage3ReviewContext, Stage3ReviewService


class _FailingEngineeringAgent:
    model = "gpt-4o"

    async def review(self, *, provider, context, image_metrics, image_data_url):  # noqa: ANN001
        _ = (provider, context, image_metrics, image_data_url)
        raise ModelProviderError(
            "OpenAI text API request failed: RemoteProtocolError: Server disconnected without sending a response.",
            status_code=502,
            provider_code="OPENAI_TEXT_NETWORK_ERROR",
        )


class _FailingPassengerAgent:
    model = "gpt-4o"

    async def review(self, *, provider, context, image_metrics, image_data_url):  # noqa: ANN001
        _ = (provider, context, image_metrics, image_data_url)
        return {
            "scores": {
                "first_impression": 8,
                "safety_trust": 8,
                "comfort_cleanliness": 7,
                "perceived_quality": 8,
                "speed_motion": 7,
                "emotion_character": 7,
            },
            "overall_score": 7.8,
            "summary": "It looks modern, reassuring, and easy to trust at first glance.",
            "quick_comment": "The scheme feels calm and easy to trust, but it could use one sharper signature detail.",
            "strengths": [
                "The blue-white balance feels calm and reliable.",
                "The body graphics stay easy to recognize from a distance.",
            ],
            "issues": [
                "The visual story is a little safe rather than exciting.",
                "Some areas feel clean but not especially memorable.",
            ],
            "suggestions": [
                "Add one stronger visual accent to make it easier to remember.",
                "Sharpen the directional graphics so it feels faster on arrival.",
            ],
        }


class _CapturingProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.messages: list[list[dict[str, object]]] = []

    async def complete_json_with_messages(self, *, messages, temperature, model):  # noqa: ANN001
        _ = (temperature, model)
        self.messages.append(messages)
        return self.payload


def _review_context(review_personas: dict[str, object]) -> Stage3ReviewContext:
    return Stage3ReviewContext(
        product_category="high_speed_train",
        brief_json={"theme": "winter"},
        surface_area_m2=120.0,
        paintable_uv_pixels=1024 * 1024,
        uv_width=1024,
        uv_height=1024,
        mesh_count=2,
        material_count=1,
        uv_source="embedded",
        scheme_id="scheme_1",
        scheme_title="Scheme 1",
        prompt_text="Winter blue streamline with snow accents.",
        texture_reference="/files/textures/demo.png",
        settings_revision=4,
        review_personas=review_personas,
    )


def test_stage3_review_returns_failed_without_retry_on_provider_transport_failure(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        review_module,
        "_texture_reference_to_data_url",
        lambda texture_reference: "data:image/jpeg;base64,ZmFrZQ==",
    )

    service = Stage3ReviewService(
        engineering_agent=_FailingEngineeringAgent(),
        passenger_agent=_FailingPassengerAgent(),
    )
    context = Stage3ReviewContext(
        product_category="high_speed_train",
        brief_json={"theme": "winter"},
        surface_area_m2=120.0,
        paintable_uv_pixels=1024 * 1024,
        uv_width=1024,
        uv_height=1024,
        mesh_count=2,
        material_count=1,
        uv_source="embedded",
        scheme_id="scheme_1",
        scheme_title="Scheme 1",
        prompt_text="Winter blue streamline with snow accents.",
        texture_reference="/files/textures/demo.png",
        settings_revision=4,
        review_personas={
            "passenger": {"display_name": "Airport Commuter"},
            "engineering": {"display_name": "Maintenance Supervisor"},
        },
    )

    assessment = asyncio.run(service.analyze_scheme(provider=object(), context=context))

    assert assessment.status == "failed"
    assert assessment.source == "failed"
    assert assessment.model_name == "gpt-4o"
    assert assessment.engineering is None
    assert assessment.passenger is None
    assert assessment.error_message is not None
    assert "OpenAI text API request failed" in assessment.error_message
    assert assessment.settings_revision_used == 4
    assert assessment.persona_labels_used == {
        "passenger": "Airport Commuter",
        "engineering": "Maintenance Supervisor",
    }


def test_engineering_agent_includes_role_prompt_as_skill_instruction() -> None:
    provider = _CapturingProvider(
        {
            "paint_volume_kg": 84.6,
            "color_zone_count": 3,
            "masking_steps": 2,
            "gradient_ratio_percent": 18.0,
            "labor_hours": 144,
            "process_steps": 5,
            "curve_conformance_score": 79,
            "material_cost_yuan": 28000,
            "labor_cost_yuan": 21000,
            "total_cost_yuan": 49000,
            "color_variance_risk": "LOW",
            "weather_durability": "A",
            "maintenance_cycle_years": 6,
            "summary": "Process complexity stays controlled while keeping the scheme recognizable.",
            "quick_comment": "Feasible overall, but keep checking masking tolerance near curved surfaces.",
        }
    )
    context = _review_context(
        {
            "engineering": {
                "display_name": "Maintenance Supervisor",
                "identity_summary": "A reviewer focused on maintainability and repeatable depot work.",
                "role_prompt": "Team-specific rule: reject schemes with unresolved maintenance ambiguity.",
                "priority_tags": ["repeatable process"],
                "risk_focus": ["maintenance ambiguity"],
                "focus_points": ["repair workflow"],
            }
        }
    )

    asyncio.run(
        review_module.EngineeringPerspectiveAgent(model="fake-review-model").review(
            provider=provider,
            context=context,
            image_metrics={"estimated_color_zones": 3},
            image_data_url="data:image/jpeg;base64,ZmFrZQ==",
        )
    )

    system_prompt = str(provider.messages[0][0]["content"])
    assert "会话内评价标准 / Skill 指令" in system_prompt
    assert "Team-specific rule: reject schemes with unresolved maintenance ambiguity." in system_prompt
    assert "不得改变下方 JSON schema" in system_prompt
    assert '"paint_volume_kg": number' in system_prompt


def test_passenger_agent_includes_role_prompt_as_skill_instruction() -> None:
    provider = _CapturingProvider(
        {
            "scores": {
                "first_impression": 8,
                "safety_trust": 8,
                "comfort_cleanliness": 7,
                "perceived_quality": 8,
                "speed_motion": 7,
                "emotion_character": 7,
            },
            "overall_score": 7.8,
            "summary": "Passengers would likely read the scheme as calm, clear, and easy to trust.",
            "quick_comment": "The scheme feels reassuring, but it could use one more memorable accent.",
            "strengths": [
                "The blue-white balance feels calm and reliable.",
                "The graphics stay legible from a distance.",
            ],
            "issues": [
                "The visual story is a little safe rather than exciting.",
                "Some areas feel clean but not especially memorable.",
            ],
            "suggestions": [
                "Add one stronger visual accent to make it easier to remember.",
                "Sharpen the directional graphics so it feels faster on arrival.",
            ],
        }
    )
    context = _review_context(
        {
            "passenger": {
                "display_name": "Airport Commuter",
                "identity_summary": "A passenger focused on fast recognition and low cognitive load.",
                "role_prompt": "Team-specific rule: prefer low cognitive load over decorative richness.",
                "preference_tags": ["low cognitive load"],
                "dislike_tags": ["busy graphics"],
                "focus_points": ["platform recognition"],
            }
        }
    )

    asyncio.run(
        review_module.PassengerPerspectiveAgent(model="fake-review-model").review(
            provider=provider,
            context=context,
            image_metrics={"contrast_score": 48},
            image_data_url="data:image/jpeg;base64,ZmFrZQ==",
        )
    )

    system_prompt = str(provider.messages[0][0]["content"])
    assert "会话内评价标准 / Skill 指令" in system_prompt
    assert "Team-specific rule: prefer low cognitive load over decorative richness." in system_prompt
    assert "不得改变下方 JSON schema" in system_prompt
    assert '"overall_score": number' in system_prompt


def test_sanitize_passenger_assessment_keeps_short_comments_and_trims_whitespace() -> None:
    sanitized = review_module._sanitize_passenger_assessment(  # noqa: SLF001
        {
            "scores": {
                "first_impression": 8,
                "safety_trust": 8,
                "comfort_cleanliness": 7,
                "perceived_quality": 8,
                "speed_motion": 7,
                "emotion_character": 7,
            },
            "overall_score": 7.8,
            "summary": "  Passengers would likely read the texture as calm, legible, and intentionally seasonal.  ",
            "quick_comment": "  Looks reassuring overall, but one stronger accent would make it easier to remember.  ",
            "strengths": [
                "  The cool palette feels steady and restful on longer trips.  ",
                "The bright side band remains easy to identify from the platform.",
            ],
            "issues": [
                "The design feels safe before it feels exciting.",
                "Some details are elegant but not especially memorable.",
            ],
            "suggestions": [
                "Keep the calm palette but add a sharper accent line.",
                "Push the directional graphics a little more to suggest speed.",
            ],
        }
    )

    assert sanitized["summary"] == "Passengers would likely read the texture as calm, legible, and intentionally seasonal."
    assert sanitized["quick_comment"] == "Looks reassuring overall, but one stronger accent would make it easier to remember."
    assert sanitized["strengths"][0] == "The cool palette feels steady and restful on longer trips."


def test_sanitize_engineering_assessment_preserves_summary_and_quick_comment() -> None:
    sanitized = review_module._sanitize_engineering_assessment(  # noqa: SLF001
        {
            "paint_volume_kg": 84.6,
            "color_zone_count": 3,
            "masking_steps": 2,
            "gradient_ratio_percent": 18.0,
            "labor_hours": 144,
            "process_steps": 5,
            "curve_conformance_score": 79,
            "material_cost_yuan": 28000,
            "labor_cost_yuan": 21000,
            "total_cost_yuan": 49000,
            "color_variance_risk": "LOW",
            "weather_durability": "A",
            "maintenance_cycle_years": 6,
            "summary": "  Process complexity stays under control, and the paint logic feels manufacturable without becoming bland.  ",
            "quick_comment": "  Feasible overall, but keep an eye on the gradient edge where masking tolerance could drift.  ",
        },
        120.0,
    )

    assert sanitized["summary"] == "Process complexity stays under control, and the paint logic feels manufacturable without becoming bland."
    assert sanitized["quick_comment"] == "Feasible overall, but keep an eye on the gradient edge where masking tolerance could drift."


def test_build_overall_narrative_prefers_human_summary_text() -> None:
    narrative = review_module._build_overall_narrative(  # noqa: SLF001
        engineering={
            "summary": "the coating path feels stable and the production effort stays in a comfortable range",
            "quick_comment": "keep watching the masking line near the nose",
        },
        passenger={
            "summary": "passengers would likely see the scheme as calm, premium, and easy to trust",
            "quick_comment": "it feels polished, but one accent could make it more memorable",
        },
        recommendation="recommended",
    )

    assert "move forward" in narrative
    assert "passenger side" in narrative
    assert "engineering side" in narrative
