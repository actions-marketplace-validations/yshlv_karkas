"""Unit tests for Karkas IR models."""

from karkas.core.ir import (
    ArchitectureEdge,
    ArchitectureGraph,
    DomainEventNode,
    EdgeType,
    EventField,
    HandlerNode,
    ServiceNode,
)


def test_ir_serialization_and_queries() -> None:
    graph = ArchitectureGraph(
        project_name="test_project",
        project_root="/path/to/project",
    )

    ev = DomainEventNode(
        id="events.BookingCreatedEvent",
        name="BookingCreatedEvent",
        docstring="Record of created booking.",
        fields=[
            EventField(name="booking_id", type_repr="str", required=True),
            EventField(name="source", type_repr="str", required=True),
        ],
    )
    graph.events.append(ev)

    svc = ServiceNode(
        id="services.BookingService",
        name="BookingService",
        methods=["create_booking"],
    )
    graph.services.append(svc)

    h = HandlerNode(
        id="handlers.notify_booking",
        name="notify_booking",
        is_batch=True,
        batch_config={"window_seconds": 30, "max_batch_size": 25},
    )
    graph.handlers.append(h)

    # Add edges
    graph.edges.append(
        ArchitectureEdge(
            source_id=svc.id,
            target_id=ev.id,
            edge_type=EdgeType.PUBLISHES,
            label="create_booking",
        )
    )
    graph.edges.append(
        ArchitectureEdge(
            source_id=ev.id,
            target_id=h.id,
            edge_type=EdgeType.DELIVERED_TO,
            label="deliver",
        )
    )

    # Test query helpers
    found_ev = graph.find_event("BookingCreatedEvent")
    assert found_ev is not None
    assert found_ev.name == "BookingCreatedEvent"

    producers = graph.get_producers_for_event(ev.id)
    assert len(producers) == 1
    assert producers[0].name == "BookingService"

    handlers = graph.get_handlers_for_event(ev.id)
    assert len(handlers) == 1
    assert handlers[0].name == "notify_booking"

    # Test JSON roundtrip
    raw_json = graph.model_dump_json()
    reloaded = ArchitectureGraph.model_validate_json(raw_json)
    assert reloaded.project_name == "test_project"
    assert len(reloaded.events) == 1
