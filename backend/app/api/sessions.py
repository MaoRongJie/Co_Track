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
from app.schemas.model import ModelAssetOut
from app.schemas.session import (
    BaseModelSelectRequest,
    CreateSessionRequest,
    JoinSessionRequest,
    SessionBaseModelOut,
    SessionJoinResponse,
    SessionOut,
)
from app.socket.server import emit_session_event
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
) -> None:
    get_workflow_controller().update_session_state(
        db,
        meeting,
        stage=stage,
        base_model_id=base_model_id,
        model_locked_at=model_locked_at,
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
    return meeting


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
    return meeting


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
    return SessionJoinResponse(session=meeting, role=member.role)


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
    if should_persist and model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Model not found')
    if model is not None and model.session_id not in (None, session_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Model does not belong to this session')
    if model is None and transient_model is None and payload.base_model_id < 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Transient model not found')

    selected_model_id = model.id if model is not None else payload.base_model_id
    selected_model_payload = (
        ModelAssetOut.model_validate(model).model_dump(mode='json')
        if model is not None
        else ModelAssetOut.model_validate(transient_model).model_dump(mode='json')
        if transient_model is not None
        else ModelAssetOut(
            id=selected_model_id,
            name=f'Transient Base Model {selected_model_id}',
            session_id=session_id,
            source_type='generate',
            precision_level='authoritative',
            license_scope='self_owned',
            export_glb_allowed=True,
            model_url=f'/files/models/transient_base_{session_id}_{selected_model_id}.glb',
            uv_template_url=f'/files/uv/transient_base_{session_id}_{selected_model_id}.png',
            surface_area_m2=312.4,
            paintable_uv_pixels=4096 * 2048,
            mapping_meta=None,
            created_at=_utcnow(),
        ).model_dump(mode='json')
    )

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

    _update_session_state(db, meeting, stage=next_stage)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    await emit_session_event('stage:changed', session_id, {'stage': meeting.stage})
    return meeting


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
    return meeting


