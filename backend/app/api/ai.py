from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.creative_dialogue_and_image_agent import (
    AgentRuntimeDependencyError,
    CreativeDialogueAndImageAgent,
    SessionAiContext,
    TexturePlanningContext,
)
from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent, Stage1RuntimeDependencyError
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.agents.providers.provider_protocols import ModelProviderError, ModelProviderNotConfiguredError
from app.api.deps import get_current_user
from app.db.models import AiMessage, GeneratedImage, MeetingSession, ModelAsset, ModelGenerationTask, User
from app.db.session import SessionLocal, get_db
from app.document_parsing import DocumentParseError, detect_image_mime_type, extract_document_text
from app.graph.engine import (
    get_creative_dialogue_and_image_agent as _engine_get_creative_dialogue_and_image_agent,
    get_meshy_texture_provider as _engine_get_meshy_texture_provider,
    get_openai_text_image_provider as _engine_get_openai_text_image_provider,
    get_stage1_intent_and_3d_generation_agent as _engine_get_stage1_intent_and_3d_generation_agent,
)
from app.model_texturing import EditedTextureApplicationResult, ModelTexturingError, apply_edited_texture_to_model
from app.schemas.ai import (
    AiChatHistoryResponse,
    AiChatRequest,
    AiGenerateImageRequest,
    AiGenerateImageResponse,
    AiMessageOut,
    ApplyTextureRequest,
    ApplyTextureResponse,
    EditedTextureVariantOut,
    GeneratedImageOut,
    ParseBriefRequest,
    ParseBriefResponse,
    TexturedModelOut,
    TextureModelsStartResponse,
    TextureModelsStateOut,
    TexturePlanGenerateResponse,
    TexturePlanPatchRequest,
    TexturePlanStateOut,
)
from app.stages.stage1_extract_concept import build_fallback_brief, run_stage1_extract_concept
from app.stages.stage3_generate_creative_reply import run_stage3_generate_creative_reply
from app.stages.stage4_generate_image_assets import run_stage4_generate_image_assets
from app.socket.server import emit_session_event
from app.texture_planning import (
    build_document_excerpt,
    normalize_texture_plan_state,
    patch_texture_plan_state,
    utcnow_iso,
)
from app.model_runtime import get_transient_model
from app.workflow.controller import get_workflow_controller

router = APIRouter()


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return get_workflow_controller().build_sse_event(event, payload)


def _is_host(db: Session, session_id: int, user_id: int) -> bool:
    return get_workflow_controller().is_host(db, session_id, user_id)


def _ensure_member(db: Session, session_id: int, user_id: int) -> MeetingSession:
    try:
        return get_workflow_controller().ensure_member(db, session_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this session") from exc


def _parse_brief_fallback(goal: str, category: str) -> dict[str, object]:
    return build_fallback_brief(goal, category)


def get_creative_dialogue_and_image_agent() -> CreativeDialogueAndImageAgent:
    return _engine_get_creative_dialogue_and_image_agent()


def get_stage1_intent_and_3d_generation_agent(text_provider: OpenAITextImageProvider | None) -> Stage1IntentAndThreeDGenerationAgent:
    return _engine_get_stage1_intent_and_3d_generation_agent(text_provider)


def get_openai_text_image_provider() -> OpenAITextImageProvider:
    return _engine_get_openai_text_image_provider()


# Backward-compatible accessors.
def get_agent_runtime() -> CreativeDialogueAndImageAgent:
    return get_creative_dialogue_and_image_agent()


def get_stage1_runtime(text_provider: OpenAITextImageProvider | None) -> Stage1IntentAndThreeDGenerationAgent:
    return get_stage1_intent_and_3d_generation_agent(text_provider)


def get_openai_provider() -> OpenAITextImageProvider:
    return get_openai_text_image_provider()


def _to_ai_message_out(item: AiMessage) -> AiMessageOut:
    return get_workflow_controller().to_message_out(item)


def _fetch_recent_history(db: Session, session_id: int, *, limit: int = 10) -> list[dict[str, str]]:
    return get_workflow_controller().fetch_recent_history(db, session_id, limit=limit)


def _build_base_model_summary(db: Session, meeting: MeetingSession) -> str:
    return get_workflow_controller().build_base_model_summary(db, meeting)


def _should_persist_session_data(db: Session, session_id: int) -> bool:
    return get_workflow_controller().should_persist_session_data(db, session_id)


def _apply_effective_session_state(db: Session, meeting: MeetingSession) -> None:
    get_workflow_controller().apply_effective_session_state(db, meeting)


def _update_session_state(
    db: Session,
    meeting: MeetingSession,
    *,
    stage: str | None = None,
    design_goal_text: str | None = None,
    product_category: str | None = None,
    brief_json: dict[str, object] | None = None,
    texture_plan_json: dict[str, object] | None = None,
) -> None:
    get_workflow_controller().update_session_state(
        db,
        meeting,
        stage=stage,
        design_goal_text=design_goal_text,
        product_category=product_category,
        brief_json=brief_json,
        texture_plan_json=texture_plan_json,
    )


def _save_ai_message(
    db: Session,
    *,
    session_id: int,
    user_id: int | None,
    role: str,
    mode: str | None,
    content: str,
    metadata_json: dict[str, object] | None = None,
) -> AiMessage:
    return get_workflow_controller().save_ai_message(
        db,
        session_id=session_id,
        user_id=user_id,
        role=role,
        mode=mode,
        content=content,
        metadata_json=metadata_json,
    )


def _to_texture_plan_state_out(
    *,
    session_id: int,
    texture_plan_json: dict[str, Any] | None,
    brief_json: dict[str, Any] | None,
) -> TexturePlanStateOut:
    normalized = normalize_texture_plan_state(texture_plan_json, brief_json=brief_json)
    return TexturePlanStateOut(
        session_id=session_id,
        source_text=str(normalized["source_text"]),
        document_name=normalized["document_name"],
        document_excerpt=str(normalized["document_excerpt"]),
        image_name=normalized["image_name"],
        image_content_keywords=list(normalized["image_content_keywords"]),
        image_style_keywords=list(normalized["image_style_keywords"]),
        selected_image_keywords=list(normalized["selected_image_keywords"]),
        brief_keywords=dict(normalized["brief_keywords"]),
        updated_at=str(normalized["updated_at"]),
    )


def _build_image_data_url(*, filename: str, content: bytes) -> str:
    mime_type = detect_image_mime_type(filename, content)
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _to_texture_models_state_out(
    *,
    session_id: int,
    texture_plan_json: dict[str, Any] | None,
    brief_json: dict[str, Any] | None,
) -> TextureModelsStateOut:
    normalized = normalize_texture_plan_state(texture_plan_json, brief_json=brief_json)
    return TextureModelsStateOut(
        session_id=session_id,
        status=str(normalized.get("texture_generation_status") or "idle"),
        models=[TexturedModelOut(**item) for item in normalized.get("textured_models", [])],
        updated_at=str(normalized.get("textured_models_updated_at") or utcnow_iso()),
    )


async def _emit_texture_models_updated(
    *,
    session_id: int,
    texture_plan_json: dict[str, Any] | None,
    brief_json: dict[str, Any] | None,
) -> None:
    payload = _to_texture_models_state_out(
        session_id=session_id,
        texture_plan_json=texture_plan_json,
        brief_json=brief_json,
    )
    await emit_session_event(
        "texture_models:updated",
        session_id,
        {"texture_models": payload.model_dump(mode="json")},
    )


def _set_texture_models_state(
    state: dict[str, Any] | None,
    *,
    brief_json: dict[str, Any] | None,
    status_text: str,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = normalize_texture_plan_state(state, brief_json=brief_json)
    normalized["texture_generation_status"] = status_text
    normalized["textured_models"] = models
    normalized["textured_models_updated_at"] = utcnow_iso()
    return normalized


def _normalize_keyword_items(raw_items: Any, *, max_items: int = 10) -> list[str]:
    if not isinstance(raw_items, list):
        return []
    keywords: list[str] = []
    for item in raw_items:
        if isinstance(item, str) and item.strip():
            keywords.append(item.strip())
        if len(keywords) >= max_items:
            break
    return keywords


async def _extract_image_analysis(
    *,
    provider: OpenAITextImageProvider,
    filename: str,
    content: bytes,
    brief_json: dict[str, Any] | None,
) -> dict[str, list[str]]:
    parsed = await provider.analyze_image_keywords(
        image_url=_build_image_data_url(filename=filename, content=content),
        brief_keywords=brief_json,
    )
    if not isinstance(parsed, dict):
        return {"content_keywords": [], "style_keywords": []}
    return {
        "content_keywords": _normalize_keyword_items(parsed.get("content_keywords")),
        "style_keywords": _normalize_keyword_items(parsed.get("style_keywords")),
    }


def _resolve_base_model_url(db: Session, meeting: MeetingSession) -> str | None:
    if not meeting.base_model_id:
        return None

    asset = db.execute(select(ModelAsset).where(ModelAsset.id == meeting.base_model_id)).scalar_one_or_none()
    if asset:
        original_upload_source = _resolve_meshy_compatible_upload_source_path(db, asset)
        if original_upload_source:
            return original_upload_source
        return asset.model_url

    transient_model = get_transient_model(int(meeting.base_model_id))
    if transient_model:
        model_url = transient_model.get("model_url")
        if isinstance(model_url, str) and model_url.strip():
            return model_url
    return None


def _resolve_meshy_compatible_upload_source_path(db: Session, asset: ModelAsset) -> str | None:
    if asset.source_type != "upload":
        return None

    inspection = asset.mapping_meta.get("inspection") if isinstance(asset.mapping_meta, dict) else None
    if not isinstance(inspection, dict):
        return None

    # Inference: if the uploaded model already had valid embedded UVs, the original
    # upload and the locked painting model share the same UV layout. In that case,
    # using the original GLB for Meshy avoids compatibility issues introduced by
    # downstream re-export while still keeping UV alignment with the editor.
    if inspection.get("has_original_uv") is not True or inspection.get("uv_source") != "embedded":
        return None

    task = (
        db.execute(
            select(ModelGenerationTask)
            .where(
                ModelGenerationTask.result_model_id == asset.id,
                ModelGenerationTask.task_type == "upload",
            )
            .order_by(ModelGenerationTask.id.desc())
        )
        .scalars()
        .first()
    )
    source_path = (task.source_path or "").strip() if task else ""
    if not source_path:
        return None
    return source_path if Path(source_path).is_file() else None


def _resolve_locked_base_model_reference(db: Session, meeting: MeetingSession) -> str | None:
    if not meeting.base_model_id:
        return None
    asset = db.execute(select(ModelAsset).where(ModelAsset.id == meeting.base_model_id)).scalar_one_or_none()
    if asset:
        return asset.model_url
    transient_model = get_transient_model(int(meeting.base_model_id))
    if transient_model:
        model_url = transient_model.get("model_url")
        if isinstance(model_url, str) and model_url.strip():
            return model_url
    return None


def _resolve_texture_application_model_reference(
    *,
    target_model: dict[str, Any],
    locked_base_model_reference: str,
) -> str:
    # Prefer the currently selected textured result so edited previews keep the
    # same geometry/material layout the user just reviewed. Fall back to the
    # locked base model if the scheme does not expose a locally resolvable GLB.
    candidate_references: list[str | None] = []
    edited_variant = target_model.get("edited_variant")
    if isinstance(edited_variant, dict):
        candidate_references.append(edited_variant.get("model_url"))
    candidate_references.append(target_model.get("textured_model_url"))
    candidate_references.append(locked_base_model_reference)

    for candidate in candidate_references:
        reference = str(candidate or "").strip()
        if not reference:
            continue
        if Path(reference).is_file() or reference.startswith("/files/models/"):
            return reference

    return locked_base_model_reference


async def _apply_texture_plan_schemes(
    *,
    db: Session,
    meeting: MeetingSession,
    session_id: int,
) -> ApplyTextureResponse:
    texture_plan_json = meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None
    normalized = normalize_texture_plan_state(
        texture_plan_json,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    schemes = normalized.get("schemes", [])
    if not schemes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No texture schemes available. Please generate model textures first.",
        )

    base_model_url = _resolve_base_model_url(db, meeting)
    if not base_model_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No base model available. Please prepare and lock a base model first.",
        )

    meshy_provider = _engine_get_meshy_texture_provider()
    results = await meshy_provider.retexture_all_schemes(
        model_glb_path=base_model_url,
        schemes=schemes,
    )

    models_out = []
    for result in results:
        matching_scheme = next((s for s in schemes if s.get("id") == result.scheme_id), {})
        models_out.append(
            TexturedModelOut(
                scheme_id=result.scheme_id,
                title=matching_scheme.get("title", ""),
                prompt_text=matching_scheme.get("prompt_text", ""),
                status=result.status,
                textured_model_url=result.textured_model_url,
                texture_maps=result.texture_maps,
                edited_variant=None,
                meshy_task_id=result.meshy_task_id,
                error_message=result.error_message,
            )
        )

    return ApplyTextureResponse(session_id=session_id, models=models_out)


def _run_texture_generation_background(
    *,
    session_id: int,
    user_id: int,
    source_text: str | None,
    document_name: str | None,
    document_text: str,
    image_name: str | None,
    image_content_keywords: list[str],
    image_style_keywords: list[str],
    selected_image_keywords: list[str],
) -> None:
    import asyncio

    asyncio.run(
        _process_texture_generation_background(
            session_id=session_id,
            user_id=user_id,
            source_text=source_text,
            document_name=document_name,
            document_text=document_text,
            image_name=image_name,
            image_content_keywords=image_content_keywords,
            image_style_keywords=image_style_keywords,
            selected_image_keywords=selected_image_keywords,
        )
    )


async def _process_texture_generation_background(
    *,
    session_id: int,
    user_id: int,
    source_text: str | None,
    document_name: str | None,
    document_text: str,
    image_name: str | None,
    image_content_keywords: list[str],
    image_style_keywords: list[str],
    selected_image_keywords: list[str],
) -> None:
    with SessionLocal() as db:
        meeting = _ensure_member(db, session_id, user_id)
        _apply_effective_session_state(db, meeting)
        should_persist = _should_persist_session_data(db, session_id)

        try:
            runtime = get_creative_dialogue_and_image_agent()
            provider = get_openai_text_image_provider()
            planning_context = TexturePlanningContext(
                session_id=session_id,
                product_category=meeting.product_category,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                base_model_summary=_build_base_model_summary(db, meeting),
                source_text=(source_text or "").strip(),
                document_text=document_text,
                document_name=document_name,
                selected_image_keywords=selected_image_keywords,
            )
            result = await runtime.plan_texture_schemes(provider=provider, context=planning_context)

            next_texture_plan = normalize_texture_plan_state(
                {
                    **(meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else {}),
                    "source_text": (source_text or "").strip(),
                    "document_name": document_name,
                    "document_excerpt": build_document_excerpt(document_text),
                    "image_name": image_name,
                    "image_content_keywords": image_content_keywords,
                    "image_style_keywords": image_style_keywords,
                    "selected_image_keywords": result.selected_image_keywords,
                    "brief_keywords": result.brief_keywords,
                    "schemes": [item.as_dict() for item in result.schemes],
                    "selected_scheme_id": "scheme_1",
                    "updated_at": utcnow_iso(),
                    "texture_generation_status": "processing",
                },
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
            next_texture_plan = _set_texture_models_state(
                next_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                status_text="processing",
                models=[
                    {
                        "scheme_id": item.id,
                        "title": item.title,
                        "prompt_text": item.prompt_text,
                        "status": "processing",
                        "textured_model_url": None,
                        "texture_maps": None,
                        "edited_variant": None,
                        "meshy_task_id": None,
                        "error_message": None,
                    }
                    for item in result.schemes
                ],
            )
            _update_session_state(db, meeting, texture_plan_json=next_texture_plan)
            if should_persist:
                db.commit()
                db.refresh(meeting)

            await _emit_texture_models_updated(
                session_id=session_id,
                texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
            await emit_session_event(
                "texture_plan:updated",
                session_id,
                {
                    "texture_plan": _to_texture_plan_state_out(
                        session_id=session_id,
                        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
                        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                    ).model_dump(mode="json")
                },
            )

            response = await _apply_texture_plan_schemes(db=db, meeting=meeting, session_id=session_id)
            models_payload = [item.model_dump(mode="json") for item in response.models]
            final_status = "completed" if all(item.status == "completed" for item in response.models) else "failed"
            final_texture_plan = _set_texture_models_state(
                meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                status_text=final_status,
                models=models_payload,
            )
            _update_session_state(db, meeting, texture_plan_json=final_texture_plan)
            if should_persist:
                db.commit()
                db.refresh(meeting)

            await _emit_texture_models_updated(
                session_id=session_id,
                texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else final_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
        except Exception as exc:  # noqa: BLE001
            failed_models = []
            existing = normalize_texture_plan_state(
                meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
            for item in existing.get("textured_models", []):
                failed_models.append(
                    {
                        **item,
                        "status": "failed",
                        "error_message": str(exc),
                    }
                )
            failed_texture_plan = _set_texture_models_state(
                meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                status_text="failed",
                models=failed_models,
            )
            _update_session_state(db, meeting, texture_plan_json=failed_texture_plan)
            if should_persist:
                db.commit()
                db.refresh(meeting)
            await _emit_texture_models_updated(
                session_id=session_id,
                texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else failed_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )


@router.post("/parse-brief", response_model=ParseBriefResponse)
async def parse_brief(
    payload: ParseBriefRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ParseBriefResponse:
    meeting = db.execute(select(MeetingSession).where(MeetingSession.id == payload.session_id)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    if not _is_host(db, payload.session_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can parse brief")

    text_provider: OpenAITextImageProvider | None = None
    try:
        text_provider = get_openai_text_image_provider()
    except Exception:
        text_provider = None

    brief_json: dict[str, object]
    try:
        stage1_runtime = get_stage1_intent_and_3d_generation_agent(text_provider)
        brief_json = await run_stage1_extract_concept(
            design_goal=payload.design_goal,
            product_category=payload.product_category,
            stage1_agent=stage1_runtime,
        )
    except Stage1RuntimeDependencyError:
        brief_json = _parse_brief_fallback(payload.design_goal, payload.product_category)
    except Exception:
        brief_json = _parse_brief_fallback(payload.design_goal, payload.product_category)

    next_stage = "BRIEFING" if meeting.stage == "LOBBY" else meeting.stage
    _update_session_state(
        db,
        meeting,
        stage=next_stage,
        design_goal_text=payload.design_goal,
        product_category=payload.product_category,
        brief_json=brief_json,
    )
    if should_persist:
        db.commit()
        db.refresh(meeting)

    await emit_session_event("brief:published", payload.session_id, {"brief_json": brief_json})
    await emit_session_event("stage:changed", payload.session_id, {"stage": meeting.stage})

    return ParseBriefResponse(session_id=payload.session_id, stage=meeting.stage, brief_json=brief_json)


@router.get("/texture-plan", response_model=TexturePlanStateOut)
def fetch_texture_plan(
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePlanStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    return _to_texture_plan_state_out(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )


@router.get("/texture-plan/models", response_model=TextureModelsStateOut)
def fetch_texture_models(
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    return _to_texture_models_state_out(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )


@router.post("/texture-plan/analyze-image", response_model=TexturePlanStateOut)
async def analyze_texture_plan_image(
    session_id: int = Form(..., ge=1),
    reference_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePlanStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    try:
        provider = get_openai_text_image_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    image_name = reference_image.filename or "reference_image"
    content = await reference_image.read()
    try:
        analysis = await _extract_image_analysis(
            provider=provider,
            filename=image_name,
            content=content,
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )
    except DocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    selected_keywords = list(dict.fromkeys([*analysis["content_keywords"], *analysis["style_keywords"]]))
    next_texture_plan = normalize_texture_plan_state(
        {
            **(meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else {}),
            "image_name": image_name,
            "image_content_keywords": analysis["content_keywords"],
            "image_style_keywords": analysis["style_keywords"],
            "selected_image_keywords": selected_keywords,
            "updated_at": utcnow_iso(),
        },
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )

    _update_session_state(db, meeting, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    response = _to_texture_plan_state_out(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    await emit_session_event("texture_plan:updated", session_id, {"texture_plan": response.model_dump(mode="json")})
    return response


@router.post("/texture-plan/generate", response_model=TexturePlanGenerateResponse)
async def generate_texture_plan(
    session_id: int = Form(..., ge=1),
    source_text: str | None = Form(default=None),
    document: UploadFile | None = File(default=None),
    reference_image: UploadFile | None = File(default=None),
    selected_image_keywords_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePlanGenerateResponse:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    try:
        runtime = get_creative_dialogue_and_image_agent()
    except AgentRuntimeDependencyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        provider = get_openai_text_image_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    normalized_source_text = (source_text or "").strip()
    document_text = ""
    document_name: str | None = None
    if document is not None:
        document_name = document.filename or "uploaded_document"
        try:
            document_text = extract_document_text(
                filename=document_name,
                content=await document.read(),
            )
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    has_text = bool(normalized_source_text)
    has_document = bool(document_text.strip())
    has_image = reference_image is not None or bool(selected_image_keywords_json and selected_image_keywords_json.strip())
    if not has_text and not has_document and not has_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide text, a document, or a reference image before generating schemes.",
        )

    image_name: str | None = None
    image_content_keywords: list[str] = []
    image_style_keywords: list[str] = []
    selected_image_keywords: list[str] = []
    existing_texture_plan = meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None
    if isinstance(existing_texture_plan, dict):
        existing_normalized_texture_plan = normalize_texture_plan_state(
            existing_texture_plan,
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )
        image_name = existing_normalized_texture_plan["image_name"]
        image_content_keywords = list(existing_normalized_texture_plan["image_content_keywords"])
        image_style_keywords = list(existing_normalized_texture_plan["image_style_keywords"])
        selected_image_keywords = list(existing_normalized_texture_plan["selected_image_keywords"])

    if reference_image is not None:
        image_name = reference_image.filename or "reference_image"
        try:
            analysis = await _extract_image_analysis(
                provider=provider,
                filename=image_name,
                content=await reference_image.read(),
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
            image_content_keywords = analysis["content_keywords"]
            image_style_keywords = analysis["style_keywords"]
            selected_image_keywords = list(dict.fromkeys([*image_content_keywords, *image_style_keywords]))
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except ModelProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if selected_image_keywords_json is not None and selected_image_keywords_json.strip():
        try:
            parsed_selected_keywords = json.loads(selected_image_keywords_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid selected image keywords payload.") from exc
        selected_image_keywords = _normalize_keyword_items(parsed_selected_keywords, max_items=16)

    planning_context = TexturePlanningContext(
        session_id=session_id,
        product_category=meeting.product_category,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        base_model_summary=_build_base_model_summary(db, meeting),
        source_text=normalized_source_text,
        document_text=document_text,
        document_name=document_name,
        selected_image_keywords=selected_image_keywords,
    )

    try:
        result = await runtime.plan_texture_schemes(provider=provider, context=planning_context)
    except ModelProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    next_texture_plan = normalize_texture_plan_state(
        {
            "source_text": normalized_source_text,
            "document_name": document_name,
            "document_excerpt": build_document_excerpt(document_text),
            "image_name": image_name,
            "image_content_keywords": image_content_keywords,
            "image_style_keywords": image_style_keywords,
            "selected_image_keywords": result.selected_image_keywords,
            "brief_keywords": result.brief_keywords,
            "schemes": [item.as_dict() for item in result.schemes],
            "selected_scheme_id": "scheme_1",
            "updated_at": utcnow_iso(),
        },
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )

    _update_session_state(db, meeting, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    response = _to_texture_plan_state_out(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    await emit_session_event("texture_plan:updated", session_id, {"texture_plan": response.model_dump(mode="json")})
    return TexturePlanGenerateResponse(texture_plan=response)


@router.post("/texture-plan/generate-model-textures", response_model=TextureModelsStartResponse)
async def generate_model_textures(
    background_tasks: BackgroundTasks,
    session_id: int = Form(..., ge=1),
    source_text: str | None = Form(default=None),
    document: UploadFile | None = File(default=None),
    reference_image: UploadFile | None = File(default=None),
    selected_image_keywords_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStartResponse:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    normalized_source_text = (source_text or "").strip()
    document_text = ""
    document_name: str | None = None
    if document is not None:
        document_name = document.filename or "uploaded_document"
        try:
            document_text = extract_document_text(
                filename=document_name,
                content=await document.read(),
            )
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    selected_image_keywords: list[str] = []
    image_name: str | None = None
    image_content_keywords: list[str] = []
    image_style_keywords: list[str] = []
    existing_texture_plan = meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None
    if isinstance(existing_texture_plan, dict):
        existing_normalized_texture_plan = normalize_texture_plan_state(
            existing_texture_plan,
            brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        )
        image_name = existing_normalized_texture_plan["image_name"]
        image_content_keywords = list(existing_normalized_texture_plan["image_content_keywords"])
        image_style_keywords = list(existing_normalized_texture_plan["image_style_keywords"])
        selected_image_keywords = list(existing_normalized_texture_plan["selected_image_keywords"])

    if reference_image is not None:
        try:
            provider = get_openai_text_image_provider()
        except ModelProviderNotConfiguredError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        image_name = reference_image.filename or "reference_image"
        try:
            analysis = await _extract_image_analysis(
                provider=provider,
                filename=image_name,
                content=await reference_image.read(),
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except ModelProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        image_content_keywords = analysis["content_keywords"]
        image_style_keywords = analysis["style_keywords"]
        selected_image_keywords = list(dict.fromkeys([*image_content_keywords, *image_style_keywords]))

    if selected_image_keywords_json is not None and selected_image_keywords_json.strip():
        try:
            parsed_selected_keywords = json.loads(selected_image_keywords_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid selected image keywords payload.") from exc
        selected_image_keywords = _normalize_keyword_items(parsed_selected_keywords, max_items=16)

    has_text = bool(normalized_source_text)
    has_document = bool(document_text.strip())
    has_image = bool(image_name or selected_image_keywords)
    if not has_text and not has_document and not has_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide text, a document, or a reference image before generating model textures.",
        )

    accepted_texture_plan = _set_texture_models_state(
        meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        status_text="queued",
        models=[
            {
                "scheme_id": "scheme_1",
                "title": "Queued",
                "prompt_text": "",
                "status": "pending",
                "textured_model_url": None,
                "texture_maps": None,
                "edited_variant": None,
                "meshy_task_id": None,
                "error_message": None,
            },
            {
                "scheme_id": "scheme_2",
                "title": "Queued",
                "prompt_text": "",
                "status": "pending",
                "textured_model_url": None,
                "texture_maps": None,
                "edited_variant": None,
                "meshy_task_id": None,
                "error_message": None,
            },
            {
                "scheme_id": "scheme_3",
                "title": "Queued",
                "prompt_text": "",
                "status": "pending",
                "textured_model_url": None,
                "texture_maps": None,
                "edited_variant": None,
                "meshy_task_id": None,
                "error_message": None,
            },
        ],
    )
    _update_session_state(db, meeting, texture_plan_json=accepted_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    await _emit_texture_models_updated(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else accepted_texture_plan,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )

    background_tasks.add_task(
        _run_texture_generation_background,
        session_id=session_id,
        user_id=current_user.id,
        source_text=normalized_source_text,
        document_name=document_name,
        document_text=document_text,
        image_name=image_name,
        image_content_keywords=image_content_keywords,
        image_style_keywords=image_style_keywords,
        selected_image_keywords=selected_image_keywords,
    )
    return TextureModelsStartResponse(session_id=session_id, status="accepted")


@router.patch("/texture-plan", response_model=TexturePlanStateOut)
async def patch_texture_plan(
    payload: TexturePlanPatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePlanStateOut:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    if payload.selected_image_keywords is None and not payload.clear_document and not payload.clear_image:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No texture plan changes were provided.")

    next_texture_plan = patch_texture_plan_state(
        meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        selected_image_keywords=payload.selected_image_keywords,
        clear_document=payload.clear_document,
        clear_image=payload.clear_image,
    )
    _update_session_state(db, meeting, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    response = _to_texture_plan_state_out(
        session_id=payload.session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    await emit_session_event(
        "texture_plan:updated",
        payload.session_id,
        {"texture_plan": response.model_dump(mode="json")},
    )
    return response


@router.post("/texture-plan/apply-edited-texture", response_model=TextureModelsStateOut)
async def apply_edited_texture(
    session_id: int = Form(..., ge=1),
    scheme_id: str = Form(...),
    edited_base_color: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    normalized_texture_plan = normalize_texture_plan_state(
        meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else None,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    textured_models = list(normalized_texture_plan.get("textured_models", []))
    target_model = next((item for item in textured_models if item.get("scheme_id") == scheme_id), None)
    if target_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected textured result was not found.")

    texture_maps = target_model.get("texture_maps")
    if not isinstance(texture_maps, dict) or not texture_maps.get("base_color"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected textured result does not contain a base_color texture to edit.",
        )

    locked_base_model_reference = _resolve_locked_base_model_reference(db, meeting)
    if not locked_base_model_reference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No locked base model is available for applying the edited texture.",
        )
    application_model_reference = _resolve_texture_application_model_reference(
        target_model=target_model,
        locked_base_model_reference=locked_base_model_reference,
    )

    edited_base_color_bytes = await edited_base_color.read()
    if not edited_base_color_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Edited base_color PNG is empty.")

    try:
        edited_result: EditedTextureApplicationResult = apply_edited_texture_to_model(
            session_id=session_id,
            scheme_id=scheme_id,
            base_model_reference=application_model_reference,
            edited_base_color_bytes=edited_base_color_bytes,
            texture_maps=texture_maps,
            meshy_task_id=target_model.get("meshy_task_id"),
        )
    except ModelTexturingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    updated_models: list[dict[str, Any]] = []
    for item in textured_models:
        if item.get("scheme_id") != scheme_id:
            updated_models.append(item)
            continue
        updated_models.append(
            {
                **item,
                "edited_variant": EditedTextureVariantOut(
                    model_url=edited_result.model_url,
                    base_color_url=edited_result.base_color_url,
                    applied_at=edited_result.applied_at,
                ).model_dump(mode="json"),
            }
        )

    next_texture_plan = {
        **normalized_texture_plan,
        "textured_models": updated_models,
        "textured_models_updated_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }
    _update_session_state(db, meeting, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)

    await _emit_texture_models_updated(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    return _to_texture_models_state_out(
        session_id=session_id,
        texture_plan_json=meeting.texture_plan_json if isinstance(meeting.texture_plan_json, dict) else next_texture_plan,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )


@router.post("/texture-plan/apply-texture", response_model=ApplyTextureResponse)
async def apply_texture(
    payload: ApplyTextureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplyTextureResponse:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    return await _apply_texture_plan_schemes(db=db, meeting=meeting, session_id=payload.session_id)


@router.post("/chat", response_model=None)
async def ai_chat(
    payload: AiChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    history = _fetch_recent_history(db, payload.session_id, limit=10)

    user_message = _save_ai_message(
        db,
        session_id=payload.session_id,
        user_id=current_user.id,
        role="user",
        mode=payload.mode,
        content=payload.message,
    )
    user_message_out = _to_ai_message_out(user_message).model_dump(mode="json")

    try:
        runtime = get_creative_dialogue_and_image_agent()
    except AgentRuntimeDependencyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        provider = get_openai_text_image_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    context = SessionAiContext(
        session_id=payload.session_id,
        product_category=meeting.product_category,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        base_model_summary=_build_base_model_summary(db, meeting),
        recent_messages=history,
    )
    plan = await run_stage3_generate_creative_reply(
        stage3_agent=runtime,
        mode=payload.mode,
        message=payload.message,
        context=context,
    )

    async def run_chat_once() -> tuple[str, dict[str, object]]:
        chunks: list[str] = []
        async for chunk in provider.stream_text(
            system_prompt=plan.system_prompt,
            user_message=payload.message,
            history=history,
            temperature=0.7,
        ):
            chunks.append(chunk)
        full_text = "".join(chunks).strip()
        if not full_text:
            full_text = "No valid AI reply was generated. Please try a different wording."

        with SessionLocal() as stream_db:
            assistant_message = _save_ai_message(
                stream_db,
                session_id=payload.session_id,
                user_id=None,
                role="assistant",
                mode=plan.route,
                content=full_text,
                metadata_json={"agent": f"{plan.route}_assistant"},
            )
            assistant_payload = _to_ai_message_out(assistant_message).model_dump(mode="json")
        return full_text, assistant_payload

    if not payload.stream:
        try:
            _full_text, assistant_payload = await run_chat_once()
        except ModelProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return {
            "route": plan.route,
            "user_message": user_message_out,
            "assistant_message": assistant_payload,
        }

    async def event_stream():
        chunks: list[str] = []
        try:
            async for chunk in provider.stream_text(
                system_prompt=plan.system_prompt,
                user_message=payload.message,
                history=history,
                temperature=0.7,
            ):
                chunks.append(chunk)
                yield _sse_event("chunk", {"delta": chunk})

            full_text = "".join(chunks).strip()
            if not full_text:
                full_text = "No valid AI reply was generated. Please try a different wording."

            with SessionLocal() as stream_db:
                assistant_message = _save_ai_message(
                    stream_db,
                    session_id=payload.session_id,
                    user_id=None,
                    role="assistant",
                    mode=plan.route,
                    content=full_text,
                    metadata_json={"agent": f"{plan.route}_assistant"},
                )
                assistant_payload = _to_ai_message_out(assistant_message).model_dump(mode="json")

            yield _sse_event(
                "done",
                {
                    "route": plan.route,
                    "user_message": user_message_out,
                    "assistant_message": assistant_payload,
                },
            )
        except ModelProviderError as exc:
            yield _sse_event(
                "error",
                {
                    "message": str(exc),
                    "code": exc.provider_code or "MODEL_PROVIDER_ERROR",
                },
            )
        except Exception:
            yield _sse_event(
                "error",
                {
                    "message": "AI service is temporarily unavailable. Please try again later.",
                    "code": "AI_INTERNAL_ERROR",
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history", response_model=AiChatHistoryResponse)
def fetch_chat_history(
    session_id: int = Query(..., ge=1),
    limit: int = Query(30, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiChatHistoryResponse:
    _ensure_member(db, session_id, current_user.id)
    if not _should_persist_session_data(db, session_id):
        return AiChatHistoryResponse(items=[], has_more=False)

    query = select(AiMessage).where(AiMessage.session_id == session_id).order_by(AiMessage.id.desc())
    if before_id is not None:
        query = query.where(AiMessage.id < before_id)

    rows = db.execute(query.limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return AiChatHistoryResponse(items=[_to_ai_message_out(row) for row in rows], has_more=has_more)


@router.post("/generate-image", response_model=AiGenerateImageResponse)
async def generate_image(
    payload: AiGenerateImageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiGenerateImageResponse:
    _ensure_member(db, payload.session_id, current_user.id)
    should_persist = _should_persist_session_data(db, payload.session_id)

    try:
        provider = get_openai_text_image_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        results = await run_stage4_generate_image_assets(
            provider=provider,
            prompt=payload.prompt,
            style_hint=payload.style_hint,
            reference_images=payload.reference_images,
        )
    except ModelProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not should_persist:
        now = datetime.now(timezone.utc)
        transient_items = [
            GeneratedImageOut(
                id=-index,
                session_id=payload.session_id,
                prompt=payload.prompt,
                style_hint=payload.style_hint,
                revised_prompt=result.revised_prompt,
                image_url=result.image_url,
                created_at=now,
            )
            for index, result in enumerate(results, start=1)
        ]
        return AiGenerateImageResponse(items=transient_items)

    items: list[GeneratedImageOut] = []
    created_ids: list[int] = []
    for result in results:
        row = GeneratedImage(
            session_id=payload.session_id,
            user_id=current_user.id,
            prompt=payload.prompt,
            style_hint=payload.style_hint,
            revised_prompt=result.revised_prompt,
            image_url=result.image_url,
            provider="openai",
            model_name=provider.image_model,
            metadata_json={
                "reference_images": payload.reference_images[:4],
                "provider_payload": result.provider_payload,
            },
        )
        db.add(row)
        db.flush()
        created_ids.append(row.id)
        items.append(
            GeneratedImageOut(
                id=row.id,
                session_id=row.session_id,
                prompt=row.prompt,
                style_hint=row.style_hint,
                revised_prompt=row.revised_prompt,
                image_url=row.image_url,
                created_at=row.created_at,
            )
        )

    summary = f"Generated {len(items)} pattern image assets for canvas reference."
    db.add(
        AiMessage(
            session_id=payload.session_id,
            user_id=None,
            role="assistant",
            mode="image",
            content=summary,
            metadata_json={"generated_image_ids": created_ids},
        )
    )
    db.commit()

    refreshed_rows = db.execute(
        select(GeneratedImage).where(GeneratedImage.id.in_(created_ids)).order_by(GeneratedImage.id.asc())
    ).scalars().all()
    final_items = [
        GeneratedImageOut(
            id=row.id,
            session_id=row.session_id,
            prompt=row.prompt,
            style_hint=row.style_hint,
            revised_prompt=row.revised_prompt,
            image_url=row.image_url,
            created_at=row.created_at,
        )
        for row in refreshed_rows
    ]

    return AiGenerateImageResponse(items=final_items)
