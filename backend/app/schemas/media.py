from typing import Literal

from pydantic import BaseModel

MeetingRole = Literal["host", "designer", "observer"]


class IceConfigResponse(BaseModel):
    ice_servers: list[dict[str, str]]

