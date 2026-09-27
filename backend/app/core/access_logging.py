import logging


class UvicornAccessQueryFilter(logging.Filter):
    """Remove query strings from Uvicorn's standard access-log target."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(
            record.args, tuple
        ):
            return True

        # Uvicorn emits: client address, method, target, HTTP version, status.
        if len(record.args) < 3 or not isinstance(record.args[2], str):
            return True

        target = record.args[2]
        path = target.split("?", 1)[0]
        if path != target:
            record.args = (*record.args[:2], path, *record.args[3:])

        return True


def configure_uvicorn_access_logging() -> None:
    """Install the sanitizer once, including across repeated app factories."""
    logger = logging.getLogger("uvicorn.access")
    if any(
        isinstance(log_filter, UvicornAccessQueryFilter)
        for log_filter in logger.filters
    ):
        return

    logger.addFilter(UvicornAccessQueryFilter())
