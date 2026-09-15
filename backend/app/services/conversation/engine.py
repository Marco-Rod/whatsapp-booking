from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.repositories.conversations import ConversationRepository
from app.schemas.booking import AppointmentCreate, CustomerInput
from app.services.booking.availability import NotFoundError
from app.services.booking.booking import BookingConflictError, BookingService
from app.services.conversation import messages
from app.services.conversation.result import ConversationResult
from app.services.conversation.states import ConversationState as State


class ConversationEngine:
    def __init__(self, session, clock=None):
        self.session = session
        self.repository = ConversationRepository(session)
        self.booking = BookingService(session)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def handle_message(self, business_id: int, phone: str, text: str) -> ConversationResult:
        phone = CustomerInput(name=phone, phone=phone).phone
        async with self.session.begin():
            business = await self.booking.bookings.lock_business(business_id)
            if business is None:
                raise NotFoundError("Business not found")
            conversation = await self.repository.get_or_create(business_id, phone)
            result = await self._handle(conversation, business, text.strip())
            await self.session.flush()
        return result

    @staticmethod
    def _choose(text, values):
        # Compare strings: unbounded or malformed numbers never reach int().
        return next((value for i, value in enumerate(values, 1) if text == str(i)), None)

    @staticmethod
    def _reset(conversation):
        conversation.state = State.MAIN_MENU.value
        conversation.context = {}

    async def _services(self, conversation):
        services = await self.repository.active_services(conversation.business_id)
        if not services:
            self._reset(conversation)
            return "No hay servicios disponibles por ahora.\n" + messages.MAIN_MENU
        conversation.state = State.SELECT_SERVICE.value
        conversation.context = {"service_ids": [service.id for service in services]}
        return messages.service_menu([service.name for service in services])

    def _dates(self, conversation, business):
        today = self.clock().astimezone(ZoneInfo(business.timezone)).date()
        conversation.state = State.SELECT_DATE.value
        conversation.context = {"service_id": conversation.context["service_id"],
            "dates": [(today + timedelta(days=i)).isoformat() for i in range(3)]}
        return messages.DATES

    async def _times(self, conversation, business, day):
        try:
            available = await self.booking.availability.get_available_slots(
                business.id, conversation.context["service_id"], date.fromisoformat(day))
        except NotFoundError:
            return "Ese servicio ya no está disponible.\n" + await self._services(conversation)
        starts = [slot.starts_at for slot in available.slots
                  if slot.starts_at.astimezone(timezone.utc) > self.clock().astimezone(timezone.utc)]
        if not starts:
            return "No hay horarios disponibles para ese día.\n" + self._dates(conversation, business)
        conversation.state = State.SELECT_TIME.value
        conversation.context = {"service_id": conversation.context["service_id"], "date": day,
                                "starts": [start.isoformat() for start in starts]}
        return messages.time_menu(starts)

    async def _handle(self, conversation, business, text):
        if text.upper() == "CANCELAR":
            self._reset(conversation)
            return ConversationResult([messages.MAIN_MENU])
        state = State(conversation.state)
        context = conversation.context
        if state == State.MAIN_MENU:
            return ConversationResult([await self._services(conversation) if text == "1" else messages.MAIN_MENU])

        if state == State.SELECT_SERVICE:
            service_id = self._choose(text, context["service_ids"])
            if service_id is None:
                # Preserve the numbering that the user saw, even if the catalog changed.
                names = []
                for selected_id in context["service_ids"]:
                    service = await self.booking.bookings.service(business.id, selected_id)
                    names.append(service.name if service else "Servicio no disponible")
                return ConversationResult([messages.INVALID, messages.service_menu(names)])
            service = await self.booking.bookings.service(business.id, service_id)
            if service is None or not service.is_active:
                return ConversationResult(["Ese servicio ya no está disponible.", await self._services(conversation)])
            conversation.context = {"service_id": service_id}
            return ConversationResult([self._dates(conversation, business)])

        if state == State.SELECT_DATE:
            day = self._choose(text, context["dates"])
            if day is None:
                return ConversationResult([messages.INVALID, messages.DATES])
            return ConversationResult([await self._times(conversation, business, day)])

        if state == State.SELECT_TIME:
            start = self._choose(text, context["starts"])
            if start is None:
                return ConversationResult([messages.INVALID, messages.time_menu(
                    [datetime.fromisoformat(value) for value in context["starts"]])])
            service = await self.booking.bookings.service(business.id, context["service_id"])
            if service is None or not service.is_active:
                return ConversationResult(["Ese servicio ya no está disponible.", await self._services(conversation)])
            conversation.state = State.CONFIRM_APPOINTMENT.value
            conversation.context = {"service_id": service.id, "date": context["date"], "starts_at": start}
            return ConversationResult([messages.confirmation(service.name, datetime.fromisoformat(start))])

        if text == "2":
            self._reset(conversation)
            return ConversationResult(["Reserva descartada.", messages.MAIN_MENU])
        service = await self.booking.bookings.service(business.id, context["service_id"])
        if service is None or not service.is_active:
            return ConversationResult(["Ese servicio ya no está disponible.", await self._services(conversation)])
        start = datetime.fromisoformat(context["starts_at"])
        if text != "1":
            return ConversationResult([messages.INVALID, messages.confirmation(service.name, start)])
        if start.astimezone(timezone.utc) <= self.clock().astimezone(timezone.utc):
            return ConversationResult(["Ese horario ya pasó.", self._dates(conversation, business)])
        try:
            # The appointment and conversation are committed together by handle_message.
            appointment = await self.booking.create_appointment_in_transaction(AppointmentCreate(
                business_id=business.id, service_id=service.id, starts_at=start,
                customer=CustomerInput(name=conversation.phone, phone=conversation.phone)))
        except (BookingConflictError, NotFoundError):
            return ConversationResult(["Ese horario ya no está disponible.",
                await self._times(conversation, business, context["date"])])
        self._reset(conversation)
        return ConversationResult([f"✅ Tu cita está confirmada.\n{service.name}\n"
            f"{appointment.starts_at:%Y-%m-%d %H:%M}\n¡Nos vemos pronto!", messages.MAIN_MENU])
