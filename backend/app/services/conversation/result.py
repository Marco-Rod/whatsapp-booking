from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationResult:
    messages: list[str]
    appointment_id: int | None = None
