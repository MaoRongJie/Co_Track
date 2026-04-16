from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ModelSourceType = Literal["upload", "library", "generate"]
PrecisionLevel = Literal["authoritative", "standard", "approximate"]
LicenseScope = Literal["self_owned", "internal", "external_restricted"]
TaskStatus = Literal["queued", "running", "ready", "failed"]


class ModelAssetOut(BaseModel):
    id: int
    name: str
    session_id: int | None
    source_type: ModelSourceType
    precision_level: PrecisionLevel
    license_scope: LicenseScope
    export_glb_allowed: bool
    model_url: str
    uv_template_url: str
    surface_area_m2: float
    paintable_uv_pixels: int
    mapping_meta: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ModelLibraryResponse(BaseModel):
    items: list[ModelAssetOut]


class ModelUploadResponse(BaseModel):
    task_id: int
    status: TaskStatus
    progress: int
    pipeline_stage: str | None = None


class ModelGenerateRequest(BaseModel):
    session_id: int
    product_category: str = Field(min_length=2, max_length=50)
    product_profile: dict[str, Any] = Field(default_factory=dict)


class ModelGenerateResponse(BaseModel):
    task_id: int
    status: TaskStatus
    progress: int


class ModelTaskOut(BaseModel):
    task_id: int
    session_id: int
    status: TaskStatus
    progress: int
    pipeline_stage: str | None = None
    progress_message: str | None = None
    error_message: str | None = None
    result_model: ModelAssetOut | None = None
    created_at: datetime
    updated_at: datetime | None = None

