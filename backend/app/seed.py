"""Create a demo business once; never overwrite existing configuration."""
import asyncio
from datetime import time
from sqlalchemy import select
from app.core.database import Session, engine
from app.models import Business, BusinessHours, Service


async def main():
    async with Session.begin() as session:
        business = await session.scalar(select(Business).where(Business.name == "Bella Studio"))
        if business is None:
            business = Business(name="Bella Studio", timezone="America/Mexico_City")
            session.add(business)
            await session.flush()
            service = Service(business_id=business.id, name="Corte", duration_minutes=60)
            session.add(service)
            for weekday in range(7):
                session.add(BusinessHours(business_id=business.id, weekday=weekday,
                    start_time=time(9), end_time=time(18), is_closed=weekday == 6))
            await session.flush()
            print(f"business_id={business.id}, service_id={service.id}")
        else:
            print(f"Demo already exists: business_id={business.id}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
