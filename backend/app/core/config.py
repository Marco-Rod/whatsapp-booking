from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://booking:booking@localhost:5432/booking"
    slot_interval_minutes: int = Field(default=30, gt=0)

    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = ""
    meta_app_secret: SecretStr = SecretStr("")

    credential_encryption_key: SecretStr | None = None
    google_oauth_client_id: SecretStr | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_identity_client_id: str | None = None
    frontend_url: str = "http://localhost:5173"

    admin_session_secret: SecretStr | None = None
    admin_session_max_age_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        gt=0,
    )
    admin_session_cookie_secure: bool = False
    admin_session_cookie_samesite: Literal[
        "lax",
        "strict",
        "none",
    ] = "lax"

    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value):
        if isinstance(value, str):
            return [
                origin.strip()
                for origin in value.split(",")
                if origin.strip()
            ]
        return value

    @model_validator(mode="after")
    def validate_admin_session_cookie(self):
        if "*" in self.cors_allowed_origins:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must list explicit origins "
                "when credentials are enabled"
            )
        if (
            self.admin_session_cookie_samesite == "none"
            and not self.admin_session_cookie_secure
        ):
            raise ValueError(
                "ADMIN_SESSION_COOKIE_SAMESITE=none requires "
                "ADMIN_SESSION_COOKIE_SECURE=true"
            )
        return self


settings = Settings()
