import re
from app.integrations.whatsapp.schemas import ParsedMessage, WebhookPayload


def normalize_phone(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid phone")
    number = re.sub(r"[ ()-]", "", value)
    if not number.startswith("+"):
        number = "+" + number
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", number):
        raise ValueError("Invalid phone")
    return number


def parse_messages(payload: dict) -> list[ParsedMessage]:
    envelope = WebhookPayload.model_validate(payload)
    result = []
    for entry in envelope.entry:
        for change in entry.changes:
            if change.field != "messages":
                continue
            for message in change.value.messages:
                if message.get("type") != "text":
                    continue
                try:
                    result.append(ParsedMessage(
                        external_message_id=message["id"], phone=normalize_phone(message["from"]),
                        text=message["text"]["body"],
                        phone_number_id=change.value.metadata["phone_number_id"],
                        business_phone=normalize_phone(change.value.metadata["display_phone_number"])))
                except (KeyError, TypeError) as exc:
                    raise ValueError("Malformed text message") from exc
    return result
