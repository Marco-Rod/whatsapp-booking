from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Customer


class CustomerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, business_id: int, phone: str, name: str) -> Customer:
        # BookingService holds the business lock throughout this transaction.
        customer = await self.session.scalar(select(Customer).where(
            Customer.business_id == business_id, Customer.phone == phone))
        if customer is None:
            customer = Customer(business_id=business_id, phone=phone, name=name)
            self.session.add(customer)
            await self.session.flush()
        return customer
