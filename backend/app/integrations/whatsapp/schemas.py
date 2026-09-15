from typing import Literal
from pydantic import BaseModel, Field


class ChangeValue(BaseModel):
    metadata: dict = Field(default_factory=dict)
    messages: list[dict] = Field(default_factory=list)


class Change(BaseModel):
    field: str
    value: ChangeValue


class Entry(BaseModel):
    changes: list[Change] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    object: Literal["whatsapp_business_account"]
    entry: list[Entry]


class ParsedMessage(BaseModel):
    external_message_id: str = Field(min_length=1, max_length=255)
    phone: str
    text: str = Field(max_length=4096)
    phone_number_id: str = Field(min_length=1)
    business_phone: str
