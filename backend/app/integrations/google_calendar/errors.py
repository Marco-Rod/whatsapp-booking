class GoogleCalendarError(Exception):
    """A Calendar operation failed; its outcome may be unknown after a timeout."""

    def __init__(self, operation: str, *, status_code: int | None = None):
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"Google Calendar {operation} failed")
