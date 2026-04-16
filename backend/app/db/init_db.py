from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base
from app.db.models import MeetingSession, ModelAsset, SessionMember, User
from app.db.session import engine


def _ensure_sessions_columns(db: Session) -> None:
    inspector = inspect(engine)
    columns = {item['name'] for item in inspector.get_columns('sessions')}

    if 'design_goal_text' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN design_goal_text TEXT'))
    if 'product_category' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN product_category VARCHAR(50)'))
    if 'product_profile' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN product_profile TEXT'))
    if 'brief_json' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN brief_json TEXT'))
    if 'texture_plan_json' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN texture_plan_json TEXT'))
    if 'base_model_id' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN base_model_id INTEGER'))
    if 'model_locked_at' not in columns:
        db.execute(text('ALTER TABLE sessions ADD COLUMN model_locked_at DATETIME'))
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
        select(ModelAsset).where(ModelAsset.source_type == 'library', ModelAsset.session_id.is_(None))
    ).scalars()
    by_name = {item.name: item for item in existing}

    presets = [
        {
            'name': 'Rail Standard Model A',
            'precision_level': 'standard',
            'license_scope': 'internal',
            'export_glb_allowed': True,
            'model_url': '/files/models/library_train_a.glb',
            'uv_template_url': '/files/uv/library_train_a.png',
            'surface_area_m2': 312.4,
            'paintable_uv_pixels': 4096 * 2048,
        },
        {
            'name': 'Rail Standard Model B',
            'precision_level': 'standard',
            'license_scope': 'internal',
            'export_glb_allowed': False,
            'model_url': '/files/models/library_train_b.glb',
            'uv_template_url': '/files/uv/library_train_b.png',
            'surface_area_m2': 305.1,
            'paintable_uv_pixels': 4096 * 2048,
        },
        {
            'name': 'Car Standard Model A',
            'precision_level': 'standard',
            'license_scope': 'internal',
            'export_glb_allowed': True,
            'model_url': '/files/models/library_auto_a.glb',
            'uv_template_url': '/files/uv/library_auto_a.png',
            'surface_area_m2': 52.8,
            'paintable_uv_pixels': 2048 * 1024,
        },
    ]

    created = False
    for preset in presets:
        if preset['name'] in by_name:
            continue
        db.add(
            ModelAsset(
                name=preset['name'],
                session_id=None,
                source_type='library',
                precision_level=preset['precision_level'],
                license_scope=preset['license_scope'],
                export_glb_allowed=preset['export_glb_allowed'],
                model_url=preset['model_url'],
                uv_template_url=preset['uv_template_url'],
                surface_area_m2=preset['surface_area_m2'],
                paintable_uv_pixels=preset['paintable_uv_pixels'],
                mapping_meta={'mesh_to_region': {'body': 'body'}},
            )
        )
        created = True

    if created:
        db.commit()

def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        _ensure_sessions_columns(db)
        _ensure_model_generation_task_columns(db)

        host_user = db.execute(select(User).where(User.email == 'host@co-track.local')).scalar_one_or_none()
        if host_user is None:
            host_user = User(
                email='host@co-track.local',
                name='Host',
                password_hash=hash_password('Host@123456'),
            )
            db.add(host_user)
            db.flush()

        default_session = db.execute(
            select(MeetingSession).where(MeetingSession.invite_code == '555555')
        ).scalar_one_or_none()

        if default_session is None:
            default_session = MeetingSession(
                name='Co-Track Default Session',
                invite_code='555555',
                creator_id=host_user.id,
                stage='LOBBY',
                product_category='high_speed_train',
                product_profile={},
            )
            db.add(default_session)
            db.flush()
        else:
            if not default_session.name:
                default_session.name = 'Co-Track Default Session'

        host_member = db.execute(
            select(SessionMember).where(
                SessionMember.session_id == default_session.id,
                SessionMember.user_id == host_user.id,
            )
        ).scalar_one_or_none()
        if host_member is None:
            db.add(SessionMember(session_id=default_session.id, user_id=host_user.id, role='host'))

        db.commit()
        _ensure_library_assets(db)


