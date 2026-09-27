import logging
from io import StringIO
from unittest.mock import Mock

import pytest

from app.api.v1.whatsapp import log_whatsapp_configuration_error
from app.core.access_logging import (
    UvicornAccessQueryFilter,
    configure_uvicorn_access_logging,
)
from app.integrations.google_calendar.oauth import (
    GoogleOAuthExchangeError,
    GoogleOAuthService,
)
from app.integrations.whatsapp.client import WhatsAppConfigurationError


def emit_access_log(target: str) -> str:
    configure_uvicorn_access_logging()
    logger = logging.getLogger("uvicorn.access")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    original_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:12345",
            "GET",
            target,
            "1.1",
            200,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)

    return stream.getvalue()


def test_uvicorn_access_log_strips_query_string_and_preserves_request_context():
    sensitive_value = "SENSITIVE_VERIFY_TOKEN"

    message = emit_access_log(
        "/api/v1/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token="
        f"{sensitive_value}&hub.challenge=123",
    )

    assert "/api/v1/webhooks/whatsapp" in message
    assert "GET" in message
    assert "200" in message
    assert "?" not in message
    assert sensitive_value not in message


def test_uvicorn_access_log_keeps_normal_path():
    message = emit_access_log("/health")

    assert message.endswith('GET /health HTTP/1.1" 200\n')


def test_uvicorn_access_logging_setup_is_idempotent():
    logger = logging.getLogger("uvicorn.access")
    configure_uvicorn_access_logging()
    configure_uvicorn_access_logging()

    assert sum(
        isinstance(log_filter, UvicornAccessQueryFilter)
        for log_filter in logger.filters
    ) == 1


def test_whatsapp_configuration_log_does_not_expose_exception_message(caplog):
    secret = "SYNTHETIC_WHATSAPP_SECRET"

    with caplog.at_level(logging.WARNING):
        log_whatsapp_configuration_error(WhatsAppConfigurationError(secret))

    assert secret not in caplog.text
    assert "WhatsApp configuration error" in caplog.text
    assert "WhatsAppConfigurationError" in caplog.text


def test_google_oauth_exchange_log_omits_exception_message_and_traceback(caplog):
    secret = "SYNTHETIC_GOOGLE_TOKEN"
    service = GoogleOAuthService(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://test/callback",
    )
    flow = Mock()
    flow.fetch_token.side_effect = RuntimeError(secret)
    service._build_flow = Mock(return_value=flow)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(GoogleOAuthExchangeError):
            service.exchange_code(
                code="test-code",
                code_verifier="test-code-verifier",
            )

    records = [
        record
        for record in caplog.records
        if record.name == "app.integrations.google_calendar.oauth"
    ]
    assert len(records) == 1
    assert records[0].exc_info is None
    assert secret not in caplog.text
    assert "Google OAuth token exchange failed (RuntimeError)" in caplog.text
