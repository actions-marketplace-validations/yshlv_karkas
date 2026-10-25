"""Intermediate Representation (IR) models for Karkas.

Provides a strongly-typed graph schema describing entrypoints (HTTP routes, CLI, tasks),
use cases, domain services, domain events, channels (buses, queues, buffers),
handlers, storage entities, and their interconnections.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    """Types of architecture nodes present in the graph."""

    ENTRYPOINT = "entrypoint"
    SERVICE = "service"
    USE_CASE = "use_case"
    DOMAIN_EVENT = "domain_event"
    CHANNEL = "channel"
    HANDLER = "handler"
    BACKGROUND_TASK = "background_task"
    REPOSITORY = "repository"
    STORAGE_ENTITY = "storage_entity"
    FLOW = "flow"


class EdgeType(StrEnum):
    """Semantic relationships between nodes."""

    TRIGGERS = "triggers"  # Entrypoint -> UseCase / Service
    ORCHESTRATES = "orchestrates"  # UseCase -> Service
    PUBLISHES = "publishes"  # Service / UseCase -> DomainEvent
    ROUTED_THROUGH = "routed_through"  # DomainEvent -> Channel
    DELIVERED_TO = "delivered_to"  # Channel -> Handler / BackgroundTask
    READS_FROM = "reads_from"  # Handler / Service / UseCase -> StorageEntity
    WRITES_TO = "writes_to"  # Handler / Service / UseCase -> StorageEntity
    INVOKES = "invokes"  # Handler -> Repository / Service / Port


class EntrypointType(StrEnum):
    """Types of system entrypoints."""

    HTTP_ROUTE = "http_route"
    BACKGROUND_TASK = "background_task"
    CLI = "cli"
    WORKER = "worker"


class ChannelType(StrEnum):
    """Types of messaging / queuing channels."""

    IN_MEMORY_BUS = "in_memory_bus"
    REDIS_BATCH = "redis_batch"
    TASKIQ_QUEUE = "taskiq_queue"
    RABBITMQ_QUEUE = "rabbitmq_queue"
    KAFKA_TOPIC = "kafka_topic"


class SourceLocation(BaseModel):
    """Precise source code location for traceability and IDE links."""

    file_path: str
    start_line: int
    end_line: int | None = None
    symbol_name: str | None = None

    def display(self, project_root: str | None = None) -> str:
        """Return relative path with forward slashes for clean portable documentation."""
        p = self.file_path.replace("\\", "/")
        if project_root:
            norm_root = project_root.replace("\\", "/").rstrip("/")
            if p.lower().startswith(norm_root.lower()):
                p = p[len(norm_root):].lstrip("/")
        # Safety fallback: if absolute drive letter remains, isolate relative src path
        if ":" in p:
            if "/src/" in p:
                p = p[p.index("/src/") + 1:]
            elif p.startswith(("C:/", "D:/", "E:/")):
                p = p[3:].lstrip("/")
        return f"{p}:{self.start_line}"


class EventField(BaseModel):
    """Specification of an individual field within a domain event payload."""

    name: str
    type_repr: str
    required: bool = True
    default_repr: str | None = None
    description: str | None = None


class EntrypointNode(BaseModel):
    """Application entrypoint (e.g. FastAPI route, Taskiq task, CLI command)."""

    id: str  # e.g. "route.booking.create_booking"
    name: str  # e.g. "POST /bookings"
    entrypoint_type: EntrypointType = EntrypointType.HTTP_ROUTE
    http_method: str | None = None  # "POST", "GET", etc.
    path: str | None = None  # "/bookings"
    summary: str | None = None
    docstring: str | None = None
    target_use_case_ids: list[str] = Field(default_factory=list)
    target_service_ids: list[str] = Field(default_factory=list)
    location: SourceLocation | None = None
    domain: str | None = None


class DomainEventNode(BaseModel):
    """Domain Event representation."""

    id: str  # fully-qualified module.ClassName
    name: str
    summary: str | None = None
    docstring: str | None = None
    fields: list[EventField] = Field(default_factory=list)
    json_schema: dict[str, Any] = Field(default_factory=dict)
    location: SourceLocation | None = None
    domain: str | None = None


class ChannelNode(BaseModel):
    """Messaging channel, event bus, or batch buffer."""

    id: str
    name: str
    channel_type: ChannelType
    configuration: dict[str, Any] = Field(default_factory=dict)


class HandlerNode(BaseModel):
    """Event handler or background task."""

    id: str
    name: str
    summary: str | None = None
    docstring: str | None = None
    is_batch: bool = False
    is_background_task: bool = False
    batch_config: dict[str, Any] | None = None
    location: SourceLocation | None = None
    handled_event_ids: list[str] = Field(default_factory=list)
    persisted_storage_ids: list[str] = Field(default_factory=list)
    domain: str | None = None


class UseCaseNode(BaseModel):
    """Application use case orchestrating domain services, persistence, and events."""

    id: str  # e.g. "use_case.booking.create_booking"
    name: str  # "create_booking"
    domain: str  # "booking"
    summary: str | None = None
    docstring: str | None = None
    orchestrated_services: list[str] = Field(default_factory=list)  # e.g. ["BookingService.create"]
    repositories: list[str] = Field(default_factory=list)  # e.g. ["BookingRepository"]
    published_events: list[str] = Field(default_factory=list)
    location: SourceLocation | None = None


class ServiceNode(BaseModel):
    """Domain service, use case, or application controller."""

    id: str
    name: str
    domain: str | None = None
    summary: str | None = None
    docstring: str | None = None
    methods: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    published_events: list[str] = Field(default_factory=list)
    location: SourceLocation | None = None


class StorageEntityNode(BaseModel):
    """Database table (PostgreSQL, ClickHouse) or Cache Key pattern (Redis)."""

    id: str
    name: str
    engine: str  # "postgresql" | "clickhouse" | "redis"
    table_or_key: str
    domain: str | None = None
    columns_or_fields: list[dict[str, Any]] = Field(default_factory=list)
    location: SourceLocation | None = None


class ArchitectureEdge(BaseModel):
    """Directed connection in the architecture graph."""

    source_id: str
    target_id: str
    edge_type: EdgeType
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessFlow(BaseModel):
    """End-to-end business flow across multiple events, services, and handlers."""

    id: str
    name: str
    description: str | None = None
    steps: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class ArchitectureGraph(BaseModel):
    """Complete root snapshot of the extracted architecture graph."""

    version: str = "2.0.0"
    project_name: str
    project_root: str = "."
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    entrypoints: list[EntrypointNode] = Field(default_factory=list)
    use_cases: list[UseCaseNode] = Field(default_factory=list)
    services: list[ServiceNode] = Field(default_factory=list)
    events: list[DomainEventNode] = Field(default_factory=list)
    channels: list[ChannelNode] = Field(default_factory=list)
    handlers: list[HandlerNode] = Field(default_factory=list)
    storage_entities: list[StorageEntityNode] = Field(default_factory=list)
    edges: list[ArchitectureEdge] = Field(default_factory=list)
    flows: list[ProcessFlow] = Field(default_factory=list)

    def find_event(self, event_id: str) -> DomainEventNode | None:
        """Find an event by its ID or simple name."""
        for ev in self.events:
            if ev.id == event_id or ev.name == event_id:
                return ev
        return None

    def find_node(self, node_id: str) -> Any | None:
        """Find any node by ID."""
        for collection in (
            self.entrypoints,
            self.use_cases,
            self.events,
            self.services,
            self.channels,
            self.handlers,
            self.storage_entities,
        ):
            for item in collection:
                if item.id == node_id:
                    return item
        return None

    def get_producers_for_event(self, event_id: str) -> list[ServiceNode]:
        """Return all services that publish this event."""
        producer_ids = [
            edge.source_id
            for edge in self.edges
            if edge.target_id == event_id and edge.edge_type == EdgeType.PUBLISHES
        ]
        return [s for s in self.services if s.id in producer_ids]

    def get_handlers_for_event(self, event_id: str) -> list[HandlerNode]:
        """Return all handlers listening to this specific event."""
        ev = self.find_event(event_id)
        ev_name = ev.name if ev else event_id

        direct_handler_ids = {
            edge.target_id
            for edge in self.edges
            if (edge.source_id == event_id or edge.metadata.get("event_id") == event_id)
            and edge.edge_type == EdgeType.DELIVERED_TO
        }

        matched: list[HandlerNode] = []
        for h in self.handlers:
            if (
                h.id in direct_handler_ids
                or event_id in h.handled_event_ids
                or ev_name in h.handled_event_ids
            ) and h not in matched:
                matched.append(h)
        return matched

    def get_entrypoints_for_use_case(self, uc_id: str) -> list[EntrypointNode]:
        """Return entrypoints that invoke this use case."""
        ep_ids = [
            e.source_id
            for e in self.edges
            if e.target_id == uc_id and e.edge_type == EdgeType.TRIGGERS
        ]
        return [ep for ep in self.entrypoints if ep.id in ep_ids]

    def get_storage_for_node(
        self, node_id: str
    ) -> tuple[list[StorageEntityNode], list[StorageEntityNode]]:
        """Return (reads, writes) storage entities connected to node."""
        read_ids = [
            e.target_id
            for e in self.edges
            if e.source_id == node_id and e.edge_type == EdgeType.READS_FROM
        ]
        write_ids = [
            e.target_id
            for e in self.edges
            if e.source_id == node_id and e.edge_type == EdgeType.WRITES_TO
        ]
        reads = [s for s in self.storage_entities if s.id in read_ids]
        writes = [s for s in self.storage_entities if s.id in write_ids]
        return reads, writes

    def get_domain_components(self, domain: str) -> dict[str, list[Any]]:
        """Return all entrypoints, use cases, services, storage entities, and events associated with a domain.

        A node is associated if its domain matches, OR if it participates directly in workflows of this domain.
        """
        domain_lower = domain.lower()

        # Primary use cases
        ucs = [u for u in self.use_cases if u.domain == domain_lower]
        uc_ids = {u.id for u in ucs}

        # Routes that trigger use cases in this domain, or have this domain
        routes = [
            r for r in self.entrypoints
            if r.domain == domain_lower or any(ucid in uc_ids for ucid in r.target_use_case_ids)
        ]

        # Services orchestrated by this domain's use cases, or belonging to domain
        orchestrated_service_ids = {
            e.target_id for e in self.edges
            if e.source_id in uc_ids and e.edge_type == EdgeType.ORCHESTRATES
        }
        services = [
            s for s in self.services
            if s.domain == domain_lower or s.id in orchestrated_service_ids or domain_lower in s.name.lower()
        ]
        service_ids = {s.id for s in services}

        # Storage entities accessed by this domain's use cases or services, or belonging to domain
        active_ids = uc_ids | service_ids
        storage_ids = {
            e.target_id for e in self.edges
            if e.source_id in active_ids and e.edge_type in (EdgeType.WRITES_TO, EdgeType.READS_FROM)
        }
        storage = [
            st for st in self.storage_entities
            if st.domain == domain_lower or st.id in storage_ids or domain_lower in st.name.lower()
        ]

        # Events emitted by this domain's use cases or services, or belonging to domain
        emitted_event_ids = {
            e.target_id for e in self.edges
            if e.source_id in active_ids and e.edge_type == EdgeType.PUBLISHES
        }
        events = [
            ev for ev in self.events
            if ev.domain == domain_lower or ev.id in emitted_event_ids or domain_lower in ev.name.lower()
        ]

        return {
            "entrypoints": sorted(routes, key=lambda x: x.name),
            "use_cases": sorted(ucs, key=lambda x: x.name),
            "services": sorted(services, key=lambda x: x.name),
            "storage": sorted(storage, key=lambda x: x.name),
            "events": sorted(events, key=lambda x: x.name),
        }

    def get_domains(self) -> list[str]:
        """Return valid business bounded contexts (excluding empty or utility domains)."""
        candidate_domains: set[str] = set()
        for col in (self.use_cases, self.events, self.services, self.entrypoints, self.storage_entities):
            for item in col:
                d = getattr(item, "domain", None)
                if d and d not in ("general", "base", "core", "application", "shared", "infrastructure"):
                    candidate_domains.add(d)

        valid_domains = []
        for d in sorted(candidate_domains):
            comps = self.get_domain_components(d)
            if comps["use_cases"] or (comps["entrypoints"] and comps["storage"]):
                valid_domains.append(d)

        return valid_domains
