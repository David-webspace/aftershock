from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True)

    database_url: str
    data_dir: Path = ROOT / "data"


settings = Settings()
