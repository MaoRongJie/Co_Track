from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base
from app.db.models import MeetingSession, ModelAsset, SessionMember, User
from app.db.session import engine


def _ensure_sessions_columns(db: Session) -> None:
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns("sessions")}

    if "design_goal_text" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN design_goal_text TEXT"))
    if "product_category" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN product_category VARCHAR(50)"))
    if "product_profile" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN product_profile TEXT"))
    if "brief_json" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN brief_json TEXT"))
    if "texture_plan_json" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN texture_plan_json TEXT"))
    if "session_settings_json" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN session_settings_json TEXT"))
    if "stage3_shared_refs_json" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN stage3_shared_refs_json TEXT"))
    if "base_model_id" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN base_model_id INTEGER"))
    if "model_locked_at" not in columns:
        db.execute(text("ALTER TABLE sessions ADD COLUMN model_locked_at DATETIME"))
    db.commit()


def _ensure_session_members_columns(db: Session) -> None:
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns("session_members")}

    if "workspace_json" not in columns:
        db.execute(text("ALTER TABLE session_members ADD COLUMN workspace_json TEXT"))
    if "shared_result_ids_json" not in columns:
        db.execute(text("ALTER TABLE session_members ADD COLUMN shared_result_ids_json TEXT"))
    db.commit()


def _ensure_model_generation_task_columns(db: Session) -> None:
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns("model_generation_tasks")}

    if "task_type" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN task_type VARCHAR(20)"))
    if "generation_plan_json" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN generation_plan_json TEXT"))
    if "pipeline_stage" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN pipeline_stage VARCHAR(40)"))
    if "progress_message" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN progress_message VARCHAR(255)"))
    if "error_detail" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN error_detail TEXT"))
    if "provider_route" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN provider_route VARCHAR(20)"))
    if "provider_task_id" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN provider_task_id VARCHAR(120)"))
    if "original_filename" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN original_filename VARCHAR(255)"))
    if "source_path" not in columns:
        db.execute(text("ALTER TABLE model_generation_tasks ADD COLUMN source_path VARCHAR(1000)"))
    db.commit()


def _ensure_library_assets(db: Session) -> None:
    existing = db.execute(
        select(ModelAsset).where(ModelAsset.source_type == "library", ModelAsset.session_id.is_(None))
    ).scalars()
    by_name = {item.name: item for item in existing}

    presets = [
        {
            "name": "Rail Standard Model A",
            "precision_level": "standard",
            "license_scope": "internal",
            "export_glb_allowed": True,
            "model_url": "/files/models/library_train_a.glb",
            "uv_template_url": "/files/uv/library_train_a.png",
            "surface_area_m2": 312.4,
            "paintable_uv_pixels": 4096 * 2048,
        },
        {
            "name": "Rail Standard Model B",
            "precision_level": "standard",
            "license_scope": "internal",
            "export_glb_allowed": False,
            "model_url": "/files/models/library_train_b.glb",
            "uv_template_url": "/files/uv/library_train_b.png",
            "surface_area_m2": 305.1,
            "paintable_uv_pixels": 4096 * 2048,
        },
        {
            "name": "Car Standard Model A",
            "precision_level": "standard",
            "license_scope": "internal",
            "export_glb_allowed": True,
            "model_url": "/files/models/library_auto_a.glb",
            "uv_template_url": "/files/uv/library_auto_a.png",
            "surface_area_m2": 52.8,
            "paintable_uv_pixels": 2048 * 1024,
        },
    ]

    created = False
    for preset in presets:
        if preset["name"] in by_name:
            continue
        db.add(
            ModelAsset(
                name=preset["name"],
                session_id=None,
                source_type="library",
                precision_level=preset["precision_level"],
                license_scope=preset["license_scope"],
                export_glb_allowed=preset["export_glb_allowed"],
                model_url=preset["model_url"],
                uv_template_url=preset["uv_template_url"],
                surface_area_m2=preset["surface_area_m2"],
                paintable_uv_pixels=preset["paintable_uv_pixels"],
                mapping_meta={"mesh_to_region": {"body": "body"}},
            )
        )
        created = True

    if created:
        db.commit()


def _normalize_member_name(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


def _role_priority(role: str | None) -> int:
    normalized = (role or "").strip().lower()
    if normalized == "host":
        return 0
    if normalized == "designer":
        return 1
    return 2


def _workspace_sort_key(value: object) -> tuple[str, int]:
    if not isinstance(value, dict):
        return ("", 0)
    updated_at = str(value.get("updated_at") or "").strip()
    return (updated_at, 1 if value else 0)


def _dedupe_result_ids(*values: list[str] | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value or []:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _ensure_default_session(
    db: Session,
    *,
    host_user: User,
    invite_code: str,
    name: str,
) -> MeetingSession:
    session = db.execute(
        select(MeetingSession).where(MeetingSession.invite_code == invite_code)
    ).scalar_one_or_none()

    if session is None:
        session = MeetingSession(
            name=name,
            invite_code=invite_code,
            creator_id=host_user.id,
            stage="LOBBY",
            product_category="high_speed_train",
            product_profile={},
        )
        db.add(session)
        db.flush()
    elif not session.name:
        session.name = name

    host_member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session.id,
            SessionMember.user_id == host_user.id,
        )
    ).scalar_one_or_none()
    if host_member is None:
        db.add(SessionMember(session_id=session.id, user_id=host_user.id, role="host"))
    else:
        host_member.role = "host"
    db.flush()
    return session


def _merge_duplicate_members_by_name(db: Session, meeting: MeetingSession) -> None:
    member_rows = db.execute(
        select(SessionMember, User)
        .join(User, User.id == SessionMember.user_id)
        .where(SessionMember.session_id == meeting.id)
        .order_by(SessionMember.joined_at.asc(), SessionMember.id.asc())
    ).all()

    grouped: dict[str, list[tuple[SessionMember, User]]] = {}
    for session_member, user in member_rows:
        normalized_name = _normalize_member_name(user.name)
        if not normalized_name:
            continue
        grouped.setdefault(normalized_name, []).append((session_member, user))

    shared_refs = list(meeting.stage3_shared_refs_json or [])
    changed = False

    for rows in grouped.values():
        if len(rows) <= 1:
            continue

        sorted_rows = sorted(
            rows,
            key=lambda item: (
                _role_priority(item[0].role),
                item[0].joined_at,
                item[0].id,
            ),
        )
        canonical_member, canonical_user = sorted_rows[0]
        duplicates = sorted_rows[1:]
        duplicate_user_ids = {member.user_id for member, _ in duplicates}

        canonical_member.shared_result_ids_json = _dedupe_result_ids(
            canonical_member.shared_result_ids_json,
            *[member.shared_result_ids_json for member, _ in duplicates],
        ) or None

        workspace_candidates = [
            member.workspace_json
            for member, _ in sorted_rows
            if isinstance(member.workspace_json, dict) and member.workspace_json
        ]
        if workspace_candidates:
            canonical_member.workspace_json = max(workspace_candidates, key=_workspace_sort_key)

        if duplicate_user_ids:
            next_refs: list[dict[str, object]] = []
            seen_refs: set[tuple[int, str]] = set()
            for item in shared_refs:
                if not isinstance(item, dict):
                    continue
                owner_user_id = int(item.get("owner_user_id") or 0)
                result_id = str(item.get("result_id") or "").strip()
                if owner_user_id in duplicate_user_ids:
                    owner_user_id = canonical_user.id
                dedupe_key = (owner_user_id, result_id)
                if owner_user_id <= 0 or not result_id or dedupe_key in seen_refs:
                    continue
                seen_refs.add(dedupe_key)
                next_refs.append(
                    {
                        **item,
                        "owner_user_id": owner_user_id,
                    }
                )
            shared_refs = next_refs

        for duplicate_member, _ in duplicates:
            db.delete(duplicate_member)
        changed = True

    if changed:
        meeting.stage3_shared_refs_json = shared_refs or None
        db.flush()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        _ensure_sessions_columns(db)
        _ensure_session_members_columns(db)
        _ensure_model_generation_task_columns(db)

        host_user = db.execute(select(User).where(User.email == "host@co-track.local")).scalar_one_or_none()
        if host_user is None:
            host_user = User(
                email="host@co-track.local",
                name="Host",
                password_hash=hash_password("Host@123456"),
            )
            db.add(host_user)
            db.flush()

        default_session = _ensure_default_session(
            db,
            host_user=host_user,
            invite_code="555555",
            name="Co-Track Default Session",
        )
        sandbox_session = _ensure_default_session(
            db,
            host_user=host_user,
            invite_code="666666",
            name="Co-Track Clean Session 666666",
        )
        extra_session = _ensure_default_session(
            db,
            host_user=host_user,
            invite_code="777777",
            name="Co-Track 777777",
        )

        _merge_duplicate_members_by_name(db, default_session)
        _merge_duplicate_members_by_name(db, sandbox_session)
        _merge_duplicate_members_by_name(db, extra_session)

        db.commit()
        _ensure_library_assets(db)
