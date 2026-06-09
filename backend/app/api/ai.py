from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.stage3_review_agents import Stage3ReviewContext, Stage3ReviewService
from app.agents.creative_dialogue_and_image_agent import (
    AgentRuntimeDependencyError,
    CreativeDialogueAndImageAgent,
    TexturePlanningContext,
)
from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent, Stage1RuntimeDependencyError
from app.agents.pattern_asset_agent import PatternAssetContext, PatternAssetAgent
from app.agents.stage4_media_agent import Stage4MediaAgent, Stage4MediaContext
from app.agents.providers.aihubmix_media_provider import AiHubMixMediaProvider
from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider
from app.agents.providers.provider_protocols import ModelProviderError, ModelProviderNotConfiguredError
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import AiMessage, GeneratedImage, GeneratedMediaAsset, MeetingSession, ModelAsset, ModelGenerationTask, SessionMember, User
from app.db.session import SessionLocal, get_db
from app.document_parsing import DocumentParseError, detect_image_mime_type, extract_document_text
from app.graph.engine import (
    get_creative_dialogue_and_image_agent as _engine_get_creative_dialogue_and_image_agent,
    get_aihubmix_media_provider as _engine_get_aihubmix_media_provider,
    get_meshy_texture_provider as _engine_get_meshy_texture_provider,
    get_openai_text_image_provider as _engine_get_openai_text_image_provider,
    get_pattern_asset_agent as _engine_get_pattern_asset_agent,
    get_pattern_image_provider as _engine_get_pattern_image_provider,
    get_stage4_media_agent as _engine_get_stage4_media_agent,
    get_stage1_intent_and_3d_generation_agent as _engine_get_stage1_intent_and_3d_generation_agent,
)
from app.model_texturing import EditedTextureApplicationResult, ModelTexturingError, apply_edited_texture_to_model
from app.model_processing import (
    TEXTURE_MAP_DIR,
    ModelProcessingError,
    create_original_upload_path,
    process_uploaded_model,
    to_texture_url,
)
from app.schemas.ai import (
    AiGenerateImageRequest,
    AiGenerateImageResponse,
    ApplyTextureRequest,
    ApplyTextureResponse,
    EditedTextureVariantOut,
    GeneratedImageOut,
    GeneratedMediaAssetOut,
    ParseBriefRequest,
    ParseBriefResponse,
    RefreshTextureReviewRequest,
    ImportSharedTextureResultsRequest,
    Stage4SceneImageGenerateRequest,
    Stage4SceneImageGenerateResponse,
    Stage4MediaListResponse,
    Stage4SceneVideoGenerateRequest,
    Stage4SceneVideoGenerateResponse,
    TexturedModelOut,
    TexturePatternGenerateRequest,
    TexturePatternGenerateResponse,
    TextureModelsStartResponse,
    TextureModelsStateOut,
    TexturePlanGenerateResponse,
    TexturePlanPatchRequest,
    TexturePlanStateOut,
    ShareTextureResultsRequest,
    ShareTextureResultsResponse,
    SharedTextureResultsResponse,
)
from app.stages.stage1_extract_concept import build_fallback_brief, run_stage1_extract_concept
from app.stages.stage4_generate_image_assets import run_stage4_generate_image_assets
from app.socket.server import emit_session_event
from app.texture_planning import (
    build_document_excerpt,
    normalize_texture_plan_state,
    patch_texture_plan_state,
    utcnow_iso,
)
from app.model_runtime import get_transient_model
from app.session_settings import normalize_session_settings
from app.workflow.controller import get_workflow_controller

router = APIRouter()


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


def get_pattern_asset_agent() -> PatternAssetAgent:
    return _engine_get_pattern_asset_agent()


def get_stage4_media_agent() -> Stage4MediaAgent:
    return _engine_get_stage4_media_agent()


def get_pattern_image_provider() -> OpenAITextImageProvider:
    return _engine_get_pattern_image_provider()


def get_aihubmix_media_provider() -> AiHubMixMediaProvider:
    return _engine_get_aihubmix_media_provider()


# Backward-compatible accessors.
def get_agent_runtime() -> CreativeDialogueAndImageAgent:
    return get_creative_dialogue_and_image_agent()


def get_stage1_runtime(text_provider: OpenAITextImageProvider | None) -> Stage1IntentAndThreeDGenerationAgent:
    return get_stage1_intent_and_3d_generation_agent(text_provider)


def get_openai_provider() -> OpenAITextImageProvider:
    return get_openai_text_image_provider()


def get_stage3_review_service() -> Stage3ReviewService:
    return Stage3ReviewService()


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
    session_settings_json: dict[str, object] | None = None,
    stage3_shared_refs_json: list[dict[str, object]] | None = None,
) -> None:
    get_workflow_controller().update_session_state(
        db,
        meeting,
        stage=stage,
        design_goal_text=design_goal_text,
        product_category=product_category,
        brief_json=brief_json,
        texture_plan_json=texture_plan_json,
        session_settings_json=session_settings_json,
        stage3_shared_refs_json=stage3_shared_refs_json,
    )


def _get_session_member_record(db: Session, session_id: int, user_id: int) -> SessionMember:
    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this session")
    return member


def _read_member_texture_plan(
    *,
    meeting: MeetingSession,
    member: SessionMember,
) -> dict[str, Any] | None:
    if isinstance(member.workspace_json, dict):
        return dict(member.workspace_json)
    if member.role == "host" and isinstance(meeting.texture_plan_json, dict):
        return dict(meeting.texture_plan_json)
    return None


def _write_member_texture_plan(
    db: Session,
    *,
    meeting: MeetingSession,
    member: SessionMember,
    texture_plan_json: dict[str, Any],
) -> None:
    member.workspace_json = texture_plan_json
    db.add(member)
    if member.role == "host":
        _update_session_state(db, meeting, texture_plan_json=texture_plan_json)


def _normalize_shared_result_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _replace_member_shared_result_ids(
    db: Session,
    *,
    member: SessionMember,
    result_ids: list[str],
) -> list[str]:
    normalized = _normalize_shared_result_ids(result_ids)
    member.shared_result_ids_json = normalized
    db.add(member)
    return normalized


def _normalize_stage3_shared_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        try:
            owner_user_id = int(item.get("owner_user_id") or 0)
        except (TypeError, ValueError):
            owner_user_id = 0
        result_id = str(item.get("result_id") or "").strip()
        shared_at = str(item.get("shared_at") or "").strip() or utcnow_iso()
        try:
            display_order = int(item.get("display_order") or index)
        except (TypeError, ValueError):
            display_order = index
        if owner_user_id <= 0 or not result_id:
            continue
        dedupe_key = (owner_user_id, result_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "owner_user_id": owner_user_id,
                "result_id": result_id,
                "display_order": display_order,
                "shared_at": shared_at,
            }
        )
    return normalized


def _get_member_textured_models(
    *,
    meeting: MeetingSession,
    member: SessionMember,
) -> list[dict[str, Any]]:
    workspace = normalize_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    return list(workspace.get("textured_models", []))


def _build_shared_models_for_member(
    *,
    meeting: MeetingSession,
    member: SessionMember,
) -> list[dict[str, Any]]:
    shared_result_ids = set(_normalize_shared_result_ids(member.shared_result_ids_json))
    if not shared_result_ids:
        return []
    models: list[dict[str, Any]] = []
    for item in _get_member_textured_models(meeting=meeting, member=member):
        if str(item.get("result_id") or "").strip() not in shared_result_ids:
            continue
        if str(item.get("status") or "").strip().lower() != "completed":
            continue
        models.append(item)
    return models


def _remove_result_from_stage3_shared_refs(
    *,
    meeting: MeetingSession,
    owner_user_id: int,
    result_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    normalized_result_id = str(result_id or "").strip()
    if owner_user_id <= 0 or not normalized_result_id:
        return _normalize_stage3_shared_refs(meeting.stage3_shared_refs_json), False

    existing_refs = _normalize_stage3_shared_refs(meeting.stage3_shared_refs_json)
    next_refs = [
        item
        for item in existing_refs
        if not (
            int(item.get("owner_user_id") or 0) == owner_user_id
            and str(item.get("result_id") or "").strip() == normalized_result_id
        )
    ]
    return next_refs, len(next_refs) != len(existing_refs)


def _build_stage3_shared_models_for_meeting(
    *,
    db: Session,
    meeting: MeetingSession,
) -> tuple[list[dict[str, Any]], str]:
    shared_refs = _normalize_stage3_shared_refs(meeting.stage3_shared_refs_json)
    if not shared_refs:
        return [], utcnow_iso()

    member_rows = db.execute(
        select(SessionMember, User)
        .join(User, User.id == SessionMember.user_id)
        .where(SessionMember.session_id == meeting.id)
    ).all()
    member_by_user_id = {
        session_member.user_id: (session_member, user)
        for session_member, user in member_rows
    }

    resolved: list[dict[str, Any]] = []
    latest_shared_at = utcnow_iso()
    for ref in shared_refs:
        owner_user_id = int(ref.get("owner_user_id") or 0)
        result_id = str(ref.get("result_id") or "").strip()
        if owner_user_id <= 0 or not result_id:
            continue
        member_row = member_by_user_id.get(owner_user_id)
        if member_row is None:
            continue
        owner_member, owner_user = member_row
        owner_models = _get_member_textured_models(meeting=meeting, member=owner_member)
        matched = _get_textured_model_by_result_id(owner_models, result_id)
        if matched is None:
            continue
        if str(matched.get("status") or "").strip().lower() != "completed":
            continue
        shared_at = str(ref.get("shared_at") or "").strip() or utcnow_iso()
        latest_shared_at = shared_at
        resolved.append(
            {
                **matched,
                "submitted_by": {
                    "user_id": owner_user.id,
                    "user_name": owner_user.name,
                },
            }
        )

    return resolved, latest_shared_at


def _to_member_texture_plan_state_out(
    *,
    session_id: int,
    meeting: MeetingSession,
    member: SessionMember,
) -> TexturePlanStateOut:
    return _to_texture_plan_state_out(
        session_id=session_id,
        texture_plan_json=_read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )


def _to_member_texture_models_state_out(
    *,
    session_id: int,
    meeting: MeetingSession,
    member: SessionMember,
) -> TextureModelsStateOut:
    return _to_texture_models_state_out(
        session_id=session_id,
        texture_plan_json=_read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )


async def _emit_member_texture_models_updated(
    *,
    session_id: int,
    meeting: MeetingSession,
    member: SessionMember,
) -> None:
    await _emit_texture_models_updated(
        session_id=session_id,
        texture_plan_json=_read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )


async def _emit_session_members_updated(*, session_id: int) -> None:
    await emit_session_event(
        "session_members:updated",
        session_id,
        {"updated_at": utcnow_iso()},
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


def _to_generated_media_asset_out(
    row: GeneratedMediaAsset,
    *,
    can_delete: bool = False,
) -> GeneratedMediaAssetOut:
    return GeneratedMediaAssetOut(
        id=row.id,
        session_id=row.session_id,
        result_id=row.result_id,
        scheme_name=row.scheme_name,
        media_type=row.media_type,  # type: ignore[arg-type]
        media_url=row.media_url,
        prompt=row.prompt,
        provider=row.provider,
        model_name=row.model_name,
        prediction_id=row.prediction_id,
        source_image_url=row.source_image_url,
        can_delete=can_delete,
        created_at=row.created_at,
    )


def _stage4_suffix_from_mime_type(mime_type: str, *, media_type: str) -> str:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    if media_type == "image":
        return {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
        }.get(normalized, ".png")
    return {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "application/vnd.apple.mpegurl": ".m3u8",
        "application/x-mpegurl": ".m3u8",
    }.get(normalized, ".mp4")


def _stage4_suffix_from_url(media_url: str, *, media_type: str) -> str:
    suffix = Path(urlparse(media_url).path).suffix.lower()
    if media_type == "image" and suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    if media_type == "video" and suffix in {".mp4", ".mov", ".webm", ".m3u8"}:
        return suffix
    return ".png" if media_type == "image" else ".mp4"


def _stage4_remote_media_headers(media_url: str) -> dict[str, str]:
    settings = get_settings()
    api_key = settings.aihubmix_api_key.strip()
    if not api_key:
        return {}

    parsed = urlparse(media_url)
    base = urlparse(settings.aihubmix_base_url)
    if parsed.scheme not in {"http", "https"}:
        return {}

    parsed_host = parsed.netloc.lower()
    base_host = base.netloc.lower()
    allowed_hosts = {base_host}
    if base_host in {"aihubmix.com", "api.aihubmix.com"}:
        allowed_hosts.update({"aihubmix.com", "api.aihubmix.com"})
    base_path = (base.path or "").rstrip("/")
    video_prefix = f"{base_path}/videos/" if base_path else "/videos/"
    if parsed_host in allowed_hosts and (parsed.path or "").startswith(video_prefix):
        return {"Authorization": f"Bearer {api_key}"}
    return {}


async def _download_stage4_remote_media(*, session_id: int, media_url: str, media_type: str) -> str:
    parsed = urlparse(media_url)
    if parsed.scheme not in {"http", "https"}:
        return media_url

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(media_url, headers=_stage4_remote_media_headers(media_url))
            response.raise_for_status()
    except Exception:
        return media_url

    content = response.content
    if not content:
        return media_url
    content_type = response.headers.get("content-type", "")
    suffix = (
        _stage4_suffix_from_mime_type(content_type, media_type=media_type)
        if content_type
        else _stage4_suffix_from_url(media_url, media_type=media_type)
    )
    output_path = TEXTURE_MAP_DIR / f"stage4_{media_type}_{session_id}_{uuid4().hex[:12]}{suffix}"
    output_path.write_bytes(content)
    return to_texture_url(output_path)


async def _stage4_media_url_for_storage(*, session_id: int, media_url: str, media_type: str) -> str:
    if not media_url.startswith("data:image/"):
        return await _download_stage4_remote_media(
            session_id=session_id,
            media_url=media_url,
            media_type=media_type,
        )

    header, separator, payload = media_url.partition(",")
    if separator != "," or ";base64" not in header:
        return media_url
    mime_type = header.removeprefix("data:").split(";", 1)[0].lower()
    suffix = _stage4_suffix_from_mime_type(mime_type, media_type=media_type)
    try:
        content = base64.b64decode(payload)
    except ValueError:
        return media_url
    output_path = TEXTURE_MAP_DIR / f"stage4_{media_type}_{session_id}_{uuid4().hex[:12]}{suffix}"
    output_path.write_bytes(content)
    return to_texture_url(output_path)


def _stage4_media_path_from_url(media_url: str) -> Path | None:
    parsed_path = urlparse(media_url).path or media_url
    if not parsed_path.startswith("/files/textures/"):
        return None
    candidate = (TEXTURE_MAP_DIR / Path(parsed_path).name).resolve()
    try:
        candidate.relative_to(TEXTURE_MAP_DIR.resolve())
    except ValueError:
        return None
    return candidate


def _stage4_local_image_data_url(media_url: str) -> str | None:
    candidate = _stage4_media_path_from_url(media_url)
    if candidate is None or not candidate.exists() or not candidate.is_file():
        return None
    try:
        content = candidate.read_bytes()
    except OSError:
        return None
    if not content:
        return None
    mime_type = detect_image_mime_type(candidate.name, content)
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _stage4_video_reference_image_url(image_url: str) -> str:
    normalized = image_url.strip()
    if normalized.startswith("data:image/"):
        return normalized
    return _stage4_local_image_data_url(normalized) or normalized


def _extract_stage4_generated_image_id(row: GeneratedMediaAsset) -> int | None:
    if not isinstance(row.metadata_json, dict):
        return None
    raw_value = row.metadata_json.get("generated_image_id")
    try:
        normalized = int(raw_value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _cleanup_stage4_media_files_if_unused(db: Session, media_urls: set[str]) -> None:
    for media_url in media_urls:
        if not media_url:
            continue
        candidate = _stage4_media_path_from_url(media_url)
        if candidate is None or not candidate.exists():
            continue
        media_ref = db.execute(
            select(GeneratedMediaAsset.id).where(GeneratedMediaAsset.media_url == media_url).limit(1)
        ).scalar_one_or_none()
        image_ref = db.execute(
            select(GeneratedImage.id).where(GeneratedImage.image_url == media_url).limit(1)
        ).scalar_one_or_none()
        if media_ref is None and image_ref is None:
            try:
                candidate.unlink()
            except OSError:
                continue


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


def _new_result_id(*, prefix: str = "result") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _new_batch_id() -> str:
    return f"batch_{uuid4().hex[:10]}"


def _build_textured_model_payload(
    *,
    result_id: str,
    batch_id: str | None,
    source_type: str,
    created_at: str,
    family_id: str | None = None,
    parent_result_id: str | None = None,
    scheme_id: str,
    title: str,
    prompt_text: str,
    status: str,
    textured_model_url: str | None,
    texture_maps: dict[str, str | None] | None,
    edited_variant: dict[str, Any] | None = None,
    review_assessment: dict[str, Any] | None = None,
    meshy_task_id: str | None = None,
    error_message: str | None = None,
    shared_origin: dict[str, Any] | None = None,
    submitted_by: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "result_id": result_id,
        "batch_id": batch_id,
        "source_type": source_type,
        "created_at": created_at,
        "family_id": family_id or result_id,
        "parent_result_id": parent_result_id,
        "scheme_id": scheme_id,
        "title": title,
        "prompt_text": prompt_text,
        "status": status,
        "textured_model_url": textured_model_url,
        "texture_maps": texture_maps,
        "edited_variant": edited_variant,
        "review_assessment": review_assessment,
        "meshy_task_id": meshy_task_id,
        "error_message": error_message,
        "shared_origin": shared_origin,
        "submitted_by": submitted_by,
    }


def _merge_textured_models(
    existing_models: list[dict[str, Any]],
    incoming_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    replacements = {
        str(item.get("result_id") or "").strip(): item
        for item in incoming_models
        if str(item.get("result_id") or "").strip()
    }
    incoming_order = [str(item.get("result_id") or "").strip() for item in incoming_models if str(item.get("result_id") or "").strip()]

    merged: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for item in existing_models:
        result_id = str(item.get("result_id") or "").strip()
        if result_id and result_id in replacements:
            merged.append(replacements[result_id])
            used_ids.add(result_id)
            continue
        merged.append(item)

    for result_id in incoming_order:
        if result_id in used_ids:
            continue
        merged.append(replacements[result_id])
        used_ids.add(result_id)
    return merged


def _merge_texture_models_state(
    state: dict[str, Any] | None,
    *,
    brief_json: dict[str, Any] | None,
    status_text: str,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = normalize_texture_plan_state(state, brief_json=brief_json)
    normalized["texture_generation_status"] = status_text
    normalized["textured_models"] = _merge_textured_models(
        list(normalized.get("textured_models", [])),
        models,
    )
    normalized["textured_models_updated_at"] = utcnow_iso()
    normalized["updated_at"] = utcnow_iso()
    return normalized


def _get_textured_model_by_result_id(
    textured_models: list[dict[str, Any]],
    result_id: str,
) -> dict[str, Any] | None:
    normalized_result_id = (result_id or "").strip()
    if not normalized_result_id:
        return None
    return next((item for item in textured_models if item.get("result_id") == normalized_result_id), None)


def _get_locked_base_model_payload(db: Session, meeting: MeetingSession) -> dict[str, Any] | None:
    asset = _get_locked_base_model_asset(db, meeting)
    if asset is not None:
        return {
            "mapping_meta": asset.mapping_meta if isinstance(asset.mapping_meta, dict) else {},
            "surface_area_m2": float(getattr(asset, "surface_area_m2", 0.0) or 0.0),
            "paintable_uv_pixels": int(getattr(asset, "paintable_uv_pixels", 0) or 0),
        }

    if not meeting.base_model_id:
        return None

    transient_model = get_transient_model(int(meeting.base_model_id))
    if transient_model is None:
        return None
    return {
        "mapping_meta": transient_model.get("mapping_meta") if isinstance(transient_model.get("mapping_meta"), dict) else {},
        "surface_area_m2": float(transient_model.get("surface_area_m2") or 0.0),
        "paintable_uv_pixels": int(transient_model.get("paintable_uv_pixels") or 0),
    }


def _validate_uploaded_textured_model_compatibility(
    *,
    locked_base_model: dict[str, Any] | None,
    uploaded_mapping_meta: dict[str, Any],
    uploaded_surface_area_m2: float,
    uploaded_paintable_uv_pixels: int,
) -> None:
    if locked_base_model is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No locked base model metadata is available for compatibility validation.",
        )

    locked_mapping_meta = locked_base_model.get("mapping_meta") if isinstance(locked_base_model, dict) else {}
    locked_inspection = locked_mapping_meta.get("inspection") if isinstance(locked_mapping_meta, dict) else {}
    locked_uv_spec = locked_mapping_meta.get("uv_spec") if isinstance(locked_mapping_meta, dict) else {}

    uploaded_inspection = uploaded_mapping_meta.get("inspection") if isinstance(uploaded_mapping_meta, dict) else {}
    uploaded_uv_spec = uploaded_mapping_meta.get("uv_spec") if isinstance(uploaded_mapping_meta, dict) else {}

    mismatches: list[str] = []
    checks = [
        ("mesh_count", locked_inspection.get("mesh_count"), uploaded_inspection.get("mesh_count")),
        ("material_count", locked_inspection.get("material_count"), uploaded_inspection.get("material_count")),
        ("uv_width", locked_uv_spec.get("width"), uploaded_uv_spec.get("width")),
        ("uv_height", locked_uv_spec.get("height"), uploaded_uv_spec.get("height")),
    ]
    for label, locked_value, uploaded_value in checks:
        if locked_value is None or uploaded_value is None:
            continue
        if int(locked_value) != int(uploaded_value):
            mismatches.append(f"{label} {uploaded_value} != {locked_value}")

    locked_uv_pixels = int(locked_base_model.get("paintable_uv_pixels") or 0)
    if locked_uv_pixels > 0 and uploaded_paintable_uv_pixels > 0:
        uv_delta = abs(uploaded_paintable_uv_pixels - locked_uv_pixels) / max(locked_uv_pixels, 1)
        if uv_delta > 0.05:
            mismatches.append(
                f"paintable_uv_pixels {uploaded_paintable_uv_pixels} != {locked_uv_pixels}"
            )

    locked_surface_area = float(locked_base_model.get("surface_area_m2") or 0.0)
    if locked_surface_area > 0 and uploaded_surface_area_m2 > 0:
        surface_delta = abs(uploaded_surface_area_m2 - locked_surface_area) / max(locked_surface_area, 1.0)
        if surface_delta > 0.05:
            mismatches.append(
                f"surface_area_m2 {uploaded_surface_area_m2:.3f} != {locked_surface_area:.3f}"
            )

    if mismatches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Uploaded textured model is incompatible with the locked base model: "
                + "; ".join(mismatches[:4])
            ),
        )


async def _store_uploaded_base_color_texture(
    *,
    session_id: int,
    result_id: str,
    base_color_file: UploadFile,
) -> tuple[str, bytes]:
    base_color_bytes = await base_color_file.read()
    if not base_color_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded base_color texture is empty.")

    suffix = Path(base_color_file.filename or "base_color.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    texture_path = TEXTURE_MAP_DIR / f"session_{session_id}_{result_id}_base_color{suffix}"
    texture_path.write_bytes(base_color_bytes)
    return to_texture_url(texture_path), base_color_bytes


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


def _resolve_pattern_texture_reference(
    *,
    target_model: dict[str, Any],
    preview_mode: str,
) -> tuple[str | None, str]:
    requested_mode = (preview_mode or "").strip().lower()
    edited_variant = target_model.get("edited_variant") if isinstance(target_model.get("edited_variant"), dict) else {}
    texture_maps = target_model.get("texture_maps") if isinstance(target_model.get("texture_maps"), dict) else {}

    if requested_mode == "edited":
        edited_reference = str(edited_variant.get("base_color_url") or "").strip()
        if edited_reference:
            return edited_reference, "edited"

    meshy_reference = str(texture_maps.get("base_color") or "").strip()
    if meshy_reference:
        return meshy_reference, "meshy"

    edited_reference = str(edited_variant.get("base_color_url") or "").strip()
    if edited_reference:
        return edited_reference, "edited"

    return None, "meshy"


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


def _get_locked_base_model_asset(db: Session, meeting: MeetingSession) -> ModelAsset | None:
    if not meeting.base_model_id:
        return None
    return db.execute(select(ModelAsset).where(ModelAsset.id == meeting.base_model_id)).scalar_one_or_none()


def _build_stage3_review_context(
    *,
    meeting: MeetingSession,
    base_model_asset: ModelAsset | None,
    model_payload: dict[str, Any],
    texture_reference: str | None,
) -> Stage3ReviewContext:
    mapping_meta = base_model_asset.mapping_meta if isinstance(getattr(base_model_asset, "mapping_meta", None), dict) else {}
    inspection = mapping_meta.get("inspection") if isinstance(mapping_meta, dict) else {}
    uv_spec = mapping_meta.get("uv_spec") if isinstance(mapping_meta, dict) else {}
    session_settings = normalize_session_settings(
        meeting.session_settings_json,
        fallback_updated_by_user_id=meeting.creator_id,
    )
    return Stage3ReviewContext(
        product_category=(meeting.product_category or "industrial_other").strip() or "industrial_other",
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        surface_area_m2=float(getattr(base_model_asset, "surface_area_m2", 0.0) or 0.0),
        paintable_uv_pixels=int(getattr(base_model_asset, "paintable_uv_pixels", 0) or 0),
        uv_width=int(uv_spec.get("width")) if isinstance(uv_spec, dict) and uv_spec.get("width") else None,
        uv_height=int(uv_spec.get("height")) if isinstance(uv_spec, dict) and uv_spec.get("height") else None,
        mesh_count=int(inspection.get("mesh_count") or 1) if isinstance(inspection, dict) else 1,
        material_count=int(inspection.get("material_count") or 1) if isinstance(inspection, dict) else 1,
        uv_source=str(inspection.get("uv_source") or "unknown") if isinstance(inspection, dict) else "unknown",
        scheme_id=str(model_payload.get("scheme_id") or ""),
        scheme_title=str(model_payload.get("title") or ""),
        prompt_text=str(model_payload.get("prompt_text") or ""),
        texture_reference=texture_reference,
        settings_revision=int(session_settings.get("revision") or 1),
        review_personas=session_settings.get("review_personas") if isinstance(session_settings.get("review_personas"), dict) else None,
    )


async def _attach_stage3_review_assessment(
    *,
    db: Session,
    meeting: MeetingSession,
    model_payload: dict[str, Any],
    texture_reference: str | None,
    provider: OpenAITextImageProvider | None,
) -> dict[str, Any]:
    if (model_payload.get("status") or "") != "completed" or not texture_reference:
        return model_payload

    review_service = get_stage3_review_service()
    base_model_asset = _get_locked_base_model_asset(db, meeting)
    context = _build_stage3_review_context(
        meeting=meeting,
        base_model_asset=base_model_asset,
        model_payload=model_payload,
        texture_reference=texture_reference,
    )
    review_assessment = await review_service.analyze_scheme(provider=provider, context=context)
    return {
        **model_payload,
        "review_assessment": review_assessment.as_dict(),
    }


async def _attach_stage3_reviews_to_models(
    *,
    db: Session,
    meeting: MeetingSession,
    models_payload: list[dict[str, Any]],
    provider: OpenAITextImageProvider | None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in models_payload:
        texture_maps = item.get("texture_maps")
        texture_reference = (
            texture_maps.get("base_color")
            if isinstance(texture_maps, dict)
            else None
        )
        enriched.append(
            await _attach_stage3_review_assessment(
                db=db,
                meeting=meeting,
                model_payload=item,
                texture_reference=texture_reference if isinstance(texture_reference, str) else None,
                provider=provider,
            )
    )
    return enriched


def _resolve_review_texture_reference(model_payload: dict[str, Any]) -> str | None:
    edited_variant = model_payload.get("edited_variant")
    texture_maps = model_payload.get("texture_maps")

    if isinstance(edited_variant, dict) and isinstance(edited_variant.get("base_color_url"), str):
        reference = str(edited_variant.get("base_color_url") or "").strip()
        if reference:
            return reference
    if isinstance(texture_maps, dict) and isinstance(texture_maps.get("base_color"), str):
        reference = str(texture_maps.get("base_color") or "").strip()
        if reference:
            return reference
    return None


async def _apply_texture_plan_schemes(
    *,
    db: Session,
    meeting: MeetingSession,
    member: SessionMember,
    session_id: int,
    review_provider: OpenAITextImageProvider | None = None,
    batch_id: str | None = None,
    result_identity_by_scheme_id: dict[str, dict[str, str | None]] | None = None,
) -> ApplyTextureResponse:
    texture_plan_json = _read_member_texture_plan(meeting=meeting, member=member)
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

    models_payload: list[dict[str, Any]] = []
    for result in results:
        matching_scheme = next((s for s in schemes if s.get("id") == result.scheme_id), {})
        identity = (result_identity_by_scheme_id or {}).get(result.scheme_id, {})
        models_payload.append(
            _build_textured_model_payload(
                result_id=str(identity.get("result_id") or _new_result_id(prefix="generated")),
                batch_id=str(identity.get("batch_id") or batch_id) if identity.get("batch_id") or batch_id else None,
                source_type="generated",
                created_at=str(identity.get("created_at") or utcnow_iso()),
                scheme_id=result.scheme_id,
                title=str(matching_scheme.get("title") or ""),
                prompt_text=str(matching_scheme.get("prompt_text") or ""),
                status=result.status,
                textured_model_url=result.textured_model_url,
                texture_maps=result.texture_maps,
                edited_variant=None,
                review_assessment=None,
                meshy_task_id=result.meshy_task_id,
                error_message=result.error_message,
            )
        )

    models_payload = await _attach_stage3_reviews_to_models(
        db=db,
        meeting=meeting,
        models_payload=models_payload,
        provider=review_provider,
    )
    return ApplyTextureResponse(
        session_id=session_id,
        models=[TexturedModelOut(**item) for item in models_payload],
    )


def _run_texture_generation_background(
    *,
    session_id: int,
    user_id: int,
    batch_id: str,
    result_identity_by_scheme_id: dict[str, dict[str, str | None]],
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
            batch_id=batch_id,
            result_identity_by_scheme_id=result_identity_by_scheme_id,
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
    batch_id: str,
    result_identity_by_scheme_id: dict[str, dict[str, str | None]],
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
        member = _get_session_member_record(db, session_id, user_id)
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
                    **(_read_member_texture_plan(meeting=meeting, member=member) or {}),
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
            next_texture_plan = _merge_texture_models_state(
                next_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                status_text="processing",
                models=[
                    _build_textured_model_payload(
                        result_id=str((result_identity_by_scheme_id.get(item.id) or {}).get("result_id") or _new_result_id(prefix="generated")),
                        batch_id=str((result_identity_by_scheme_id.get(item.id) or {}).get("batch_id") or batch_id),
                        source_type="generated",
                        created_at=str((result_identity_by_scheme_id.get(item.id) or {}).get("created_at") or utcnow_iso()),
                        scheme_id=item.id,
                        title=item.title,
                        prompt_text=item.prompt_text,
                        status="processing",
                        textured_model_url=None,
                        texture_maps=None,
                        edited_variant=None,
                        review_assessment=None,
                        meshy_task_id=None,
                        error_message=None,
                    )
                    for item in result.schemes
                ],
            )
            _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
            if should_persist:
                db.commit()
                db.refresh(meeting)
                db.refresh(member)

            await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)
            await emit_session_event(
                "texture_plan:updated",
                session_id,
                {
                    "texture_plan": _to_member_texture_plan_state_out(
                        session_id=session_id,
                        meeting=meeting,
                        member=member,
                    ).model_dump(mode="json")
                },
            )

            response = await _apply_texture_plan_schemes(
                db=db,
                meeting=meeting,
                member=member,
                session_id=session_id,
                review_provider=provider,
                batch_id=batch_id,
                result_identity_by_scheme_id=result_identity_by_scheme_id,
            )
            models_payload = [item.model_dump(mode="json") for item in response.models]
            final_status = "completed" if all(item.status == "completed" for item in response.models) else "failed"
            final_texture_plan = _merge_texture_models_state(
                _read_member_texture_plan(meeting=meeting, member=member) or next_texture_plan,
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                status_text=final_status,
                models=models_payload,
            )
            _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=final_texture_plan)
            if should_persist:
                db.commit()
                db.refresh(meeting)
                db.refresh(member)

            await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)
        except Exception as exc:  # noqa: BLE001
            failed_models = []
            existing = normalize_texture_plan_state(
                _read_member_texture_plan(meeting=meeting, member=member),
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
            )
            target_result_ids = {
                str(item.get("result_id") or "").strip()
                for item in result_identity_by_scheme_id.values()
                if str(item.get("result_id") or "").strip()
            }
            for item in existing.get("textured_models", []):
                if str(item.get("result_id") or "").strip() not in target_result_ids:
                    failed_models.append(item)
                    continue
                failed_models.append(
                    {
                        **item,
                        "status": "failed",
                        "error_message": str(exc),
                    }
                )
            failed_texture_plan = _set_texture_models_state(
                _read_member_texture_plan(meeting=meeting, member=member),
                brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
                status_text="failed",
                models=failed_models,
            )
            _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=failed_texture_plan)
            if should_persist:
                db.commit()
                db.refresh(meeting)
                db.refresh(member)
            await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)


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
    member = _get_session_member_record(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    return _to_member_texture_plan_state_out(session_id=session_id, meeting=meeting, member=member)


@router.get("/texture-plan/models", response_model=TextureModelsStateOut)
async def fetch_texture_models(
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    member = _get_session_member_record(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    return _to_member_texture_models_state_out(session_id=session_id, meeting=meeting, member=member)


@router.post("/texture-plan/analyze-image", response_model=TexturePlanStateOut)
async def analyze_texture_plan_image(
    session_id: int = Form(..., ge=1),
    reference_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePlanStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    member = _get_session_member_record(db, session_id, current_user.id)
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
            **(_read_member_texture_plan(meeting=meeting, member=member) or {}),
            "image_name": image_name,
            "image_content_keywords": analysis["content_keywords"],
            "image_style_keywords": analysis["style_keywords"],
            "selected_image_keywords": selected_keywords,
            "updated_at": utcnow_iso(),
        },
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )

    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    response = _to_member_texture_plan_state_out(session_id=session_id, meeting=meeting, member=member)
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
    member = _get_session_member_record(db, session_id, current_user.id)
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
    existing_texture_plan = _read_member_texture_plan(meeting=meeting, member=member)
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

    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    response = _to_member_texture_plan_state_out(session_id=session_id, meeting=meeting, member=member)
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
    member = _get_session_member_record(db, session_id, current_user.id)
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
    existing_texture_plan = _read_member_texture_plan(meeting=meeting, member=member)
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

    batch_id = _new_batch_id()
    created_at = utcnow_iso()
    placeholder_identities = {
        scheme_id: {
            "result_id": _new_result_id(prefix="generated"),
            "batch_id": batch_id,
            "created_at": created_at,
        }
        for scheme_id in ("scheme_1", "scheme_2", "scheme_3")
    }

    accepted_texture_plan = _merge_texture_models_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        status_text="queued",
        models=[
            _build_textured_model_payload(
                result_id=str(placeholder_identities[scheme_id]["result_id"]),
                batch_id=batch_id,
                source_type="generated",
                created_at=created_at,
                scheme_id=scheme_id,
                title="Queued",
                prompt_text="",
                status="pending",
                textured_model_url=None,
                texture_maps=None,
                edited_variant=None,
                review_assessment=None,
                meshy_task_id=None,
                error_message=None,
            )
            for scheme_id in ("scheme_1", "scheme_2", "scheme_3")
        ],
    )
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=accepted_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)

    background_tasks.add_task(
        _run_texture_generation_background,
        session_id=session_id,
        user_id=current_user.id,
        batch_id=batch_id,
        result_identity_by_scheme_id=placeholder_identities,
        source_text=normalized_source_text,
        document_name=document_name,
        document_text=document_text,
        image_name=image_name,
        image_content_keywords=image_content_keywords,
        image_style_keywords=image_style_keywords,
        selected_image_keywords=selected_image_keywords,
    )
    return TextureModelsStartResponse(session_id=session_id, status="accepted")


@router.post("/texture-plan/upload-textured-model", response_model=TextureModelsStateOut)
async def upload_textured_model_result(
    session_id: int = Form(..., ge=1),
    model_file: UploadFile = File(...),
    base_color_file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    member = _get_session_member_record(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    locked_base_model_reference = _resolve_locked_base_model_reference(db, meeting)
    if not locked_base_model_reference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No locked base model is available. Please lock a base model before uploading a custom textured result.",
        )

    original_filename = model_file.filename or "uploaded_textured_model.glb"
    upload_task_token = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    source_path = create_original_upload_path(
        session_id=session_id,
        task_id=upload_task_token,
        suffix=Path(original_filename).suffix.lower() or ".glb",
    )
    model_bytes = await model_file.read()
    if not model_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded textured model file is empty.")
    source_path.write_bytes(model_bytes)

    try:
        processed_model = process_uploaded_model(
            source_path=source_path,
            session_id=session_id,
            model_id=upload_task_token,
            product_category=(meeting.product_category or "industrial_other"),
            original_filename=original_filename,
        )
    except ModelProcessingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _validate_uploaded_textured_model_compatibility(
        locked_base_model=_get_locked_base_model_payload(db, meeting),
        uploaded_mapping_meta=processed_model.mapping_meta,
        uploaded_surface_area_m2=processed_model.surface_area_m2,
        uploaded_paintable_uv_pixels=processed_model.paintable_uv_pixels,
    )

    result_id = _new_result_id(prefix="uploaded")
    base_color_url, _ = await _store_uploaded_base_color_texture(
        session_id=session_id,
        result_id=result_id,
        base_color_file=base_color_file,
    )
    created_at = utcnow_iso()

    review_provider: OpenAITextImageProvider | None
    try:
        review_provider = get_openai_text_image_provider()
    except Exception:
        review_provider = None

    uploaded_payload = _build_textured_model_payload(
        result_id=result_id,
        batch_id=None,
        source_type="uploaded",
        created_at=created_at,
        scheme_id="uploaded_custom",
        title=(title or "").strip() or Path(original_filename).stem or "Uploaded Result",
        prompt_text="",
        status="completed",
        textured_model_url=processed_model.model_url,
        texture_maps={
            "base_color": base_color_url,
            "metallic": None,
            "normal": None,
            "roughness": None,
        },
        edited_variant=None,
        review_assessment=None,
        meshy_task_id=None,
        error_message=None,
    )
    uploaded_payload = await _attach_stage3_review_assessment(
        db=db,
        meeting=meeting,
        model_payload=uploaded_payload,
        texture_reference=base_color_url,
        provider=review_provider,
    )

    next_texture_plan = _merge_texture_models_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        status_text="completed",
        models=[uploaded_payload],
    )
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)
    return _to_member_texture_models_state_out(session_id=session_id, meeting=meeting, member=member)


@router.delete("/texture-plan/models/{result_id}", response_model=TextureModelsStateOut)
async def delete_textured_model_result(
    result_id: str,
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    member = _get_session_member_record(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    normalized_texture_plan = normalize_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    textured_models = list(normalized_texture_plan.get("textured_models", []))
    target_model = _get_textured_model_by_result_id(textured_models, result_id)
    if target_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected textured result was not found.")

    normalized_result_id = str(target_model.get("result_id") or "").strip()
    remaining_models = [
        item for item in textured_models if str(item.get("result_id") or "").strip() != normalized_result_id
    ]
    existing_status = str(normalized_texture_plan.get("texture_generation_status") or "idle").strip() or "idle"
    next_status = existing_status if existing_status in {"queued", "processing"} else ("completed" if remaining_models else "idle")
    next_texture_plan = {
        **normalized_texture_plan,
        "texture_generation_status": next_status,
        "textured_models": remaining_models,
        "textured_models_updated_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)

    shared_result_ids = _normalize_shared_result_ids(member.shared_result_ids_json)
    shared_ids_changed = normalized_result_id in shared_result_ids
    if shared_ids_changed:
        _replace_member_shared_result_ids(
            db,
            member=member,
            result_ids=[item for item in shared_result_ids if item != normalized_result_id],
        )
    next_stage3_refs, shared_refs_changed = _remove_result_from_stage3_shared_refs(
        meeting=meeting,
        owner_user_id=member.user_id,
        result_id=normalized_result_id,
    )
    if shared_refs_changed:
        _update_session_state(db, meeting, stage3_shared_refs_json=next_stage3_refs)

    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)
    if shared_ids_changed:
        await _emit_session_members_updated(session_id=session_id)
    return _to_member_texture_models_state_out(session_id=session_id, meeting=meeting, member=member)


@router.post("/texture-plan/share-results", response_model=ShareTextureResultsResponse)
async def share_texture_results(
    payload: ShareTextureResultsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShareTextureResultsResponse:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    member = _get_session_member_record(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    completed_result_ids = {
        str(item.get("result_id") or "").strip()
        for item in _get_member_textured_models(meeting=meeting, member=member)
        if str(item.get("status") or "").strip().lower() == "completed"
    }
    requested_result_ids = _normalize_shared_result_ids(payload.result_ids)
    invalid_result_ids = [item for item in requested_result_ids if item not in completed_result_ids]
    if invalid_result_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed results from your current workspace can be shared.",
        )

    shared_result_ids = _replace_member_shared_result_ids(db, member=member, result_ids=requested_result_ids)
    if should_persist:
        db.commit()
        db.refresh(member)

    await _emit_session_members_updated(session_id=payload.session_id)
    return ShareTextureResultsResponse(
        session_id=payload.session_id,
        shared_result_ids=shared_result_ids,
        updated_at=utcnow_iso(),
    )


@router.get("/texture-plan/shared-results", response_model=SharedTextureResultsResponse)
async def fetch_shared_texture_results(
    session_id: int = Query(..., ge=1),
    member_user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SharedTextureResultsResponse:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    source_member = _get_session_member_record(db, session_id, member_user_id)
    source_models = _build_shared_models_for_member(meeting=meeting, member=source_member)
    source_user = db.execute(select(User).where(User.id == source_member.user_id)).scalar_one_or_none()
    source_name = source_user.name if source_user is not None else f"Member {source_member.user_id}"
    source_workspace = normalize_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=source_member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    return SharedTextureResultsResponse(
        session_id=session_id,
        source_user_id=source_member.user_id,
        source_user_name=source_name,
        models=[TexturedModelOut(**item) for item in source_models],
        updated_at=str(source_workspace.get("textured_models_updated_at") or utcnow_iso()),
    )


@router.get("/texture-plan/stage3-shared-models", response_model=TextureModelsStateOut)
async def fetch_stage3_shared_texture_models(
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    models, updated_at = _build_stage3_shared_models_for_meeting(db=db, meeting=meeting)
    return TextureModelsStateOut(
        session_id=session_id,
        status="completed" if models else "idle",
        models=[TexturedModelOut(**item) for item in models],
        updated_at=updated_at,
    )


@router.post("/texture-plan/import-shared-results", response_model=TextureModelsStateOut)
async def import_shared_texture_results(
    payload: ImportSharedTextureResultsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    member = _get_session_member_record(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    if payload.source_user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot import your own shared results.")

    source_member = _get_session_member_record(db, payload.session_id, payload.source_user_id)
    source_user = db.execute(select(User).where(User.id == source_member.user_id)).scalar_one_or_none()
    source_name = source_user.name if source_user is not None else f"Member {source_member.user_id}"
    shared_models = _build_shared_models_for_member(meeting=meeting, member=source_member)
    shared_by_result_id = {
        str(item.get("result_id") or "").strip(): item
        for item in shared_models
        if str(item.get("result_id") or "").strip()
    }
    requested_result_ids = _normalize_shared_result_ids(payload.result_ids)
    if not requested_result_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one shared result to import.")
    missing_result_ids = [item for item in requested_result_ids if item not in shared_by_result_id]
    if missing_result_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more requested shared results are no longer available.",
        )

    target_workspace = normalize_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    imported_models: list[dict[str, Any]] = []
    import_timestamp = utcnow_iso()
    for source_result_id in requested_result_ids:
        source_model = shared_by_result_id[source_result_id]
        family_id = str(source_model.get("family_id") or source_result_id).strip() or source_result_id
        imported_models.append(
            {
                **json.loads(json.dumps(source_model)),
                "result_id": _new_result_id(prefix="imported"),
                "batch_id": None,
                "source_type": "imported",
                "created_at": import_timestamp,
                "family_id": family_id,
                "parent_result_id": source_result_id,
                "shared_origin": {
                    "user_id": source_member.user_id,
                    "user_name": source_name,
                    "source_result_id": source_result_id,
                },
            }
        )

    existing_status = str(target_workspace.get("texture_generation_status") or "idle")
    next_status = existing_status if existing_status in {"queued", "processing"} else "completed"
    next_texture_plan = _merge_texture_models_state(
        target_workspace,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        status_text=next_status,
        models=imported_models,
    )
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    await _emit_member_texture_models_updated(session_id=payload.session_id, meeting=meeting, member=member)
    return _to_member_texture_models_state_out(session_id=payload.session_id, meeting=meeting, member=member)


@router.patch("/texture-plan", response_model=TexturePlanStateOut)
async def patch_texture_plan(
    payload: TexturePlanPatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePlanStateOut:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    member = _get_session_member_record(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    if payload.selected_image_keywords is None and not payload.clear_document and not payload.clear_image:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No texture plan changes were provided.")

    next_texture_plan = patch_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        selected_image_keywords=payload.selected_image_keywords,
        clear_document=payload.clear_document,
        clear_image=payload.clear_image,
    )
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    response = _to_member_texture_plan_state_out(session_id=payload.session_id, meeting=meeting, member=member)
    await emit_session_event(
        "texture_plan:updated",
        payload.session_id,
        {"texture_plan": response.model_dump(mode="json")},
    )
    return response


@router.post("/texture-plan/refresh-review", response_model=TextureModelsStateOut)
async def refresh_texture_review(
    payload: RefreshTextureReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    member = _get_session_member_record(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    normalized_texture_plan = normalize_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    textured_models = list(normalized_texture_plan.get("textured_models", []))
    if not textured_models:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No textured model results are available yet.")

    target_result_id = (payload.result_id or "").strip() or None
    initial_cleared_models: list[dict[str, Any]] = []
    refreshable_count = 0
    for item in textured_models:
        if target_result_id and item.get("result_id") != target_result_id:
            initial_cleared_models.append(item)
            continue
        if (item.get("status") or "") != "completed":
            initial_cleared_models.append(item)
            continue
        initial_cleared_models.append({**item, "review_assessment": None})
        refreshable_count += 1

    if refreshable_count == 0:
        if target_result_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed textured model matched the requested result for review refresh.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No completed textured model results are available to refresh review.",
        )

    try:
        review_provider = get_openai_text_image_provider()
    except ModelProviderNotConfiguredError as exc:
        next_texture_plan = {
            **normalized_texture_plan,
            "textured_models": initial_cleared_models,
            "textured_models_updated_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
        }
        _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
        if should_persist:
            db.commit()
            db.refresh(meeting)
            db.refresh(member)
        await _emit_member_texture_models_updated(session_id=payload.session_id, meeting=meeting, member=member)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    updated_models: list[dict[str, Any]] = []
    refreshed_count = 0
    failed_messages: list[str] = []
    for item in textured_models:
        if target_result_id and item.get("result_id") != target_result_id:
            updated_models.append(item)
            continue
        if (item.get("status") or "") != "completed":
            updated_models.append(item)
            continue

        cleared_item = {**item, "review_assessment": None}
        texture_reference = _resolve_review_texture_reference(item)
        refreshed_item = await _attach_stage3_review_assessment(
            db=db,
            meeting=meeting,
            model_payload=cleared_item,
            texture_reference=texture_reference,
            provider=review_provider,
        )
        review_assessment = refreshed_item.get("review_assessment")
        review_status = (
            str(review_assessment.get("status") or "").strip().lower()
            if isinstance(review_assessment, dict)
            else ""
        )
        review_source = (
            str(review_assessment.get("source") or "").strip().lower()
            if isinstance(review_assessment, dict)
            else ""
        )
        if review_status == "completed" and review_source == "llm":
            updated_models.append(refreshed_item)
            refreshed_count += 1
            continue

        updated_models.append(cleared_item)
        failure_message = (
            str(review_assessment.get("error_message") or "").strip()
            if isinstance(review_assessment, dict)
            else ""
        )
        failed_messages.append(
            failure_message or f"Review failed for {(item.get('title') or item.get('result_id') or 'selected result')}."
        )

    next_texture_plan = {
        **normalized_texture_plan,
        "textured_models": updated_models,
        "textured_models_updated_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    await _emit_member_texture_models_updated(session_id=payload.session_id, meeting=meeting, member=member)
    if failed_messages:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=failed_messages[0],
        )
    return _to_member_texture_models_state_out(session_id=payload.session_id, meeting=meeting, member=member)


@router.post("/texture-plan/apply-edited-texture", response_model=TextureModelsStateOut)
async def apply_edited_texture(
    session_id: int = Form(..., ge=1),
    result_id: str = Form(...),
    edited_base_color: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TextureModelsStateOut:
    meeting = _ensure_member(db, session_id, current_user.id)
    member = _get_session_member_record(db, session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, session_id)

    normalized_texture_plan = normalize_texture_plan_state(
        _read_member_texture_plan(meeting=meeting, member=member),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    textured_models = list(normalized_texture_plan.get("textured_models", []))
    target_model = _get_textured_model_by_result_id(textured_models, result_id)
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
            scheme_id=str(target_model.get("scheme_id") or result_id),
            base_model_reference=application_model_reference,
            edited_base_color_bytes=edited_base_color_bytes,
            texture_maps=texture_maps,
            meshy_task_id=target_model.get("meshy_task_id"),
        )
    except ModelTexturingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    review_provider: OpenAITextImageProvider | None
    try:
        review_provider = get_openai_text_image_provider()
    except Exception:
        review_provider = None

    updated_models: list[dict[str, Any]] = []
    for item in textured_models:
        if item.get("result_id") != result_id:
            updated_models.append(item)
            continue
        updated_item = {
            **item,
            "edited_variant": EditedTextureVariantOut(
                model_url=edited_result.model_url,
                base_color_url=edited_result.base_color_url,
                applied_at=edited_result.applied_at,
            ).model_dump(mode="json"),
        }
        updated_models.append(
            await _attach_stage3_review_assessment(
                db=db,
                meeting=meeting,
                model_payload=updated_item,
                texture_reference=edited_result.base_color_url,
                provider=review_provider,
            )
        )

    next_texture_plan = {
        **normalized_texture_plan,
        "textured_models": updated_models,
        "textured_models_updated_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }
    _write_member_texture_plan(db, meeting=meeting, member=member, texture_plan_json=next_texture_plan)
    if should_persist:
        db.commit()
        db.refresh(meeting)
        db.refresh(member)

    await _emit_member_texture_models_updated(session_id=session_id, meeting=meeting, member=member)
    return _to_member_texture_models_state_out(session_id=session_id, meeting=meeting, member=member)


@router.post("/texture-plan/apply-texture", response_model=ApplyTextureResponse)
async def apply_texture(
    payload: ApplyTextureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplyTextureResponse:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    member = _get_session_member_record(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    try:
        review_provider: OpenAITextImageProvider | None = get_openai_text_image_provider()
    except Exception:
        review_provider = None
    return await _apply_texture_plan_schemes(
        db=db,
        meeting=meeting,
        member=member,
        session_id=payload.session_id,
        review_provider=review_provider,
    )


@router.post("/texture-plan/generate-pattern", response_model=TexturePatternGenerateResponse)
async def generate_texture_pattern(
    payload: TexturePatternGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TexturePatternGenerateResponse:
    meeting = _ensure_member(db, payload.session_id, current_user.id)
    member = _get_session_member_record(db, payload.session_id, current_user.id)
    _apply_effective_session_state(db, meeting)
    should_persist = _should_persist_session_data(db, payload.session_id)

    texture_plan_json = _read_member_texture_plan(meeting=meeting, member=member)
    normalized = normalize_texture_plan_state(
        texture_plan_json,
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
    )
    textured_models = list(normalized.get("textured_models", []))
    target_model = _get_textured_model_by_result_id(textured_models, payload.result_id)
    if target_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected textured result was not found.")

    texture_reference, resolved_preview_mode = _resolve_pattern_texture_reference(
        target_model=target_model,
        preview_mode=payload.preview_mode,
    )
    if not texture_reference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected textured result does not expose a usable base color texture.",
        )

    try:
        pattern_provider = get_pattern_image_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    pattern_agent = get_pattern_asset_agent()
    context = PatternAssetContext(
        session_id=payload.session_id,
        result_id=str(target_model.get("result_id") or payload.result_id),
        preview_mode=resolved_preview_mode,
        workspace_id=payload.workspace_id,
        pattern_prompt_text=str(payload.pattern_prompt_text or "").strip(),
        brief_json=meeting.brief_json if isinstance(meeting.brief_json, dict) else None,
        brief_keywords=dict(normalized.get("brief_keywords") or {}),
        selected_image_keywords=list(normalized.get("selected_image_keywords") or []),
        texture_prompt_text=str(target_model.get("prompt_text") or ""),
        texture_reference=texture_reference,
        canvas_snapshot_data_url=str(payload.canvas_snapshot_data_url or "").strip() or None,
    )

    try:
        generated = await pattern_agent.generate_pattern_asset(provider=pattern_provider, context=context)
    except ModelProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not should_persist:
        transient_item = GeneratedImageOut(
            id=-1,
            session_id=payload.session_id,
            prompt=generated.prompt,
            style_hint=generated.style_hint,
            revised_prompt=generated.revised_prompt,
            image_url=generated.image_url,
            created_at=datetime.now(timezone.utc),
        )
        return TexturePatternGenerateResponse(
            item=transient_item,
            analysis_summary=generated.analysis_summary,
            dominant_colors=generated.dominant_colors,
            source_result_id=context.result_id,
            pattern_prompt_text=context.pattern_prompt_text or None,
        )

    row = GeneratedImage(
        session_id=payload.session_id,
        user_id=current_user.id,
        prompt=generated.prompt,
        style_hint=generated.style_hint,
        revised_prompt=generated.revised_prompt,
        image_url=generated.image_url,
        provider="openai_compatible",
        model_name=pattern_provider.image_model,
        metadata_json={
            "kind": "pattern_asset",
            "source_result_id": context.result_id,
            "workspace_id": payload.workspace_id,
            "preview_mode": resolved_preview_mode,
            "pattern_prompt_text": context.pattern_prompt_text or None,
            "canvas_snapshot_used": bool(context.canvas_snapshot_data_url),
            "analysis": {
                "analysis_summary": generated.analysis_summary,
                "dominant_colors": generated.dominant_colors,
            },
            "provider_payload": generated.provider_payload,
        },
    )
    db.add(row)
    db.flush()
    db.add(
        AiMessage(
            session_id=payload.session_id,
            user_id=None,
            role="assistant",
            mode="image",
            content=f"Generated 1 pattern asset for textured result {context.result_id}.",
            metadata_json={"generated_image_ids": [row.id], "kind": "pattern_asset"},
        )
    )
    db.commit()
    db.refresh(row)

    item = GeneratedImageOut(
        id=row.id,
        session_id=row.session_id,
        prompt=row.prompt,
        style_hint=row.style_hint,
        revised_prompt=row.revised_prompt,
        image_url=row.image_url,
        created_at=row.created_at,
    )
    return TexturePatternGenerateResponse(
        item=item,
        analysis_summary=generated.analysis_summary,
        dominant_colors=generated.dominant_colors,
        source_result_id=context.result_id,
        pattern_prompt_text=context.pattern_prompt_text or None,
    )


@router.get("/stage4/media", response_model=Stage4MediaListResponse)
async def list_stage4_media(
    session_id: int = Query(...),
    result_id: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Stage4MediaListResponse:
    _ensure_member(db, session_id, current_user.id)
    can_manage_all_stage4_media = _is_host(db, session_id, current_user.id)
    query = select(GeneratedMediaAsset).where(GeneratedMediaAsset.session_id == session_id)
    normalized_result_id = result_id.strip() if result_id else None
    if normalized_result_id:
        query = query.where(GeneratedMediaAsset.result_id == normalized_result_id)
    rows = db.execute(query.order_by(GeneratedMediaAsset.created_at.desc(), GeneratedMediaAsset.id.desc())).scalars().all()
    return Stage4MediaListResponse(
        session_id=session_id,
        result_id=normalized_result_id,
        items=[
            _to_generated_media_asset_out(
                row,
                can_delete=can_manage_all_stage4_media or row.user_id == current_user.id,
            )
            for row in rows
        ],
    )


@router.delete("/stage4/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage4_media(
    asset_id: int,
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _ensure_member(db, session_id, current_user.id)
    media_row = db.execute(
        select(GeneratedMediaAsset).where(
            GeneratedMediaAsset.id == asset_id,
            GeneratedMediaAsset.session_id == session_id,
        )
    ).scalar_one_or_none()
    if media_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage 4 media asset was not found.")

    if media_row.user_id != current_user.id and not _is_host(db, session_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to delete this Stage 4 media asset.")

    media_urls_to_cleanup = {media_row.media_url}
    generated_image_id = _extract_stage4_generated_image_id(media_row)
    generated_image_row: GeneratedImage | None = None
    if generated_image_id is not None:
        generated_image_row = db.execute(
            select(GeneratedImage).where(
                GeneratedImage.id == generated_image_id,
                GeneratedImage.session_id == session_id,
            )
        ).scalar_one_or_none()
        if generated_image_row is not None:
            media_urls_to_cleanup.add(generated_image_row.image_url)
            db.delete(generated_image_row)

    db.delete(media_row)
    db.commit()
    _cleanup_stage4_media_files_if_unused(db, media_urls_to_cleanup)


@router.post("/stage4/scene-image", response_model=Stage4SceneImageGenerateResponse)
async def generate_stage4_scene_image(
    payload: Stage4SceneImageGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Stage4SceneImageGenerateResponse:
    _ensure_member(db, payload.session_id, current_user.id)
    should_persist = _should_persist_session_data(db, payload.session_id)
    screenshot_data_url = payload.screenshot_data_url.strip()
    if not screenshot_data_url.startswith("data:image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stage 4 screenshot must be an image data URL.",
        )

    try:
        provider = get_aihubmix_media_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    context = Stage4MediaContext(
        session_id=payload.session_id,
        result_id=payload.result_id.strip() if payload.result_id else None,
        scheme_name=payload.scheme_name.strip() if payload.scheme_name else None,
        screenshot_data_url=screenshot_data_url,
        image_prompt=payload.image_prompt,
        video_prompt="",
    )

    try:
        generated = await get_stage4_media_agent().generate_scene_image(provider=provider, context=context)
    except ModelProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    image_output_url = await _stage4_media_url_for_storage(
        session_id=payload.session_id,
        media_url=generated.image_url,
        media_type="image",
    )
    created_image: GeneratedImageOut | None = None
    media_asset: GeneratedMediaAssetOut | None = None
    if should_persist:
        image_row: GeneratedImage | None = None
        media_row: GeneratedMediaAsset | None = None
        if len(image_output_url) <= 3900:
            image_row = GeneratedImage(
                session_id=payload.session_id,
                user_id=current_user.id,
                prompt=generated.image_prompt,
                style_hint=None,
                revised_prompt=None,
                image_url=image_output_url,
                provider="aihubmix",
                model_name=provider.image_model,
                metadata_json={
                    "kind": "stage4_scene_image",
                    "source_result_id": context.result_id,
                    "scheme_name": context.scheme_name,
                    "image_prediction_id": generated.image_prediction_id,
                    "screenshot_data_url_used": True,
                },
            )
            db.add(image_row)
            db.flush()
            media_row = GeneratedMediaAsset(
                session_id=payload.session_id,
                user_id=current_user.id,
                result_id=context.result_id,
                scheme_name=context.scheme_name,
                media_type="image",
                media_url=image_output_url,
                prompt=generated.image_prompt,
                provider="aihubmix",
                model_name=provider.image_model,
                prediction_id=generated.image_prediction_id,
                source_image_url=None,
                metadata_json={
                    "kind": "stage4_scene_image",
                    "generated_image_id": image_row.id,
                    "screenshot_data_url_used": True,
                },
            )
            db.add(media_row)
            db.flush()
        db.add(
            AiMessage(
                session_id=payload.session_id,
                user_id=None,
                role="assistant",
                mode="image",
                content="Generated Stage 4 running-scene image preview.",
                metadata_json={
                    "kind": "stage4_scene_image",
                    "generated_image_ids": [image_row.id] if image_row else [],
                    "generated_media_asset_id": media_row.id if media_row else None,
                    "source_result_id": context.result_id,
                    "image_url_omitted": image_row is None,
                },
            )
        )
        db.commit()
        if image_row is not None:
            db.refresh(image_row)
            created_image = GeneratedImageOut(
                id=image_row.id,
                session_id=image_row.session_id,
                prompt=image_row.prompt,
                style_hint=image_row.style_hint,
                revised_prompt=image_row.revised_prompt,
                image_url=image_row.image_url,
                created_at=image_row.created_at,
            )
        if media_row is not None:
            db.refresh(media_row)
            media_asset = _to_generated_media_asset_out(media_row, can_delete=True)

    return Stage4SceneImageGenerateResponse(
        session_id=payload.session_id,
        result_id=context.result_id,
        image_url=image_output_url,
        image_prediction_id=generated.image_prediction_id,
        image_prompt=generated.image_prompt,
        created_image=created_image,
        media_asset=media_asset,
    )


@router.post("/stage4/scene-video", response_model=Stage4SceneVideoGenerateResponse)
async def generate_stage4_scene_video(
    payload: Stage4SceneVideoGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Stage4SceneVideoGenerateResponse:
    _ensure_member(db, payload.session_id, current_user.id)
    should_persist = _should_persist_session_data(db, payload.session_id)
    if not payload.image_url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stage 4 scene image is required before generating video.",
        )
    source_image_url = payload.image_url.strip()
    provider_image_url = _stage4_video_reference_image_url(source_image_url)

    try:
        provider = get_aihubmix_media_provider()
    except ModelProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    context = Stage4MediaContext(
        session_id=payload.session_id,
        result_id=payload.result_id.strip() if payload.result_id else None,
        scheme_name=payload.scheme_name.strip() if payload.scheme_name else None,
        image_prompt="",
        video_prompt=payload.video_prompt,
        image_url=provider_image_url,
        duration=payload.duration,
        resolution=payload.resolution,
        generate_audio=payload.generate_audio,
    )

    try:
        generated = await get_stage4_media_agent().generate_scene_video(provider=provider, context=context)
    except ModelProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    video_output_url = await _stage4_media_url_for_storage(
        session_id=payload.session_id,
        media_url=generated.video_url,
        media_type="video",
    )

    media_asset: GeneratedMediaAssetOut | None = None
    if should_persist:
        media_row: GeneratedMediaAsset | None = None
        if len(video_output_url) <= 3900:
            media_row = GeneratedMediaAsset(
                session_id=payload.session_id,
                user_id=current_user.id,
                result_id=context.result_id,
                scheme_name=context.scheme_name,
                media_type="video",
                media_url=video_output_url,
                prompt=generated.video_prompt,
                provider="aihubmix",
                model_name=provider.video_model,
                prediction_id=generated.video_prediction_id,
                source_image_url=source_image_url,
                metadata_json={
                    "kind": "stage4_scene_video",
                    "duration": context.duration,
                    "resolution": context.resolution,
                    "generate_audio": context.generate_audio,
                    "source_image_embedded": provider_image_url.startswith("data:image/") and provider_image_url != source_image_url,
                },
            )
            db.add(media_row)
            db.flush()
        db.add(
            AiMessage(
                session_id=payload.session_id,
                user_id=None,
                role="assistant",
                mode="video",
                content="Generated Stage 4 running-scene video preview.",
                metadata_json={
                    "kind": "stage4_scene_video",
                    "video_url": video_output_url,
                    "video_prediction_id": generated.video_prediction_id,
                    "generated_media_asset_id": media_row.id if media_row else None,
                    "source_result_id": context.result_id,
                    "source_image_url": source_image_url,
                    "source_image_embedded": provider_image_url.startswith("data:image/") and provider_image_url != source_image_url,
                    "resolution": context.resolution,
                },
            )
        )
        db.commit()
        if media_row is not None:
            db.refresh(media_row)
            media_asset = _to_generated_media_asset_out(media_row, can_delete=True)

    return Stage4SceneVideoGenerateResponse(
        session_id=payload.session_id,
        result_id=context.result_id,
        video_url=video_output_url,
        video_prediction_id=generated.video_prediction_id,
        video_prompt=generated.video_prompt,
        media_asset=media_asset,
    )


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
