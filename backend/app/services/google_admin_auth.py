from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, BusinessUser
from app.security.admin_tokens import (
    BusinessAdminAuthenticationError,
    authenticate_business_admin,
)
from app.security.google_identity import (
    GoogleIdentityError,
    GoogleIdentityVerifier,
)


class GoogleAdminAuthError(PermissionError):
    pass


@dataclass(frozen=True)
class GoogleAdminAuthentication:
    business: Business
    user: BusinessUser


class GoogleAdminAuthService:
    def __init__(
        self,
        session: AsyncSession,
        identity_verifier: GoogleIdentityVerifier,
    ) -> None:
        self.session = session
        self.identity_verifier = identity_verifier

    async def link_google_identity(
        self,
        *,
        admin_token: str,
        google_credential: str,
    ) -> GoogleAdminAuthentication:
        try:
            async with self.session.begin():
                business = await authenticate_business_admin(
                    self.session,
                    admin_token,
                )
                identity = await self.identity_verifier.verify(
                    google_credential
                )
                user = await self.session.scalar(
                    select(BusinessUser)
                    .where(
                        BusinessUser.auth_provider == "google",
                        BusinessUser.provider_subject
                        == identity.subject,
                    )
                    .with_for_update()
                )

                if user is None:
                    user = BusinessUser(
                        business_id=business.id,
                        auth_provider="google",
                        provider_subject=identity.subject,
                        email=identity.email,
                        display_name=identity.display_name,
                    )
                    self.session.add(user)
                    await self.session.flush()
                elif user.business_id != business.id:
                    raise GoogleAdminAuthError(
                        "Invalid Google admin authentication"
                    )
                else:
                    user.email = identity.email
                    user.display_name = identity.display_name

                return GoogleAdminAuthentication(
                    business=business,
                    user=user,
                )
        except GoogleAdminAuthError:
            raise
        except (
            BusinessAdminAuthenticationError,
            GoogleIdentityError,
            IntegrityError,
        ) as exc:
            raise GoogleAdminAuthError(
                "Invalid Google admin authentication"
            ) from exc

    async def authenticate_google(
        self,
        *,
        google_credential: str,
    ) -> GoogleAdminAuthentication:
        try:
            identity = await self.identity_verifier.verify(
                google_credential
            )
            user = await self.session.scalar(
                select(BusinessUser).where(
                    BusinessUser.auth_provider == "google",
                    BusinessUser.provider_subject
                    == identity.subject,
                )
            )
            if user is None:
                raise GoogleAdminAuthError(
                    "Invalid Google admin authentication"
                )

            business = await self.session.get(
                Business,
                user.business_id,
            )
            if business is None or business.admin_token_hash is None:
                raise GoogleAdminAuthError(
                    "Invalid Google admin authentication"
                )

            return GoogleAdminAuthentication(
                business=business,
                user=user,
            )
        except GoogleAdminAuthError:
            raise
        except GoogleIdentityError as exc:
            raise GoogleAdminAuthError(
                "Invalid Google admin authentication"
            ) from exc
