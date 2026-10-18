"""Unit tests for ArchDoc AST visitor and docstring utilities."""

from pathlib import Path

from archdoc.config.schema import ArchDocConfig
from archdoc.core.docstring import clean_summary, format_docstring_markdown
from archdoc.extractors.ast_visitor import scan_directory_ast


def test_ast_visitor_detects_publish_and_handlers(tmp_path: Path) -> None:
    service_code = """
class BookingService:
    def __init__(self, event_bus):
        self.event_bus = event_bus

    async def create_booking(self, booking_id: str):
        \"\"\"Create a booking and publish event.\"\"\"
        event = BookingCreatedEvent(booking_id=booking_id)
        await self.event_bus.publish(event)

    async def cancel_many(self):
        await self.event_bus.publish_many([
            BookingCancelledEvent(id="1"),
            BookingCancelledEvent(id="2"),
        ])
"""

    handler_code = """
@batch_event_handler(BookingCreatedEvent, window_seconds=45, max_batch_size=50)
async def handle_bookings_batch(events):
    \"\"\"Process batched bookings.\"\"\"
    pass

@event_handler(BookingCancelledEvent)
async def handle_cancelled(event):
    pass
"""

    (tmp_path / "service.py").write_text(service_code, encoding="utf-8")
    (tmp_path / "handler.py").write_text(handler_code, encoding="utf-8")

    config = ArchDocConfig(project_root=str(tmp_path))
    result = scan_directory_ast(tmp_path, config)

    # Verify publishers
    pub_events = [ev for call in result.publish_calls for ev in call.event_class_names]
    assert "BookingCreatedEvent" in pub_events
    assert "BookingCancelledEvent" in pub_events

    callers = [call.caller_method for call in result.publish_calls]
    assert "create_booking" in callers
    assert "cancel_many" in callers

    # Verify handlers
    handler_names = [h.handler_name for h in result.handlers]
    assert "handle_bookings_batch" in handler_names
    assert "handle_cancelled" in handler_names

    batch_h = next(h for h in result.handlers if h.handler_name == "handle_bookings_batch")
    assert batch_h.is_batch is True
    assert batch_h.batch_kwargs.get("window_seconds") == 45
    assert batch_h.batch_kwargs.get("max_batch_size") == 50
    assert "BookingCreatedEvent" in batch_h.handled_event_names


def test_ast_visitor_detects_routes_and_uow_persistence(tmp_path: Path) -> None:
    routes_code = """
from fastapi import APIRouter
router = APIRouter()

@router.post("", response_model=BookingCreateResponse)
async def create_booking(payload: BookingCreateRequest):
    \"\"\"
    Create a booking and its tickets atomically.

    :param payload: Input booking request payload
    :return: Created booking response
    \"\"\"
    booking, tickets = await booking_use_cases.create_booking(payload=payload)
    return booking

@router.get("/search")
async def search_bookings():
    \"\"\"List bookings matching search query.\"\"\"
    return await booking_use_cases.get_booking_datatable()
"""

    use_case_code = """
async def create_booking(payload):
    \"\"\"Orchestrate booking creation and persist to database.\"\"\"
    async with db_uow:
        await db_uow[BookingRepository].create_booking(payload)
        await db_uow[TicketRepository].bulk_create_tickets(payload.tickets)
    return payload
"""

    routes_file = tmp_path / "routes_booking.py"
    uc_file = tmp_path / "booking_use_cases.py"
    routes_file.write_text(routes_code, encoding="utf-8")
    uc_file.write_text(use_case_code, encoding="utf-8")

    config = ArchDocConfig(project_root=str(tmp_path))
    result = scan_directory_ast(tmp_path, config)

    # Verify entrypoints
    assert len(result.entrypoints) == 2
    ep_post = next(ep for ep in result.entrypoints if ep.http_method == "POST")
    assert ep_post.func_name == "create_booking"
    assert ep_post.summary == "Create a booking and its tickets atomically."
    assert "create_booking" in ep_post.called_use_cases

    ep_get = next(ep for ep in result.entrypoints if ep.http_method == "GET")
    assert ep_get.func_name == "search_bookings"
    assert ep_get.path == "/search"
    assert ep_get.summary == "List bookings matching search query."
    assert "get_booking_datatable" in ep_get.called_use_cases

    # Verify UoW repository detection
    assert len(result.use_cases) >= 1
    uc = next(u for u in result.use_cases if u.name == "create_booking")
    assert "BookingRepository" in uc.repositories
    assert "TicketRepository" in uc.repositories


def test_docstring_cleaner() -> None:
    raw = """
    Create a booking aggregate with flattened tickets atomically.

    :param booking_service: Booking domain service
    :param booking_id: Booking public identifier
    :return: Booking entity
    :raises BookingDeletionError: If deletion fails
    """
    summary = clean_summary(raw)
    assert summary == "Create a booking aggregate with flattened tickets atomically."

    md = format_docstring_markdown(raw)
    assert "**Parameters:**" in md
    assert "- `booking_service` — Booking domain service" in md
    assert "**Returns:**" in md
    assert "- Booking entity" in md
    assert "**Raises:**" in md
    assert "- `BookingDeletionError` — If deletion fails" in md
