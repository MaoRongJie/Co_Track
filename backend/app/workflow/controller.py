from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AiMessage, MeetingSession, ModelAsset, SessionMember
from app.model_runtime import get_transient_model
from app.graph.nodes import to_ai_message_out
from app.schemas.ai import AiMessageOut


class WorkflowController:
    def __init__(self) -> None:
        self._transient_session_state: dict[int, dict[str, object]] = {}

    def build_sse_event(self, event: str, payload: dict[str, object]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def should_persist_session_data(self, db: Session, session_id: int) -> bool:
        invite_code = db.execute(
            select(MeetingSession.invite_code).where(MeetingSession.id == session_id)
        ).scalar_one_or_none()
        # The shared default test session should now be resumable across reloads
        # and backend restarts, so every real session persists.
        if invite_code is None:
            return True
        return True

    def _snapshot_session_state(self, meeting: MeetingSession) -> dict[str, object]:
        return {
            "stage": meeting.stage,
            "design_goal_text": meeting.design_goal_text,
            "product_category": meeting.product_category,
            "product_profile": meeting.product_profile,
            "brief_json": meeting.brief_json,
            "texture_plan_json": meeting.texture_plan_json,
            "base_model_id": meeting.base_model_id,
            "model_locked_at": meeting.model_locked_at,
        }

    def get_effective_session_state(self, db: Session, meeting: MeetingSession) -> dict[str, object]:
        state = self._snapshot_session_state(meeting)
        if self.should_persist_session_data(db, meeting.id):
            return state

        override = self._transient_session_state.get(meeting.id)
        if override:
            state.update(override)
        return state

    def apply_effective_session_state(self, db: Session, meeting: MeetingSession) -> None:
        state = self.get_effective_session_state(db, meeting)
        meeting.stage = str(state["stage"])
        meeting.design_goal_text = state["design_goal_text"]  # type: ignore[assignment]
        meeting.product_category = state["product_category"]  # type: ignore[assignment]
        meeting.product_profile = state["product_profile"]  # type: ignore[assignment]
        meeting.brief_json = state["brief_json"]  # type: ignore[assignment]
        meeting.texture_plan_json = state["texture_plan_json"]  # type: ignore[assignment]
        meeting.base_model_id = state["base_model_id"]  # type: ignore[assignment]
        meeting.model_locked_at = state["model_locked_at"]  # type: ignore[assignment]

    def clear_transient_session_state(self, session_id: int) -> None:
        self._transient_session_state.pop(session_id, None)

    def update_session_state(
        self,
        db: Session,
        meeting: MeetingSession,
        *,
        stage: str | None = None,
        design_goal_text: str | None = None,
        product_category: str | None = None,
        product_profile: dict[str, object] | None = None,
        brief_json: dict[str, object] | None = None,
        texture_plan_json: dict[str, object] | None = None,
        base_model_id: int | None = None,
        model_locked_at: datetime | None = None,
    ) -> None:
        updates: dict[str, object | None] = {}
        if stage is not None:
            updates["stage"] = stage
        if design_goal_text is not None:
            updates["design_goal_text"] = design_goal_text
        if product_category is not None:
            updates["product_category"] = product_category
        if product_profile is not None:
            updates["product_profile"] = product_profile
        if brief_json is not None:
            updates["brief_json"] = brief_json
        if texture_plan_json is not None:
            updates["texture_plan_json"] = texture_plan_json
        if base_model_id is not None:
            updates["base_model_id"] = base_model_id
        if model_locked_at is not None:
            updates["model_locked_at"] = model_locked_at

        if self.should_persist_session_data(db, meeting.id):
            for key, value in updates.items():
                setattr(meeting, key, value)
            return

        state = self.get_effective_session_state(db, meeting)
        state.update(updates)
        self._transient_session_state[meeting.id] = state
        self.apply_effective_session_state(db, meeting)

    def is_host(self, db: Session, session_id: int, user_id: int) -> bool:
        member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == user_id,
                SessionMember.role == "host",
            )
        ).scalar_one_or_none()
        return member is not None

    def ensure_member(self, db: Session, session_id: int, user_id: int) -> MeetingSession:
        meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
        if meeting is None:
            raise ValueError("Session not found")

        member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == user_id,
            )
        ).scalar_one_or_none()
        if member is None:
            raise PermissionError("Not a member of this session")
        return meeting

    def ensure_meeting(self, db: Session, session_id: int) -> MeetingSession:
        meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
        if meeting is None:
            raise ValueError("Session not found")
        return meeting

    def save_ai_message(
        self,
        db: Session,
        *,
        session_id: int,
        user_id: int | None,
        role: str,
        mode: str | None,
        content: str,
        metadata_json: dict[str, object] | None = None,
    ) -> AiMessage:
        if not self.should_persist_session_data(db, session_id):
            row = AiMessage(
                session_id=session_id,
                user_id=user_id,
                role=role,
                mode=mode,
                content=content,
                metadata_json=metadata_json,
            )
            row.id = 0
            row.created_at = datetime.now(timezone.utc)
            return row

        row = AiMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            mode=mode,
            content=content,
            metadata_json=metadata_json,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def fetch_recent_history(self, db: Session, session_id: int, *, limit: int = 10) -> list[dict[str, str]]:
        if not self.should_persist_session_data(db, session_id):
            return []

        rows = db.execute(
            select(AiMessage).where(AiMessage.session_id == session_id).order_by(AiMessage.id.desc()).limit(limit)
        ).scalars().all()
        history: list[dict[str, str]] = []
        for row in reversed(rows):
            message_out = to_ai_message_out(row)
            history.append({"role": message_out.role, "content": message_out.content})
        return history

    def build_base_model_summary(self, db: Session, meeting: MeetingSession) -> str:
        if not meeting.base_model_id:
            return "none"
        model = db.execute(select(ModelAsset).where(ModelAsset.id == meeting.base_model_id)).scalar_one_or_none()
        if model is None:
            transient_model = get_transient_model(int(meeting.base_model_id))
            if transient_model is None:
                return "none"
            return (
                f"id={transient_model.get('id')}, source={transient_model.get('source_type')}, "
                f"precision={transient_model.get('precision_level')}, "
                f"surface_area_m2={float(transient_model.get('surface_area_m2', 0.0)):.2f}"
            )
        return (
            f"id={model.id}, source={model.source_type}, precision={model.precision_level}, "
            f"surface_area_m2={model.surface_area_m2:.2f}"
        )

    def to_message_out(self, item: AiMessage) -> AiMessageOut:
        return to_ai_message_out(item)


_WORKFLOW_CONTROLLER = WorkflowController()


def get_workflow_controller() -> WorkflowController:
    return _WORKFLOW_CONTROLLER
