"""Unit tests for Mermaid diagram generation."""

from archtopo.core.ir import (
    ArchitectureEdge,
    ArchitectureGraph,
    DomainEventNode,
    EdgeType,
    EntrypointNode,
    EntrypointType,
    EventField,
    HandlerNode,
    ServiceNode,
    StorageEntityNode,
    UseCaseNode,
)
from archtopo.renderers.mermaid import (
    generate_domain_diagram,
    generate_event_flowchart,
    generate_system_overview,
    generate_use_case_flowchart,
)


def _build_sample_graph() -> ArchitectureGraph:
    graph = ArchitectureGraph(project_name="InventX", project_root="/tmp/inventx")

    ep = EntrypointNode(
        id="route.booking.create",
        name="POST /bookings",
        entrypoint_type=EntrypointType.HTTP_ROUTE,
        domain="booking",
        target_use_case_ids=["use_case.booking.create_booking"],
    )
    graph.entrypoints.append(ep)

    uc = UseCaseNode(
        id="use_case.booking.create_booking",
        name="create_booking",
        domain="booking",
        summary="Create a booking.",
    )
    graph.use_cases.append(uc)

    svc = ServiceNode(
        id="service.BookingService",
        name="BookingService",
        domain="booking",
        methods=["create"],
    )
    graph.services.append(svc)

    table = StorageEntityNode(
        id="db.table.bookings",
        name="bookings",
        engine="postgresql",
        table_or_key="bookings",
        domain="booking",
    )
    graph.storage_entities.append(table)

    ev = DomainEventNode(
        id="event.BookingCreatedEvent",
        name="BookingCreatedEvent",
        domain="booking",
        fields=[EventField(name="id", type_repr="str", required=True)],
    )
    graph.events.append(ev)

    h = HandlerNode(
        id="handler.handle_booking",
        name="handle_booking",
        domain="booking",
        handled_event_ids=[ev.id],
    )
    graph.handlers.append(h)

    # Edges
    graph.edges.append(ArchitectureEdge(source_id=ep.id, target_id=uc.id, edge_type=EdgeType.TRIGGERS))
    graph.edges.append(ArchitectureEdge(source_id=uc.id, target_id=svc.id, edge_type=EdgeType.ORCHESTRATES))
    graph.edges.append(ArchitectureEdge(source_id=svc.id, target_id=table.id, edge_type=EdgeType.WRITES_TO))
    graph.edges.append(ArchitectureEdge(source_id=svc.id, target_id=ev.id, edge_type=EdgeType.PUBLISHES))
    graph.edges.append(ArchitectureEdge(source_id=ev.id, target_id=h.id, edge_type=EdgeType.DELIVERED_TO))

    return graph


def test_mermaid_no_broken_wikilinks_in_labels() -> None:
    graph = _build_sample_graph()

    ev_chart = generate_event_flowchart(graph.events[0], graph)
    assert "[[" not in ev_chart
    assert "]]" not in ev_chart

    uc_chart = generate_use_case_flowchart(graph.use_cases[0], graph)
    assert "[[" not in uc_chart
    assert "]]" not in uc_chart

    dom_chart = generate_domain_diagram("booking", graph)
    assert "[[" not in dom_chart
    assert "]]" not in dom_chart

    overview_chart = generate_system_overview(graph)
    assert "[[" not in overview_chart
    assert "]]" not in overview_chart


def test_mermaid_overview_shows_bounded_contexts() -> None:
    graph = _build_sample_graph()
    overview = generate_system_overview(graph)

    assert "subgraph Ingress" in overview
    assert "subgraph Contexts" in overview
    assert "subgraph Transport" in overview
    assert "Booking Context" in overview
