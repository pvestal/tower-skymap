from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    storage_root: Path
    cold_storage_root: Path | None = None
    hot_retention_days: int = 90
    listen_host: str = "127.0.0.1"
    listen_port: int = 8410
    nasa_api_key: str = "DEMO_KEY"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "sky_embeddings"

    model_config = SettingsConfigDict(
        env_prefix="SKYMAP_",
        env_file="/opt/skymap/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
