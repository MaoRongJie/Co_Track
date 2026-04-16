from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.schemas.media import IceConfigResponse

router = APIRouter()


@router.get("/config", response_model=IceConfigResponse)
def get_rtc_config(_user: User = Depends(get_current_user)) -> IceConfigResponse:
    settings = get_settings()
    return IceConfigResponse(ice_servers=settings.rtc_ice_servers)

