import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Business
from app.security.admin_tokens import (
    generate_admin_token,
    hash_admin_token,
)


class BusinessNotFoundError(LookupError):
    pass


class AdminAccessAlreadyEnabledError(RuntimeError):
    pass


async def bootstrap_business_admin(
    session: AsyncSession,
    business_id: int,
    *,
    rotate: bool = False,
) -> str:
    """Enable admin access and return the new plaintext token once."""
    async with session.begin():
        business = await session.scalar(
            select(Business)
            .where(Business.id == business_id)
            .with_for_update()
        )

        if business is None:
            raise BusinessNotFoundError("Business not found")

        if business.admin_token_hash is not None and not rotate:
            raise AdminAccessAlreadyEnabledError(
                "Admin access is already enabled"
            )

        token = generate_admin_token()
        business.admin_token_hash = hash_admin_token(token)

    return token


async def run(
    business_id: int,
    *,
    rotate: bool = False,
) -> str:
    from app.core.config import Settings

    config = Settings()
    engine = create_async_engine(config.database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            return await bootstrap_business_admin(
                session,
                business_id,
                rotate=rotate,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Enable self-service admin access for one business. "
            "The generated token is shown only once."
        )
    )
    parser.add_argument(
        "--business-id",
        type=int,
        required=True,
        help="Business to enable",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Explicitly replace an existing admin credential",
    )
    args = parser.parse_args(argv)

    if args.business_id <= 0:
        parser.error("--business-id must be positive")

    try:
        token = asyncio.run(
            run(args.business_id, rotate=args.rotate)
        )
    except BusinessNotFoundError:
        print("Business not found.", file=sys.stderr)
        return 2
    except AdminAccessAlreadyEnabledError:
        print(
            "Admin access is already enabled. "
            "Use --rotate to replace it.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("Admin bootstrap interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Exception strings may contain database or configuration secrets.
        print(
            "Admin bootstrap failed: "
            f"error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2

    action = "rotated" if args.rotate else "enabled"
    print(f"Admin access {action}.")
    print(f"Token: {token}")
    print("Store this token securely.")
    print("It cannot be recovered later.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
