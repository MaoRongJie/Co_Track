from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


MeetingRole = Literal["host", "designer", "observer"]


class CreateSessionRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class JoinSessionRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=8)
    role: MeetingRole = "designer"


class SessionOut(BaseModel):
    id: int
    name: str
    invite_code: str
    stage: str
    design_goal_text: str | None = None
    product_category: str | None = None
    product_profile: dict[str, Any] | None = None
    brief_json: dict[str, Any] | None = None
    base_model_id: int | None = None
    model_locked_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class SessionJoinResponse(BaseModel):
    session: SessionOut
    role: MeetingRole


class BaseModelSelectRequest(BaseModel):
    base_model_id: int


class SessionBaseModelOut(BaseModel):
    session_id: int
    base_model_id: int | None
    model_locked_at: datetime | None

