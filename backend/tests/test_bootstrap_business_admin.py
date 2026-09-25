from unittest.mock import AsyncMock

import pytest

from test_booking import booking_client  # noqa: F401

from app.commands import bootstrap_business_admin as command
from app.commands.bootstrap_business_admin import (
    AdminAccessAlreadyEnabledError,
    BusinessNotFoundError,
    bootstrap_business_admin,
)
from app.models import Business
from app.security.admin_tokens import hash_admin_token


async def test_bootstrap_generates_token_and_persists_only_hash(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        token = await bootstrap_business_admin(session, 1)

    async with sessions() as session:
        business = await session.get(Business, 1)
        stored = business.admin_token_hash

    assert stored == hash_admin_token(token)
    assert stored != token
    assert token not in stored


async def test_unknown_business_fails_without_generating_token(
    booking_client,
    monkeypatch,
):
    _, sessions, _ = booking_client
    generate = AsyncMock()
    monkeypatch.setattr(command, "generate_admin_token", generate)

    async with sessions() as session:
        with pytest.raises(BusinessNotFoundError):
            await bootstrap_business_admin(session, 999)

    generate.assert_not_called()


async def test_existing_credential_is_not_overwritten_by_default(
    booking_client,
):
    _, sessions, _ = booking_client
    original_hash = hash_admin_token("original-token")

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.admin_token_hash = original_hash

    async with sessions() as session:
        with pytest.raises(AdminAccessAlreadyEnabledError):
            await bootstrap_business_admin(session, 1)

    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.admin_token_hash == original_hash


async def test_rotate_replaces_existing_credential(booking_client):
    _, sessions, _ = booking_client
    original_hash = hash_admin_token("original-token")

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.admin_token_hash = original_hash

    async with sessions() as session:
        token = await bootstrap_business_admin(
            session,
            1,
            rotate=True,
        )

    async with sessions() as session:
        business = await session.get(Business, 1)
        stored = business.admin_token_hash

    assert stored == hash_admin_token(token)
    assert stored != original_hash
    assert stored != token


def test_cli_prints_new_token_once(monkeypatch, capsys):
    token = "new-one-time-admin-token"
    run = AsyncMock(return_value=token)
    monkeypatch.setattr(command, "run", run)

    result = command.main(["--business-id", "1"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.count(token) == 1
    assert "Admin access enabled." in captured.out
    assert "It cannot be recovered later." in captured.out
    run.assert_awaited_once_with(1, rotate=False)


def test_cli_requires_rotate_and_does_not_print_token(
    monkeypatch,
    capsys,
):
    run = AsyncMock(side_effect=AdminAccessAlreadyEnabledError())
    monkeypatch.setattr(command, "run", run)

    result = command.main(["--business-id", "1"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "already enabled" in captured.err
    assert "Token:" not in captured.err


def test_cli_rotation_prints_only_new_token(monkeypatch, capsys):
    token = "rotated-one-time-admin-token"
    run = AsyncMock(return_value=token)
    monkeypatch.setattr(command, "run", run)

    result = command.main(
        ["--business-id", "1", "--rotate"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.count(token) == 1
    assert "Admin access rotated." in captured.out
    run.assert_awaited_once_with(1, rotate=True)


def test_cli_unknown_business_has_no_stdout(monkeypatch, capsys):
    run = AsyncMock(side_effect=BusinessNotFoundError())
    monkeypatch.setattr(command, "run", run)

    result = command.main(["--business-id", "999"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "Business not found.\n"
    assert "Token:" not in captured.err
