from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True)

    database_url: str
    jwt_secret: str  # 不給預設值：沒設定就啟動失敗，避免用到可猜測的固定金鑰
    jwt_ttl_hours: int = 12
    cookie_secure: bool = False
    seed_demo_password: str | None = None
    data_dir: Path = ROOT / "data"

    # 郵件：示範環境一律寄到 Mailpit；收件網域白名單在程式層面擋掉真實網域
    smtp_host: str = "localhost"
    smtp_port: int = 1026
    mailpit_api: str = "http://localhost:8026"
    buyer_mailbox: str = "procurement@arcwell.example"
    allowed_recipient_suffix: str = ".example"

    llm_provider: str = "anthropic"  # anthropic / openai_compatible
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "claude-haiku-5-5"
    llm_reasoning_effort: str | None = None


settings = Settings()
