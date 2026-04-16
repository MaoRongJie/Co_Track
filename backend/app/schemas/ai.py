from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ChatMode = Literal["creative", "image"]
ChatRole = Literal["user", "assistant", "system"]


class ParseBriefRequest(BaseModel):
    session_id: int
    design_goal: str = Field(min_length=4, max_length=4000)
    product_category: str = Field(min_length=2, max_length=50)


class ParseBriefResponse(BaseModel):
    session_id: int
    stage: str
    brief_json: dict[str, Any]


class AiChatRequest(BaseModel):
    session_id: int
    message: str = Field(min_length=1, max_length=4000)
    mode: ChatMode = "creative"
    stream: bool = True


class AiMessageOut(BaseModel):
    id: int
    session_id: int
    user_id: int | None = None
    role: ChatRole
    mode: ChatMode | None = None
    content: str
    created_at: datetime


class AiChatHistoryResponse(BaseModel):
    items: list[AiMessageOut]
    has_more: bool = False


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


class AiGenerateImageResponse(BaseModel):
    items: list[GeneratedImageOut]


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


class TexturedModelOut(BaseModel):
    scheme_id: str
    title: str = ""
    prompt_text: str = ""
    status: str = "pending"
    textured_model_url: str | None = None
    texture_maps: dict[str, str | None] | None = None
    edited_variant: EditedTextureVariantOut | None = None
    meshy_task_id: str | None = None
    error_message: str | None = None


class ApplyTextureRequest(BaseModel):
    session_id: int


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


