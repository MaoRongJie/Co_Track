from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

class ParseBriefRequest(BaseModel):
    session_id: int
    design_goal: str = Field(min_length=4, max_length=4000)
    product_category: str = Field(min_length=2, max_length=50)


class ParseBriefResponse(BaseModel):
    session_id: int
    stage: str
    brief_json: dict[str, Any]


class AiGenerateImageRequest(BaseModel):
    session_id: int
    prompt: str = Field(min_length=1, max_length=4000)
    style_hint: str | None = Field(default=None, max_length=400)
    reference_images: list[str] = Field(default_factory=list, max_length=4)


class GeneratedImageOut(BaseModel):
    id: int
    session_id: int
    prompt: str
    style_hint: str | None = None
    revised_prompt: str | None = None
    image_url: str
    created_at: datetime


class GeneratedMediaAssetOut(BaseModel):
    id: int
    session_id: int
    result_id: str | None = None
    scheme_name: str | None = None
    media_type: Literal["image", "video"]
    media_url: str
    prompt: str
    provider: str
    model_name: str
    prediction_id: str | None = None
    source_image_url: str | None = None
    can_delete: bool = False
    created_at: datetime


class Stage4MediaListResponse(BaseModel):
    session_id: int
    result_id: str | None = None
    items: list[GeneratedMediaAssetOut] = Field(default_factory=list)


class AiGenerateImageResponse(BaseModel):
    items: list[GeneratedImageOut]


class TexturePatternGenerateRequest(BaseModel):
    session_id: int
    result_id: str = Field(min_length=1, max_length=120)
    preview_mode: Literal["meshy", "edited"] = "meshy"
    workspace_id: str = Field(min_length=1, max_length=240)
    pattern_prompt_text: str | None = Field(default=None, max_length=600)
    canvas_snapshot_data_url: str | None = None


class TexturePatternGenerateResponse(BaseModel):
    item: GeneratedImageOut
    analysis_summary: str
    dominant_colors: list[str] = Field(default_factory=list)
    source_result_id: str
    pattern_prompt_text: str | None = None


class Stage4SceneImageGenerateRequest(BaseModel):
    session_id: int
    result_id: str | None = Field(default=None, max_length=120)
    scheme_name: str | None = Field(default=None, max_length=240)
    screenshot_data_url: str = Field(min_length=32)
    image_prompt: str = Field(min_length=1, max_length=3000)


class Stage4SceneImageGenerateResponse(BaseModel):
    session_id: int
    result_id: str | None = None
    image_url: str
    image_prediction_id: str
    image_prompt: str
    created_image: GeneratedImageOut | None = None
    media_asset: GeneratedMediaAssetOut | None = None


class Stage4SceneVideoGenerateRequest(BaseModel):
    session_id: int
    result_id: str | None = Field(default=None, max_length=120)
    scheme_name: str | None = Field(default=None, max_length=240)
    image_url: str = Field(min_length=1)
    video_prompt: str = Field(min_length=1, max_length=3000)
    duration: int = Field(default=5, ge=4, le=15)
    resolution: Literal["480p", "720p", "1080p", "1080p-SR", "1440p-SR"] = "480p"
    generate_audio: bool = True


class Stage4SceneVideoGenerateResponse(BaseModel):
    session_id: int
    result_id: str | None = None
    video_url: str
    video_prediction_id: str
    video_prompt: str
    media_asset: GeneratedMediaAssetOut | None = None


class TexturePlanStateOut(BaseModel):
    session_id: int
    source_text: str = ""
    document_name: str | None = None
    document_excerpt: str = ""
    image_name: str | None = None
    image_content_keywords: list[str] = Field(default_factory=list)
    image_style_keywords: list[str] = Field(default_factory=list)
    selected_image_keywords: list[str] = Field(default_factory=list)
    brief_keywords: dict[str, Any] = Field(default_factory=dict)
    updated_at: str


class TexturePlanGenerateResponse(BaseModel):
    texture_plan: TexturePlanStateOut


class TexturePlanPatchRequest(BaseModel):
    session_id: int
    selected_image_keywords: list[str] | None = None
    clear_document: bool = False
    clear_image: bool = False


class EditedTextureVariantOut(BaseModel):
    model_url: str
    base_color_url: str
    applied_at: str


class PassengerScoreSetOut(BaseModel):
    first_impression: int
    safety_trust: int
    comfort_cleanliness: int
    perceived_quality: int
    speed_motion: int
    emotion_character: int


class PassengerAssessmentOut(BaseModel):
    scores: PassengerScoreSetOut
    overall_score: float
    summary: str
    quick_comment: str | None = None
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class EngineeringAssessmentOut(BaseModel):
    paint_volume_kg: float
    color_zone_count: int
    masking_steps: int
    gradient_ratio_percent: float
    labor_hours: int
    process_steps: int
    curve_conformance_score: int
    material_cost_yuan: int
    labor_cost_yuan: int
    total_cost_yuan: int
    color_variance_risk: Literal["HIGH", "MEDIUM", "LOW"]
    weather_durability: Literal["A", "B", "C"]
    maintenance_cycle_years: int
    summary: str | None = None
    quick_comment: str | None = None


class ReviewPersonaLabelsOut(BaseModel):
    passenger: str
    engineering: str


class Stage3RoleReviewOut(BaseModel):
    role_id: str
    role_type: Literal["passenger", "engineering", "custom"]
    role_name: str
    assessment: dict[str, Any]


class Stage3ReviewAssessmentOut(BaseModel):
    status: Literal["completed", "failed"] = "failed"
    engineering: EngineeringAssessmentOut | None = None
    passenger: PassengerAssessmentOut | None = None
    role_reviews: list[Stage3RoleReviewOut] = Field(default_factory=list)
    recommendation: Literal["highly_recommended", "recommended", "acceptable", "not_recommended"] | None = None
    overall_narrative: str | None = None
    source: Literal["llm", "failed"] = "failed"
    model_name: str | None = None
    error_message: str | None = None
    settings_revision_used: int | None = None
    persona_labels_used: ReviewPersonaLabelsOut | None = None


class SharedOriginOut(BaseModel):
    user_id: int
    user_name: str
    source_result_id: str


class SubmittedByOut(BaseModel):
    user_id: int
    user_name: str


class TexturedModelOut(BaseModel):
    result_id: str
    batch_id: str | None = None
    source_type: Literal["generated", "uploaded", "imported"] = "generated"
    created_at: str
    family_id: str
    parent_result_id: str | None = None
    scheme_id: str
    title: str = ""
    prompt_text: str = ""
    status: str = "pending"
    textured_model_url: str | None = None
    texture_maps: dict[str, str | None] | None = None
    edited_variant: EditedTextureVariantOut | None = None
    review_assessment: Stage3ReviewAssessmentOut | None = None
    meshy_task_id: str | None = None
    error_message: str | None = None
    shared_origin: SharedOriginOut | None = None
    submitted_by: SubmittedByOut | None = None


class ApplyTextureRequest(BaseModel):
    session_id: int


class RefreshTextureReviewRequest(BaseModel):
    session_id: int
    result_id: str | None = None


class ApplyTextureResponse(BaseModel):
    session_id: int
    models: list[TexturedModelOut]


class TextureModelsStateOut(BaseModel):
    session_id: int
    status: str = "idle"
    models: list[TexturedModelOut] = Field(default_factory=list)
    updated_at: str


class TextureModelsStartResponse(BaseModel):
    session_id: int
    status: str = "accepted"


class ShareTextureResultsRequest(BaseModel):
    session_id: int
    result_ids: list[str] = Field(default_factory=list, max_length=12)


class ShareTextureResultsResponse(BaseModel):
    session_id: int
    shared_result_ids: list[str] = Field(default_factory=list)
    updated_at: str


class SharedTextureResultsResponse(BaseModel):
    session_id: int
    source_user_id: int
    source_user_name: str
    models: list[TexturedModelOut] = Field(default_factory=list)
    updated_at: str


class ImportSharedTextureResultsRequest(BaseModel):
    session_id: int
    source_user_id: int
    result_ids: list[str] = Field(default_factory=list, max_length=12)


