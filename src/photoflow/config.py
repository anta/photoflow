"""Environment configuration; writable state must be separate from the NAS."""

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PHOTOFLOW_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    nas_root: Path = Path("/photos")
    data_dir: Path = Path("./data")
    exiftool_path: str = "exiftool"
    exiftool_timeout: float = Field(default=30, gt=0, le=300)
    thumbnail_size: int = Field(default=400, ge=64, le=2048)
    thumbnail_quality: int = Field(default=85, ge=50, le=95)
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_directories(self) -> "Settings":
        self.nas_root = self.nas_root.expanduser().resolve()
        self.data_dir = self.data_dir.expanduser().resolve()
        if not self.nas_root.is_dir():
            raise ValueError("PHOTOFLOW_NAS_ROOT must be an existing directory")
        if not os.access(self.nas_root, os.R_OK | os.X_OK):
            raise ValueError("PHOTOFLOW_NAS_ROOT must be readable and searchable")
        if self.data_dir.is_relative_to(self.nas_root) or self.nas_root.is_relative_to(
            self.data_dir
        ):
            raise ValueError("PHOTOFLOW_DATA_DIR and PHOTOFLOW_NAS_ROOT must not overlap")
        return self

    @property
    def database_path(self) -> Path:
        return self.data_dir / "photoflow.sqlite3"

    @property
    def thumbnail_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    def prepare_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
