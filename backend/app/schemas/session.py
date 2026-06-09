from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


MeetingRole = Literal["host", "designer", "observer"]
MeetingSettingsSectionId = Literal[
    "review_roles",
    "passenger_evaluation",
    "engineering_evaluation",
    "collaboration_rules",
    "meeting_workflow",
    "export_preferences",
]


class CreateSessionRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class JoinSessionRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=8)
    role: MeetingRole = "designer"


class PassengerEvaluationConfigOut(BaseModel):
    display_name: str
    identity_summary: str
    preference_tags: list[str] = Field(default_factory=list)
    dislike_tags: list[str] = Field(default_factory=list)
    focus_points: list[str] = Field(default_factory=list)


class EngineeringEvaluationConfigOut(BaseModel):
    display_name: str
    identity_summary: str
    priority_tags: list[str] = Field(default_factory=list)
    risk_focus: list[str] = Field(default_factory=list)
    focus_points: list[str] = Field(default_factory=list)


class ReviewPersonaRoleOut(BaseModel):
    id: str
    type: Literal["passenger", "engineering", "custom"]
    enabled: bool = True
    display_name: str
    identity_summary: str
    role_prompt: str | None = None
    focus_points: list[str] = Field(default_factory=list)
    preference_tags: list[str] = Field(default_factory=list)
    dislike_tags: list[str] = Field(default_factory=list)
    priority_tags: list[str] = Field(default_factory=list)
    risk_focus: list[str] = Field(default_factory=list)


class ReviewPersonasOut(BaseModel):
    passenger: PassengerEvaluationConfigOut
    engineering: EngineeringEvaluationConfigOut
    roles: list[ReviewPersonaRoleOut] = Field(default_factory=list)


class SessionSettingsOut(BaseModel):
    revision: int = 1
    updated_at: str | None = None
    updated_by_user_id: int | None = None
    review_personas: ReviewPersonasOut


class SessionSettingsPermissionsOut(BaseModel):
    role: MeetingRole
    can_edit: bool = False


class MeetingSettingsSectionOut(BaseModel):
    id: MeetingSettingsSectionId
    label: str
    description: str
    enabled: bool
    badge: str | None = None


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
    session_settings: SessionSettingsOut | None = None
    settings_permissions: SessionSettingsPermissionsOut | None = None
    settings_sections: list[MeetingSettingsSectionOut] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class SessionJoinResponse(BaseModel):
    session: SessionOut
    role: MeetingRole


class SessionMemberDirectoryEntryOut(BaseModel):
    user_id: int
    name: str
    role: MeetingRole
    joined_at: datetime
    online: bool = False
    public_share_count: int = 0
    can_live_sync: bool = False
    shared_result_ids: list[str] = Field(default_factory=list)


class SessionMembersResponse(BaseModel):
    session_id: int
    members: list[SessionMemberDirectoryEntryOut] = Field(default_factory=list)


class PassengerEvaluationConfigPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    identity_summary: str | None = Field(default=None, max_length=320)
    preference_tags: list[str] | None = Field(default=None, max_length=8)
    dislike_tags: list[str] | None = Field(default=None, max_length=8)
    focus_points: list[str] | None = Field(default=None, max_length=8)


class EngineeringEvaluationConfigPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    identity_summary: str | None = Field(default=None, max_length=320)
    priority_tags: list[str] | None = Field(default=None, max_length=8)
    risk_focus: list[str] | None = Field(default=None, max_length=8)
    focus_points: list[str] | None = Field(default=None, max_length=8)


class ReviewPersonaRolePatch(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["passenger", "engineering", "custom"]
    enabled: bool = True
    display_name: str = Field(min_length=1, max_length=60)
    identity_summary: str = Field(min_length=1, max_length=360)
    role_prompt: str | None = Field(default=None, max_length=1200)
    focus_points: list[str] = Field(default_factory=list, max_length=8)
    preference_tags: list[str] = Field(default_factory=list, max_length=8)
    dislike_tags: list[str] = Field(default_factory=list, max_length=8)
    priority_tags: list[str] = Field(default_factory=list, max_length=8)
    risk_focus: list[str] = Field(default_factory=list, max_length=8)


class ReviewPersonasPatchRequest(BaseModel):
    passenger: PassengerEvaluationConfigPatch | None = None
    engineering: EngineeringEvaluationConfigPatch | None = None
    roles: list[ReviewPersonaRolePatch] | None = Field(default=None, max_length=8)


class SessionSettingsPatchRequest(BaseModel):
    review_personas: ReviewPersonasPatchRequest


class SessionSettingsStateOut(BaseModel):
    session_id: int
    session_settings: SessionSettingsOut
    settings_permissions: SessionSettingsPermissionsOut
    sections: list[MeetingSettingsSectionOut] = Field(default_factory=list)


class BaseModelSelectRequest(BaseModel):
    base_model_id: int


class SessionBaseModelOut(BaseModel):
    session_id: int
    base_model_id: int | None
    model_locked_at: datetime | None
