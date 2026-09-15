from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")
    database_url: str = "postgresql+asyncpg://booking:booking@localhost:5432/booking"
    slot_interval_minutes: int = Field(default=30, gt=0)
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = ""


settings = Settings()
