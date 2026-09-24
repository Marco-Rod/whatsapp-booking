import pytest

from app.security.oauth_state import (
    OAuthStateError,
    OAuthStateManager,
)


def make_manager() -> OAuthStateManager:
    return OAuthStateManager(
        secret="test-oauth-state-secret",
        max_age_seconds=600,
    )


def test_state_round_trip():
    manager = make_manager()

    state = manager.create(
        business_id=42,
        code_verifier="test-code-verifier",
    )

    result = manager.verify(state)

    assert state
    assert result.business_id == 42
    assert result.code_verifier == "test-code-verifier"


def test_state_does_not_expose_plain_business_parameter():
    manager = make_manager()

    state = manager.create(
        business_id=42,
        code_verifier="test-code-verifier",
    )

    assert "business_id=42" not in state


def test_modified_state_is_rejected():
    manager = make_manager()

    state = manager.create(
        business_id=42,
        code_verifier="test-code-verifier",
    )

    payload, signature = state.split(".", 1)

    replacement = "A" if signature[-1] != "A" else "B"
    tampered = f"{payload}.{signature[:-1]}{replacement}"

    with pytest.raises(
        OAuthStateError,
        match="Invalid OAuth state",
    ):
        manager.verify(tampered)


def test_different_secret_is_rejected():
    first = make_manager()

    second = OAuthStateManager(
        secret="different-secret",
    )

    state = first.create(
        business_id=42,
        code_verifier="test-code-verifier",
    )

    with pytest.raises(OAuthStateError):
        second.verify(state)


def test_invalid_business_id_is_rejected():
    manager = make_manager()

    with pytest.raises(OAuthStateError):
        manager.create(
            business_id=0,
            code_verifier="test-code-verifier",
        )


def test_expired_state_is_rejected(monkeypatch):
    manager = OAuthStateManager(
        secret="test-secret",
        max_age_seconds=60,
    )

    monkeypatch.setattr(
        "app.security.oauth_state.time.time",
        lambda: 1_000,
    )

    state = manager.create(
        business_id=42,
        code_verifier="test-code-verifier",
    )

    monkeypatch.setattr(
        "app.security.oauth_state.time.time",
        lambda: 1_061,
    )

    with pytest.raises(
        OAuthStateError,
        match="OAuth state has expired",
    ):
        manager.verify(state)
