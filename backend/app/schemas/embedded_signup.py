from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmbeddedSignupStartResponse(BaseModel):
    nonce: str = Field(min_length=32, max_length=128, repr=False)
    expires_at: datetime


class EmbeddedSignupCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_nonce: str = Field(min_length=32, max_length=128, repr=False)
    authorization_code: str = Field(min_length=1, max_length=4_096, repr=False)
    candidate_account_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[0-9]+$",
    )
    candidate_phone_number_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[0-9]+$",
    )
