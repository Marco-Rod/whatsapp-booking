import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business


class BusinessAdminAuthenticationError(PermissionError):
    pass


def generate_admin_token() -> str:
    """Generate the plaintext credential that is shown only at bootstrap."""
    return secrets.token_urlsafe(32)


def hash_admin_token(token: str) -> str:
    if not token:
        raise BusinessAdminAuthenticationError(
            "Invalid business admin credentials"
        )

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def authenticate_business_admin(
    session: AsyncSession,
    token: str,
) -> Business:
    try:
        candidate_hash = hash_admin_token(token)
    except BusinessAdminAuthenticationError:
        raise BusinessAdminAuthenticationError(
            "Invalid business admin credentials"
        ) from None

    business = await session.scalar(
        select(Business).where(
            Business.admin_token_hash == candidate_hash
        )
    )

    if (
        business is None
        or business.admin_token_hash is None
        or not hmac.compare_digest(
            business.admin_token_hash,
            candidate_hash,
        )
    ):
        raise BusinessAdminAuthenticationError(
            "Invalid business admin credentials"
        )

    return business
