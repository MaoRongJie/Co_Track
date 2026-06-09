import random
from datetime import datetime, timezone
from string import digits

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import MeetingSession, ModelAsset, SessionMember, User
from app.db.session import get_db
from app.model_runtime import get_transient_model
from app.session_settings import (
    build_settings_permissions,
    build_settings_sections,
    normalize_session_settings,
    patch_session_settings,
)
from app.schemas.model import ModelAssetOut
from app.schemas.session import (
    BaseModelSelectRequest,
    CreateSessionRequest,
    JoinSessionRequest,
    SessionSettingsPatchRequest,
    SessionBaseModelOut,
    SessionJoinResponse,
    SessionMemberDirectoryEntryOut,
    SessionMembersResponse,
    SessionSettingsStateOut,
    SessionOut,
)
from app.socket.server import emit_session_event, hub
from app.texture_planning import normalize_texture_plan_state
from app.workflow.controller import get_workflow_controller

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_invite_code() -> str:
    return ''.join(random.choice(digits) for _ in range(6))


def _should_persist_session_data(db: Session, session_id: int) -> bool:
    return get_workflow_controller().should_persist_session_data(db, session_id)


def _apply_effective_session_state(db: Session, meeting: MeetingSession) -> None:
    get_workflow_controller().apply_effective_session_state(db, meeting)


def _update_session_state(
    db: Session,
    meeting: MeetingSession,
    *,
    stage: str | None = None,
    base_model_id: int | None = None,
    model_locked_at: datetime | None = None,
    session_settings_json: dict[str, object] | None = None,
    stage3_shared_refs_json: list[dict[str, object]] | None = None,
) -> None:
    get_workflow_controller().update_session_state(
        db,
        meeting,
        stage=stage,
        base_model_id=base_model_id,
        model_locked_at=model_locked_at,
        session_settings_json=session_settings_json,
        stage3_shared_refs_json=stage3_shared_refs_json,
    )


def _require_host(db: Session, session_id: int, user_id: int) -> None:
    host_member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == user_id,
            SessionMember.role == 'host',
        )
    ).scalar_one_or_none()
    if host_member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only host can perform this action')


def _read_member_workspace(meeting: MeetingSession, member: SessionMember) -> dict[str, object] | None:
    if isinstance(member.workspace_json, dict):
        return dict(member.workspace_json)
    if member.role == 'host' and isinstance(meeting.texture_plan_json, dict):
        return dict(meeting.texture_plan_json)
    return None


def _serialize_session_out(meeting: MeetingSession, role: str) -> SessionOut:
    session_settings = normalize_session_settings(
        meeting.session_settings_json,
        fallback_updated_by_user_id=meeting.creator_id,
    )
    return SessionOut(
        id=meeting.id,
        name=meeting.name,
        invite_code=meeting.invite_code,
        stage=meeting.stage,
        design_goal_text=meeting.design_goal_text,
        product_category=meeting.product_category,
        product_profile=meeting.product_profile,
        brief_json=meeting.brief_json,
        base_model_id=meeting.base_model_id,
        model_locked_at=meeting.model_locked_at,
        session_settings=session_settings,
        settings_permissions=build_settings_permissions(role),
        settings_sections=build_settings_sections(),
        created_at=meeting.created_at,
    )


def _serialize_session_settings_state(
    *,
    meeting: MeetingSession,
    role: str,
) -> SessionSettingsStateOut:
    return SessionSettingsStateOut(
        session_id=meeting.id,
        session_settings=normalize_session_settings(
            meeting.session_settings_json,
            fallback_updated_by_user_id=meeting.creator_id,
        ),
        settings_permissions=build_settings_permissions(role),
        sections=build_settings_sections(),
    )


def _build_stage3_shared_refs(db: Session, meeting: MeetingSession) -> list[dict[str, object]]:
    members = db.execute(
        select(SessionMember)
        .where(SessionMember.session_id == meeting.id)
        .order_by(SessionMember.joined_at.asc(), SessionMember.id.asc())
    ).scalars().all()

    shared_refs: list[dict[str, object]] = []
    display_order = 0
    shared_at = _utcnow().isoformat()
    for member in members:
        workspace = normalize_texture_plan_state(
            _read_member_workspace(meeting, member),
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )
        completed_result_ids = {
            str(item.get('result_id') or '').strip()
            for item in workspace.get('textured_models', [])
            if str(item.get('status') or '').strip().lower() == 'completed'
        }
        for raw_result_id in member.shared_result_ids_json or []:
            result_id = str(raw_result_id or '').strip()
            if not result_id or result_id not in completed_result_ids:
                continue
            shared_refs.append(
                {
                    'owner_user_id': member.user_id,
                    'result_id': result_id,
                    'display_order': display_order,
                    'shared_at': shared_at,
                }
            )
            display_order += 1
    return shared_refs


@router.post('', response_model=SessionOut)
def create_session(
    payload: CreateSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionOut:
    invite_code = _gen_invite_code()
    while db.execute(select(MeetingSession).where(MeetingSession.invite_code == invite_code)).scalar_one_or_none():
        invite_code = _gen_invite_code()

    meeting = MeetingSession(
        name=payload.name.strip(),
        invite_code=invite_code,
        creator_id=current_user.id,
        stage='LOBBY',
        product_profile={},
    )
    db.add(meeting)
    db.flush()

    db.add(SessionMember(session_id=meeting.id, user_id=current_user.id, role='host'))
    db.commit()
    db.refresh(meeting)
    return _serialize_session_out(meeting, 'host')


@router.get('/{session_id}', response_model=SessionOut)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionOut:
    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not a member of this session')

    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)
    return _serialize_session_out(meeting, member.role)


@router.get('/{session_id}/settings', response_model=SessionSettingsStateOut)
def get_session_settings(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionSettingsStateOut:
    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not a member of this session')

    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)
    return _serialize_session_settings_state(meeting=meeting, role=member.role)


@router.patch('/{session_id}/settings', response_model=SessionSettingsStateOut)
def patch_meeting_settings(
    session_id: int,
    payload: SessionSettingsPatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionSettingsStateOut:
    _require_host(db, session_id, current_user.id)
    should_persist = _should_persist_session_data(db, session_id)

    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)

    try:
        next_settings = patch_session_settings(
            meeting.session_settings_json,
            payload.model_dump(mode='json', exclude_none=True),
            updated_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _update_session_state(db, meeting, session_settings_json=next_settings)

    if should_persist:
        db.commit()
        db.refresh(meeting)

    return _serialize_session_settings_state(meeting=meeting, role='host')


@router.post('/join', response_model=SessionJoinResponse)
def join_session_by_invite(
    payload: JoinSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionJoinResponse:
    meeting = db.execute(
        select(MeetingSession).where(MeetingSession.invite_code == payload.invite_code.strip())
    ).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Invite code not found')

    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == meeting.id,
            SessionMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if member is None:
        member = SessionMember(
            session_id=meeting.id,
            user_id=current_user.id,
            role=payload.role,
        )
        db.add(member)
    else:
        member.role = payload.role

    db.commit()
    db.refresh(meeting)
    return SessionJoinResponse(session=_serialize_session_out(meeting, member.role), role=member.role)


@router.get('/{session_id}/members', response_model=SessionMembersResponse)
def get_session_members(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionMembersResponse:
    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not a member of this session')

    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)

    members = db.execute(
        select(SessionMember, User)
        .join(User, User.id == SessionMember.user_id)
        .where(SessionMember.session_id == session_id)
        .order_by(SessionMember.joined_at.asc(), SessionMember.id.asc())
    ).all()

    entries: list[SessionMemberDirectoryEntryOut] = []
    for session_member, user in members:
        workspace = normalize_texture_plan_state(
            _read_member_workspace(meeting, session_member),
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )
        shared_ids = {
            str(item).strip()
            for item in (session_member.shared_result_ids_json or [])
            if str(item).strip()
        }
        ordered_shared_ids = [
            str(item).strip()
            for item in (session_member.shared_result_ids_json or [])
            if str(item).strip()
        ]
        valid_shared_ids = {
            str(item.get('result_id') or '').strip()
            for item in workspace.get('textured_models', [])
            if str(item.get('status') or '').strip().lower() == 'completed'
        }
        ordered_shared_ids = [item for item in ordered_shared_ids if item in valid_shared_ids]
        public_share_count = sum(
            1
            for item in workspace.get('textured_models', [])
            if str(item.get('result_id') or '').strip() in shared_ids
            and str(item.get('status') or '').strip().lower() == 'completed'
        )
        entries.append(
            SessionMemberDirectoryEntryOut(
                user_id=session_member.user_id,
                name=user.name,
                role=session_member.role,  # type: ignore[arg-type]
                joined_at=session_member.joined_at,
                online=hub.get_peer(session_id, session_member.user_id) is not None,
                public_share_count=public_share_count,
                can_live_sync=public_share_count > 0,
                shared_result_ids=ordered_shared_ids,
            )
        )

    return SessionMembersResponse(session_id=session_id, members=entries)


@router.get('/{session_id}/base-model')
def get_session_base_model(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not a member of this session')

    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)

    model = None
    transient_model = None
    if meeting.base_model_id:
        model = db.execute(select(ModelAsset).where(ModelAsset.id == meeting.base_model_id)).scalar_one_or_none()
        if model is None:
            transient_model = get_transient_model(int(meeting.base_model_id))

    return {
        'session_id': session_id,
        'base_model_id': meeting.base_model_id,
        'model_locked_at': meeting.model_locked_at,
        'base_model': (
            ModelAssetOut.model_validate(model).model_dump(mode='json')
            if model
            else ModelAssetOut.model_validate(transient_model).model_dump(mode='json')
            if transient_model
            else None
        ),
    }


@router.post('/{session_id}/base-model/select', response_model=SessionBaseModelOut)
async def select_base_model(
    session_id: int,
    payload: BaseModelSelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionBaseModelOut:
    _require_host(db, session_id, current_user.id)
    should_persist = _should_persist_session_data(db, session_id)

    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')

    model = db.execute(select(ModelAsset).where(ModelAsset.id == payload.base_model_id)).scalar_one_or_none()
    transient_model = get_transient_model(payload.base_model_id) if model is None else None
    if model is not None and model.session_id not in (None, session_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Model does not belong to this session')
    if model is None and transient_model is None:
        detail = 'Transient model not found' if payload.base_model_id < 0 else 'Model not found'
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    if model is not None:
        selected_model_id = model.id
        selected_model_payload = ModelAssetOut.model_validate(model).model_dump(mode='json')
    else:
        selected_model_id = payload.base_model_id
        selected_model_payload = ModelAssetOut.model_validate(transient_model).model_dump(mode='json')

    next_stage = meeting.stage
    if next_stage == 'LOBBY':
        next_stage = 'BRIEFING'
    if next_stage == 'BRIEFING':
        next_stage = 'MODEL_PREPARING'
    locked_at = _utcnow()
    _update_session_state(
        db,
        meeting,
        stage=next_stage,
        base_model_id=selected_model_id,
        model_locked_at=locked_at,
    )

    if should_persist:
        db.commit()
        db.refresh(meeting)

    await emit_session_event(
        'model:locked',
        session_id,
        {
            'base_model_id': selected_model_id,
            'model_locked_at': meeting.model_locked_at.isoformat() if meeting.model_locked_at else None,
            'model': selected_model_payload,
        },
    )
    await emit_session_event('stage:changed', session_id, {'stage': meeting.stage})

    return SessionBaseModelOut(
        session_id=session_id,
        base_model_id=meeting.base_model_id,
        model_locked_at=meeting.model_locked_at,
    )


@router.post('/{session_id}/advance', response_model=SessionOut)
async def advance_stage(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionOut:
    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    _require_host(db, session_id, current_user.id)

    ordered_stages = ['LOBBY', 'BRIEFING', 'MODEL_PREPARING', 'DESIGNING', 'COLLECTING', 'REVIEWING', 'PREVIEWING']
    if meeting.stage not in ordered_stages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Unknown stage: {meeting.stage}')

    idx = ordered_stages.index(meeting.stage)
    next_stage = ordered_stages[min(idx + 1, len(ordered_stages) - 1)]

    if meeting.stage == 'MODEL_PREPARING' and next_stage == 'DESIGNING' and not meeting.model_locked_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Please lock base model before entering DESIGNING stage',
        )

    if meeting.stage == 'DESIGNING' and next_stage == 'COLLECTING':
        stage3_shared_refs = _build_stage3_shared_refs(db, meeting)
        if not stage3_shared_refs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Share at least one completed textured result before entering Stage 3.',
            )
        _update_session_state(db, meeting, stage3_shared_refs_json=stage3_shared_refs)

    _update_session_state(db, meeting, stage=next_stage)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    await emit_session_event('stage:changed', session_id, {'stage': meeting.stage})
    return _serialize_session_out(meeting, 'host')


@router.post('/{session_id}/revert', response_model=SessionOut)
async def revert_stage(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionOut:
    """Allow host to revert session stage backwards (e.g. COLLECTING/REVIEWING -> DESIGNING)."""
    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    _require_host(db, session_id, current_user.id)

    revert_map = {
        'DESIGNING': 'MODEL_PREPARING',
        'COLLECTING': 'DESIGNING',
        'REVIEWING': 'DESIGNING',
        'PREVIEWING': 'REVIEWING',
    }
    target_stage = revert_map.get(meeting.stage)
    if target_stage is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Cannot revert from stage: {meeting.stage}',
        )

    _update_session_state(db, meeting, stage=target_stage)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    await emit_session_event('stage:changed', session_id, {'stage': meeting.stage})
    return _serialize_session_out(meeting, 'host')


