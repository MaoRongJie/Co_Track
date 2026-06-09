from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list["SessionMember"]] = relationship(back_populates="user")


class MeetingSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(30), default="LOBBY")
    design_goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    product_profile: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    brief_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    texture_plan_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    session_settings_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    stage3_shared_refs_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    base_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_assets.id"), nullable=True)
    model_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["SessionMember"]] = relationship(back_populates="session")
    base_model: Mapped["ModelAsset | None"] = relationship(foreign_keys=[base_model_id])


class SessionMember(Base):
    __tablename__ = "session_members"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_session_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="designer")
    workspace_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    shared_result_ids_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[MeetingSession] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class ModelAsset(Base):
    __tablename__ = "model_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    precision_level: Mapped[str] = mapped_column(String(20), nullable=False)
    license_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    export_glb_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_url: Mapped[str] = mapped_column(String(500), nullable=False)
    uv_template_url: Mapped[str] = mapped_column(String(500), nullable=False)
    surface_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    paintable_uv_pixels: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_meta: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelGenerationTask(Base):
    __tablename__ = "model_generation_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    task_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pipeline_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    product_profile: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    generation_plan_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    provider_route: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_assets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    style_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str] = mapped_column(String(4000), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GeneratedMediaAsset(Base):
    __tablename__ = "generated_media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    result_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    scheme_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    media_url: Mapped[str] = mapped_column(String(4000), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prediction_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_image_url: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

