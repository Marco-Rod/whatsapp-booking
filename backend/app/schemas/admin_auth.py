from pydantic import BaseModel, ConfigDict


class GoogleCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: str
