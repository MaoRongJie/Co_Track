from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.intent_and_3d_generation_agent import (
    Stage1IntentAndThreeDGenerationAgent,
    Stage1RuntimeDependencyError,
    ThreeDModelGenerationPlan,
)
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.agents.providers.provider_protocols import ModelProviderNotConfiguredError
from app.agents.providers.three_d_generation_provider import ThreeDModelGenerationProvider
from app.api.deps import get_current_user
from app.db.models import MeetingSession, ModelAsset, ModelGenerationTask, SessionMember, User
from app.db.session import SessionLocal, get_db
from app.graph.engine import (
    get_openai_text_image_provider as _engine_get_openai_text_image_provider,
    get_stage1_intent_and_3d_generation_agent as _engine_get_stage1_intent_and_3d_generation_agent,
    get_three_d_model_generation_provider as _engine_get_three_d_model_generation_provider,
)
from app.model_processing import (
    ModelProcessingError,
    SUPPORTED_MODEL_SUFFIXES,
    create_original_upload_path,
    process_uploaded_model,
)
from app.model_runtime import (
    get_transient_task,
    next_transient_model_id,
    next_transient_task_id,
    save_transient_model,
    save_transient_task,
    update_transient_task,
    utcnow as runtime_utcnow,
)
from app.schemas.model import (
    ModelAssetOut,
    ModelGenerateRequest,
    ModelGenerateResponse,
    ModelLibraryResponse,
    ModelTaskOut,
    ModelUploadResponse,
)
from app.socket.server import emit_session_event
from app.stages.stage2_plan_3d_model import build_fallback_model_generation_plan, run_stage2_plan_3d_model
from app.workflow.controller import get_workflow_controller

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_host(db: Session, session_id: int, user_id: int) -> bool:
    return get_workflow_controller().is_host(db, session_id, user_id)


def _ensure_meeting(db: Session, session_id: int) -> MeetingSession:
    try:
        return get_workflow_controller().ensure_meeting(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc


def _should_persist_session_data(db: Session, session_id: int) -> bool:
    return get_workflow_controller().should_persist_session_data(db, session_id)


def _apply_effective_session_state(db: Session, meeting: MeetingSession) -> None:
    get_workflow_controller().apply_effective_session_state(db, meeting)


def _update_session_state(
    db: Session,
    meeting: MeetingSession,
    *,
    stage: str | None = None,
    product_category: str | None = None,
    product_profile: dict[str, Any] | None = None,
) -> None:
    get_workflow_controller().update_session_state(
        db,
        meeting,
        stage=stage,
        product_category=product_category,
        product_profile=product_profile,
    )


def _set_model_preparing_stage(meeting: MeetingSession) -> bool:
    if meeting.stage != "MODEL_PREPARING":
        meeting.stage = "MODEL_PREPARING"
        return True
    return False


def _task_payload(
    *,
    task_id: int,
    session_id: int,
    status_text: str,
    progress: int,
    pipeline_stage: str | None,
    progress_message: str | None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "session_id": session_id,
        "status": status_text,
        "progress": progress,
        "pipeline_stage": pipeline_stage,
        "progress_message": progress_message,
    }


async def _emit_task_status(
    *,
    session_id: int,
    task_id: int,
    status_text: str,
    progress: int,
    pipeline_stage: str | None,
    progress_message: str | None,
) -> None:
    await emit_session_event(
        "model:task_status",
        session_id,
        _task_payload(
            task_id=task_id,
            session_id=session_id,
            status_text=status_text,
            progress=progress,
            pipeline_stage=pipeline_stage,
            progress_message=progress_message,
        ),
    )


def _get_openai_text_image_provider() -> OpenAITextImageProvider:
    try:
        return _engine_get_openai_text_image_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _get_stage1_intent_and_3d_generation_agent(
    text_provider: OpenAITextImageProvider | None,
) -> Stage1IntentAndThreeDGenerationAgent:
    return _engine_get_stage1_intent_and_3d_generation_agent(text_provider)


def _get_three_d_model_provider() -> ThreeDModelGenerationProvider:
    return _engine_get_three_d_model_generation_provider()


def _fallback_generation_plan(
    *,
    product_category: str,
    product_profile: dict[str, Any],
    brief_json: dict[str, Any] | None,
) -> ThreeDModelGenerationPlan:
    return build_fallback_model_generation_plan(
        product_category=product_category,
        product_profile=product_profile,
        brief_json=brief_json,
    )


def _build_transient_model_payload(
    *,
    model_id: int,
    session_id: int,
    name: str,
    model_url: str,
    uv_template_url: str,
    surface_area_m2: float,
    paintable_uv_pixels: int,
    mapping_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    return ModelAssetOut(
        id=model_id,
        name=name,
        session_id=session_id,
        source_type="upload",
        precision_level="authoritative",
        license_scope="self_owned",
        export_glb_allowed=True,
        model_url=model_url,
        uv_template_url=uv_template_url,
        surface_area_m2=surface_area_m2,
        paintable_uv_pixels=paintable_uv_pixels,
        mapping_meta=mapping_meta,
        created_at=runtime_utcnow(),
    ).model_dump(mode="json")


def _sync_emit_status(
    *,
    session_id: int,
    task_id: int,
    status_text: str,
    progress: int,
    pipeline_stage: str | None,
    progress_message: str | None,
) -> None:
    asyncio.run(
        _emit_task_status(
            session_id=session_id,
            task_id=task_id,
            status_text=status_text,
            progress=progress,
            pipeline_stage=pipeline_stage,
            progress_message=progress_message,
        )
    )


def _update_persistent_upload_stage(
    task_id: int,
    pipeline_stage: str,
    progress: int,
    progress_message: str,
) -> None:
    with SessionLocal() as db:
        task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == task_id)).scalar_one_or_none()
        if task is None:
            return
        task.status = "running"
        task.progress = progress
        task.pipeline_stage = pipeline_stage
        task.progress_message = progress_message
        task.updated_at = _utcnow()
        session_id = task.session_id
        db.commit()

    _sync_emit_status(
        session_id=session_id,
        task_id=task_id,
        status_text="running",
        progress=progress,
        pipeline_stage=pipeline_stage,
        progress_message=progress_message,
    )


def _update_transient_upload_stage(
    task_id: int,
    pipeline_stage: str,
    progress: int,
    progress_message: str,
) -> None:
    payload = update_transient_task(
        task_id,
        status="running",
        progress=progress,
        pipeline_stage=pipeline_stage,
        progress_message=progress_message,
    )
    if payload is None:
        return
    _sync_emit_status(
        session_id=int(payload["session_id"]),
        task_id=task_id,
        status_text="running",
        progress=progress,
        pipeline_stage=pipeline_stage,
        progress_message=progress_message,
    )


def _run_persistent_upload_task(task_id: int) -> None:
    asyncio.run(_process_persistent_upload_task(task_id))


def _run_transient_upload_task(task_id: int) -> None:
    asyncio.run(_process_transient_upload_task(task_id))


async def _process_persistent_upload_task(task_id: int) -> None:
    with SessionLocal() as db:
        task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == task_id)).scalar_one_or_none()
        if task is None:
            return

        session_id = task.session_id
        source_path = Path(task.source_path or "")
        original_filename = task.original_filename or source_path.name
        product_category = task.product_category or "industrial_other"

    try:
        processed = await asyncio.to_thread(
            process_uploaded_model,
            source_path=source_path,
            session_id=session_id,
            model_id=task_id,
            product_category=product_category,
            original_filename=original_filename,
            stage_callback=lambda stage_name, progress, message: _update_persistent_upload_stage(
                task_id, stage_name, progress, message
            ),
        )
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc) if isinstance(exc, ModelProcessingError) else "Model processing failed."
        with SessionLocal() as db:
            task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == task_id)).scalar_one_or_none()
            if task is None:
                return
            task.status = "failed"
            task.progress = 100
            task.pipeline_stage = "failed"
            task.progress_message = error_message
            task.error_message = error_message
            task.error_detail = repr(exc)
            task.updated_at = _utcnow()
            db.commit()

        await _emit_task_status(
            session_id=session_id,
            task_id=task_id,
            status_text="failed",
            progress=100,
            pipeline_stage="failed",
            progress_message=error_message,
        )
        return

    with SessionLocal() as db:
        task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == task_id)).scalar_one()
        asset = ModelAsset(
            name=task.original_filename or f"Uploaded Model {task.id}",
            session_id=task.session_id,
            source_type="upload",
            precision_level="authoritative",
            license_scope="self_owned",
            export_glb_allowed=True,
            model_url=processed.model_url,
            uv_template_url=processed.uv_template_url,
            surface_area_m2=processed.surface_area_m2,
            paintable_uv_pixels=processed.paintable_uv_pixels,
            mapping_meta=processed.mapping_meta,
            created_by=task.created_by,
        )
        db.add(asset)
        db.flush()
        task.result_model_id = asset.id
        task.status = "ready"
        task.progress = 100
        task.pipeline_stage = "ready"
        task.progress_message = "UV template ready"
        task.error_message = None
        task.error_detail = None
        task.updated_at = _utcnow()
        db.commit()
        db.refresh(task)
        db.refresh(asset)
        model_payload = ModelAssetOut.model_validate(asset).model_dump(mode="json")

    await _emit_task_status(
        session_id=session_id,
        task_id=task_id,
        status_text="ready",
        progress=100,
        pipeline_stage="ready",
        progress_message="UV template ready",
    )
    await emit_session_event(
        "model:ready",
        session_id,
        {
            "task_id": task_id,
            "model": model_payload,
        },
    )


async def _process_transient_upload_task(task_id: int) -> None:
    task = get_transient_task(task_id)
    if task is None:
        return

    session_id = int(task["session_id"])
    source_path = Path(str(task["source_path"]))
    original_filename = str(task.get("original_filename") or source_path.name)
    product_category = str(task.get("product_category") or "industrial_other")
    model_id = int(task.get("model_id") or next_transient_model_id())

    try:
        processed = await asyncio.to_thread(
            process_uploaded_model,
            source_path=source_path,
            session_id=session_id,
            model_id=model_id,
            product_category=product_category,
            original_filename=original_filename,
            stage_callback=lambda stage_name, progress, message: _update_transient_upload_stage(
                task_id, stage_name, progress, message
            ),
        )
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc) if isinstance(exc, ModelProcessingError) else "Model processing failed."
        payload = update_transient_task(
            task_id,
            status="failed",
            progress=100,
            pipeline_stage="failed",
            progress_message=error_message,
            error_message=error_message,
            error_detail=repr(exc),
        )
        if payload is not None:
            await _emit_task_status(
                session_id=session_id,
                task_id=task_id,
                status_text="failed",
                progress=100,
                pipeline_stage="failed",
                progress_message=error_message,
            )
        return

    model_payload = _build_transient_model_payload(
        model_id=model_id,
        session_id=session_id,
        name=original_filename,
        model_url=processed.model_url,
        uv_template_url=processed.uv_template_url,
        surface_area_m2=processed.surface_area_m2,
        paintable_uv_pixels=processed.paintable_uv_pixels,
        mapping_meta=processed.mapping_meta,
    )
    save_transient_model(model_id, model_payload)
    update_transient_task(
        task_id,
        status="ready",
        progress=100,
        pipeline_stage="ready",
        progress_message="UV template ready",
        error_message=None,
        error_detail=None,
        result_model=model_payload,
    )

    await _emit_task_status(
        session_id=session_id,
        task_id=task_id,
        status_text="ready",
        progress=100,
        pipeline_stage="ready",
        progress_message="UV template ready",
    )
    await emit_session_event(
        "model:ready",
        session_id,
        {
            "task_id": task_id,
            "model": model_payload,
        },
    )


def _create_generated_asset(db: Session, task: ModelGenerationTask) -> ModelAsset:
    if task.result_model_id:
        existing = db.execute(select(ModelAsset).where(ModelAsset.id == task.result_model_id)).scalar_one_or_none()
        if existing is not None:
            return existing

    three_d_provider = _get_three_d_model_provider()
    plan = task.generation_plan_json if isinstance(task.generation_plan_json, dict) else {}
    artifact = three_d_provider.build_artifact(
        task_id=task.id,
        session_id=task.session_id,
        product_category=task.product_category or "industrial_other",
        generation_plan=plan,
    )

    task_suffix = str(task.id).zfill(6)
    asset = ModelAsset(
        name=f"Generated Model {task_suffix}",
        session_id=task.session_id,
        source_type="generate",
        precision_level=artifact.precision_level,
        license_scope=artifact.license_scope,
        export_glb_allowed=artifact.export_glb_allowed,
        model_url=artifact.model_url,
        uv_template_url=artifact.uv_template_url,
        surface_area_m2=artifact.surface_area_m2,
        paintable_uv_pixels=artifact.paintable_uv_pixels,
        mapping_meta=artifact.mapping_meta,
        created_by=task.created_by,
    )
    db.add(asset)
    db.flush()
    task.result_model_id = asset.id
    return asset


def _refresh_generate_task_state(db: Session, task: ModelGenerationTask) -> tuple[bool, bool]:
    now = _utcnow()
    changed = False
    became_ready = False

    if not task.created_at:
        task.created_at = now

    created_at = task.created_at
    if created_at.tzinfo is not None and created_at.utcoffset() is not None:
        now_for_diff = datetime.now(timezone.utc)
    else:
        now_for_diff = now
    elapsed = (now_for_diff - created_at).total_seconds()

    if task.status == "queued" and elapsed >= 1:
        task.status = "running"
        task.progress = 35
        task.pipeline_stage = "planning"
        task.progress_message = "Preparing generated model task"
        changed = True
    if task.status == "running" and elapsed >= 3:
        task.progress = 75
        task.pipeline_stage = "provider_generation"
        task.progress_message = "Waiting for generated model artifact"
        changed = True
    if task.status in {"queued", "running"} and elapsed >= 5:
        task.status = "ready"
        task.progress = 100
        task.pipeline_stage = "ready"
        task.progress_message = "Generated model ready"
        _create_generated_asset(db, task)
        changed = True
        became_ready = True

    task.updated_at = now
    return changed, became_ready


@router.get("/library", response_model=ModelLibraryResponse)
async def fetch_model_library(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModelLibraryResponse:
    items = db.execute(select(ModelAsset).where(ModelAsset.source_type == "library")).scalars().all()
    return ModelLibraryResponse(items=items)


@router.post("/upload", response_model=ModelUploadResponse)
async def upload_model(
    background_tasks: BackgroundTasks,
    session_id: int = Form(...),
    product_category: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ModelUploadResponse:
    if not _is_host(db, session_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can upload model")

    meeting = _ensure_meeting(db, session_id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)
    changed_stage = _set_model_preparing_stage(meeting)
    resolved_category = (product_category or meeting.product_category or "industrial_other").strip() or "industrial_other"
    _update_session_state(db, meeting, stage=meeting.stage, product_category=resolved_category)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    suffix = Path(file.filename or "uploaded_model.glb").suffix.lower() or ".glb"
    if suffix not in SUPPORTED_MODEL_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only GLB/GLTF uploads are supported in the current version.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    original_filename = file.filename or f"uploaded_model{suffix}"

    if should_persist:
        task = ModelGenerationTask(
            session_id=session_id,
            created_by=current_user.id,
            task_type="upload",
            status="queued",
            progress=0,
            pipeline_stage="queued",
            progress_message="Upload received",
            product_category=resolved_category,
            original_filename=original_filename,
        )
        db.add(task)
        db.flush()
        source_path = create_original_upload_path(session_id=session_id, task_id=task.id, suffix=suffix)
        source_path.write_bytes(content)
        task.source_path = str(source_path)
        db.commit()
        db.refresh(task)
        task_id = task.id
        background_tasks.add_task(_run_persistent_upload_task, task_id)
    else:
        task_id = next_transient_task_id()
        model_id = next_transient_model_id()
        source_path = create_original_upload_path(session_id=session_id, task_id=task_id, suffix=suffix)
        source_path.write_bytes(content)
        now = runtime_utcnow()
        save_transient_task(
            task_id,
            {
                "task_id": task_id,
                "session_id": session_id,
                "status": "queued",
                "progress": 0,
                "pipeline_stage": "queued",
                "progress_message": "Upload received",
                "error_message": None,
                "error_detail": None,
                "result_model": None,
                "product_category": resolved_category,
                "original_filename": original_filename,
                "source_path": str(source_path),
                "model_id": model_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        background_tasks.add_task(_run_transient_upload_task, task_id)

    if changed_stage:
        await emit_session_event("stage:changed", session_id, {"stage": meeting.stage})
    await _emit_task_status(
        session_id=session_id,
        task_id=task_id,
        status_text="queued",
        progress=0,
        pipeline_stage="queued",
        progress_message="Upload received",
    )

    return ModelUploadResponse(task_id=task_id, status="queued", progress=0, pipeline_stage="queued")


@router.post("/generate", response_model=ModelGenerateResponse)
async def generate_model(
    payload: ModelGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ModelGenerateResponse:
    if not _is_host(db, payload.session_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can generate model")

    meeting = _ensure_meeting(db, payload.session_id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)
    changed_stage = _set_model_preparing_stage(meeting)
    meeting.product_category = payload.product_category
    meeting.product_profile = payload.product_profile
    _update_session_state(
        db,
        meeting,
        stage=meeting.stage,
        product_category=payload.product_category,
        product_profile=payload.product_profile,
    )

    text_provider: OpenAITextImageProvider | None = None
    try:
        text_provider = _get_openai_text_image_provider()
    except HTTPException:
        text_provider = None

    plan: ThreeDModelGenerationPlan
    try:
        stage1_runtime = _get_stage1_intent_and_3d_generation_agent(text_provider)
        plan = await run_stage2_plan_3d_model(
            stage1_agent=stage1_runtime,
            product_category=payload.product_category,
            product_profile=payload.product_profile,
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            provider_availability=_get_three_d_model_provider().provider_availability,
        )
    except Stage1RuntimeDependencyError:
        plan = _fallback_generation_plan(
            product_category=payload.product_category,
            product_profile=payload.product_profile,
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )
    except Exception:
        plan = _fallback_generation_plan(
            product_category=payload.product_category,
            product_profile=payload.product_profile,
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )

    if not should_persist:
        transient_task_id = next_transient_task_id()
        task_abs = abs(transient_task_id)
        artifact = _get_three_d_model_provider().build_artifact(
            task_id=task_abs,
            session_id=payload.session_id,
            product_category=payload.product_category,
            generation_plan=plan.as_dict(),
        )
        transient_model = ModelAssetOut(
            id=next_transient_model_id(),
            name=f"Generated Model {str(task_abs).zfill(6)}",
            session_id=payload.session_id,
            source_type="generate",
            precision_level="approximate",
            license_scope=artifact.license_scope,
            export_glb_allowed=artifact.export_glb_allowed,
            model_url=artifact.model_url,
            uv_template_url=artifact.uv_template_url,
            surface_area_m2=artifact.surface_area_m2,
            paintable_uv_pixels=artifact.paintable_uv_pixels,
            mapping_meta=artifact.mapping_meta,
            created_at=runtime_utcnow(),
        ).model_dump(mode="json")
        now = runtime_utcnow()
        save_transient_model(int(transient_model["id"]), transient_model)
        save_transient_task(
            transient_task_id,
            {
                "task_id": transient_task_id,
                "session_id": payload.session_id,
                "status": "ready",
                "progress": 100,
                "pipeline_stage": "ready",
                "progress_message": "Generated model ready",
                "error_message": None,
                "result_model": transient_model,
                "created_at": now,
                "updated_at": now,
            },
        )

        if changed_stage:
            await emit_session_event("stage:changed", payload.session_id, {"stage": meeting.stage})
        await _emit_task_status(
            session_id=payload.session_id,
            task_id=transient_task_id,
            status_text="ready",
            progress=100,
            pipeline_stage="ready",
            progress_message="Generated model ready",
        )
        await emit_session_event(
            "model:ready",
            payload.session_id,
            {
                "task_id": transient_task_id,
                "model": transient_model,
            },
        )
        return ModelGenerateResponse(task_id=transient_task_id, status="ready", progress=100)

    task = ModelGenerationTask(
        session_id=payload.session_id,
        created_by=current_user.id,
        task_type="generate",
        status="queued",
        progress=0,
        pipeline_stage="queued",
        progress_message="Generation task queued",
        product_category=payload.product_category,
        product_profile=payload.product_profile,
        generation_plan_json=plan.as_dict(),
        provider_route=plan.provider_route,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    db.refresh(meeting)

    if changed_stage:
        await emit_session_event("stage:changed", payload.session_id, {"stage": meeting.stage})
    await _emit_task_status(
        session_id=payload.session_id,
        task_id=task.id,
        status_text=task.status,
        progress=task.progress,
        pipeline_stage=task.pipeline_stage,
        progress_message=task.progress_message,
    )

    return ModelGenerateResponse(task_id=task.id, status=task.status, progress=task.progress)


@router.get("/tasks/{task_id}", response_model=ModelTaskOut)
async def get_task_status(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ModelTaskOut:
    transient_task = get_transient_task(task_id)
    if transient_task is not None:
        session_id = int(transient_task["session_id"])
        member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.user_id == current_user.id,
            )
        ).scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this session")

        result_model = transient_task.get("result_model")
        return ModelTaskOut(
            task_id=int(transient_task["task_id"]),
            session_id=session_id,
            status=str(transient_task["status"]),  # type: ignore[arg-type]
            progress=int(transient_task["progress"]),
            pipeline_stage=transient_task.get("pipeline_stage"),
            progress_message=transient_task.get("progress_message"),
            error_message=transient_task.get("error_message"),
            result_model=ModelAssetOut.model_validate(result_model) if isinstance(result_model, dict) else None,
            created_at=transient_task["created_at"],  # type: ignore[arg-type]
            updated_at=transient_task.get("updated_at"),  # type: ignore[arg-type]
        )

    task = db.execute(select(ModelGenerationTask).where(ModelGenerationTask.id == task_id)).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == task.session_id,
            SessionMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this session")

    task_type = task.task_type or "generate"
    if task_type == "generate" and _should_persist_session_data(db, task.session_id):
        changed, became_ready = _refresh_generate_task_state(db, task)
        if changed:
            db.commit()
            db.refresh(task)

            await _emit_task_status(
                session_id=task.session_id,
                task_id=task.id,
                status_text=task.status,
                progress=task.progress,
                pipeline_stage=task.pipeline_stage,
                progress_message=task.progress_message,
            )
            if became_ready and task.result_model_id:
                model = db.execute(select(ModelAsset).where(ModelAsset.id == task.result_model_id)).scalar_one()
                await emit_session_event(
                    "model:ready",
                    task.session_id,
                    {
                        "task_id": task.id,
                        "model": ModelAssetOut.model_validate(model).model_dump(mode="json"),
                    },
                )

    result_model: ModelAsset | None = None
    if task.result_model_id:
        result_model = db.execute(select(ModelAsset).where(ModelAsset.id == task.result_model_id)).scalar_one_or_none()

    return ModelTaskOut(
        task_id=task.id,
        session_id=task.session_id,
        status=task.status,  # type: ignore[arg-type]
        progress=task.progress,
        pipeline_stage=task.pipeline_stage,
        progress_message=task.progress_message,
        error_message=task.error_message,
        result_model=ModelAssetOut.model_validate(result_model) if result_model else None,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
