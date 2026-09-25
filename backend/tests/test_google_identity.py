import pytest

from app.security.google_identity import (
    GoogleIdentityError,
    GoogleIdentityVerifier,
)
from app.security import factory


CLIENT_ID = "identity-client.apps.googleusercontent.com"
NOW = 2_000_000_000


def valid_claims(**overrides):
    return {
        "sub": "google-subject-123",
        "email": "owner@example.com",
        "name": "  Studio Owner  ",
        "email_verified": True,
        "aud": CLIENT_ID,
        "iss": "https://accounts.google.com",
        "exp": NOW + 300,
        **overrides,
    }


def make_verifier(claims=None, *, error=None):
    request_object = object()

    def verify_token(credential, request, audience):
        assert credential == "google-id-credential"
        assert request is request_object
        assert audience == CLIENT_ID
        if error is not None:
            raise error
        return valid_claims() if claims is None else claims

    return GoogleIdentityVerifier(
        client_id=CLIENT_ID,
        token_verifier=verify_token,
        request_factory=lambda: request_object,
        clock=lambda: NOW,
    )


async def test_valid_google_id_token_returns_trusted_identity():
    identity = await make_verifier().verify(
        "google-id-credential"
    )

    assert identity.subject == "google-subject-123"
    assert identity.email == "owner@example.com"
    assert identity.display_name == "Studio Owner"
    assert identity.email_verified is True


async def test_invalid_google_token_has_generic_error():
    verifier = make_verifier(
        error=ValueError("signature verification failed")
    )

    with pytest.raises(
        GoogleIdentityError,
        match="^Invalid Google identity$",
    ) as captured:
        await verifier.verify("google-id-credential")

    assert "signature" not in str(captured.value).lower()


@pytest.mark.parametrize(
    "claims",
    [
        valid_claims(aud="another-client"),
        valid_claims(exp=NOW),
        valid_claims(iss="https://malicious.example"),
        valid_claims(sub=""),
        valid_claims(email_verified=False),
        valid_claims(email_verified="true"),
    ],
    ids=[
        "wrong-audience",
        "expired",
        "wrong-issuer",
        "missing-subject",
        "unverified-email",
        "non-boolean-email-verification",
    ],
)
async def test_invalid_identity_claims_are_rejected(claims):
    with pytest.raises(
        GoogleIdentityError,
        match="^Invalid Google identity$",
    ):
        await make_verifier(claims).verify(
            "google-id-credential"
        )


@pytest.mark.parametrize("email", [None, "", "   "])
async def test_email_is_required(email):
    with pytest.raises(GoogleIdentityError):
        await make_verifier(
            valid_claims(email=email)
        ).verify("google-id-credential")


@pytest.mark.parametrize("name", [None, "", "   "])
async def test_display_name_is_optional(name):
    identity = await make_verifier(
        valid_claims(name=name)
    ).verify("google-id-credential")

    assert identity.display_name is None


async def test_empty_credential_is_rejected_before_verification():
    called = False

    def verify_token(*args):
        nonlocal called
        called = True
        return valid_claims()

    verifier = GoogleIdentityVerifier(
        client_id=CLIENT_ID,
        token_verifier=verify_token,
        clock=lambda: NOW,
    )

    with pytest.raises(GoogleIdentityError):
        await verifier.verify("")

    assert called is False


def test_google_identity_factory_uses_configured_client_id(
    monkeypatch,
):
    monkeypatch.setattr(
        factory.settings,
        "google_identity_client_id",
        CLIENT_ID,
    )

    verifier = factory.build_google_identity_verifier()

    assert verifier._client_id == CLIENT_ID


@pytest.mark.parametrize("client_id", [None, "", "   "])
def test_google_identity_factory_requires_configuration(
    monkeypatch,
    client_id,
):
    monkeypatch.setattr(
        factory.settings,
        "google_identity_client_id",
        client_id,
    )

    with pytest.raises(
        GoogleIdentityError,
        match="^Invalid Google identity$",
    ):
        factory.build_google_identity_verifier()
