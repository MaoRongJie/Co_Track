from pathlib import Path
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "co_track.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Co-Track Backend"
    secret_key: str = "replace_with_secure_secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")
    cors_origin_regex: str = Field(
        default=(
            r"^https?://("
            r"localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0|"
            r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3}"
            r")(:\d+)?$"
        )
    )

    rtc_stun_url: str = "stun:stun.l.google.com:19302"
    rtc_turn_url: str = ""
    rtc_turn_username: str = ""
    rtc_turn_password: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_text_model: str = "gpt-4.1-free"
    openai_vision_model: str = "gpt-4.1-free"
    openai_image_model: str = "gpt-image-1"
    openai_timeout_ms: int = 45000

    tripo_api_key: str = ""
    tripo_base_url: str = "https://api.tripo3d.ai/v2"
    meshy_api_key: str = ""
    meshy_base_url: str = "https://api.meshy.ai"
    hyper3d_api_key: str = ""
    hyper3d_base_url: str = "https://api.hyper3d.ai/v1"
    model_generation_timeout_sec: int = 120
    model_generation_enable_remote: bool = False

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_database_url(cls, value: str) -> str:
        for prefix in ("sqlite:///", "sqlite+pysqlite:///"):
            if not value.startswith(prefix):
                continue
            path_part = value[len(prefix):]
            if path_part == ":memory:":
                return value
            candidate = Path(path_part)
            if candidate.is_absolute():
                return f"{prefix}{candidate.as_posix()}"
            return f"{prefix}{(BACKEND_DIR / candidate).resolve().as_posix()}"
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def rtc_ice_servers(self) -> list[dict[str, str]]:
        servers: list[dict[str, str]] = [{"urls": self.rtc_stun_url}]
        if self.rtc_turn_url:
            turn_server = {"urls": self.rtc_turn_url}
            if self.rtc_turn_username:
                turn_server["username"] = self.rtc_turn_username
            if self.rtc_turn_password:
                turn_server["credential"] = self.rtc_turn_password
            servers.append(turn_server)
        return servers


@lru_cache
def get_settings() -> Settings:
    return Settings()
