"""Mermaid diagram generation for Karkas.

Produces:
1. High-Level Bounded Context Architecture Map (clean, executive-level).
2. Per-domain end-to-end trace diagrams (Routes -> Use Cases -> Services -> Storage & Events).
3. Localized Use Case execution flows.
4. Localized Domain Event lifecycle and batching flows.
5. End-to-end business sequence diagrams.
"""

import re

from karkas.core.ir import (
    ArchitectureGraph,
    ChannelType,
    DomainEventNode,
    EdgeType,
    EntrypointNode,
    ProcessFlow,
    UseCaseNode,
)


def generate_event_flowchart(event: DomainEventNode, graph: ArchitectureGraph) -> str:
    """Generate localized Mermaid flowchart for a single Domain Event lifecycle."""
    producers = graph.get_producers_for_event(event.id)
    handlers = graph.get_handlers_for_event(event.id)

    lines = [
        "flowchart LR",
    ]

    # Subgraph Producers
    lines.append("    subgraph Producers [\"🚀 Emitted By\"]")
    if producers:
        for s in producers:
            lines.append(f"        {_node_safe_id(s.id)}[\"{s.name}\"]")
    else:
        lines.append(f"        P_UN[\"{_escape_mermaid('External / Unknown')}\"]")
    lines.append("    end\n")

    # Subgraph Event & Channels
    lines.append("    subgraph EventTransport [\"⚡ Event & Buffers\"]")
    ev_safe = _node_safe_id(event.id)
    lines.append(f"        {ev_safe}[\"📦 {event.name}\"]")

    channel_ids = list(dict.fromkeys([
        e.target_id
        for e in graph.edges
        if e.source_id == event.id and e.edge_type == EdgeType.ROUTED_THROUGH
    ]))
    for ch_id in channel_ids:
        ch = graph.find_node(ch_id)
        if ch:
            ch_safe = _node_safe_id(ch.id)
            if ch.channel_type == ChannelType.REDIS_BATCH:
                cfg = ch.configuration
                w = cfg.get("window_seconds", 30)
                m = cfg.get("max_batch_size", 25)
                lines.append(f"        {ch_safe}[\"Буфер Redis<br/><i>{w}с / макс {m}</i>\"]")
            else:
                lines.append(f"        {ch_safe}[\"{ch.name}\"]")
    lines.append("    end\n")

    # Subgraph Consumers
    lines.append("    subgraph Consumers [\"🎯 Handlers\"]")
    if handlers:
        for h in handlers:
            h_safe = _node_safe_id(h.id)
            batch_label = "<br/><i>Batch Handler</i>" if h.is_batch else ""
            lines.append(f"        {h_safe}[\"{h.name}{batch_label}\"]")
    else:
        lines.append(f"        H_NONE[\"{_escape_mermaid('No active listeners')}\"]")
    lines.append("    end\n")

    # Flow Edges
    added_edges: set[str] = set()

    def add_flow_edge(src: str, dst: str, lbl: str) -> None:
        edge_key = f"{src}->{dst}"
        if edge_key not in added_edges:
            added_edges.add(edge_key)
            lines.append(f"    {src} -->|{lbl}| {dst}")

    if producers:
        for s in producers:
            add_flow_edge(_node_safe_id(s.id), ev_safe, "publish")
    else:
        add_flow_edge("P_UN", ev_safe, "publish")

    for h in handlers:
        h_safe = _node_safe_id(h.id)
        if h.is_batch:
            chan_id = f"channel.redis_batch.{h.name}"
            ch_safe = _node_safe_id(chan_id)
            add_flow_edge(ev_safe, ch_safe, "buffer")
            add_flow_edge(ch_safe, h_safe, "flush batch")
        else:
            add_flow_edge(ev_safe, h_safe, "dispatch")

    # CSS classes
    lines.extend([
        "",
        "    classDef service fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;",
        "    classDef event fill:#fff3e0,stroke:#f57c00,stroke-width:2px;",
        "    classDef handler fill:#f1f8e9,stroke:#689f38,stroke-width:2px;",
        "    classDef channel fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;",
        f"    class {ev_safe} event;",
    ])
    if producers:
        lines.append(f"    class {','.join(_node_safe_id(s.id) for s in producers)} service;")
    if handlers:
        lines.append(f"    class {','.join(_node_safe_id(h.id) for h in handlers)} handler;")

    return "\n".join(lines)


def generate_use_case_flowchart(uc: UseCaseNode, graph: ArchitectureGraph) -> str:
    """Generate localized Mermaid flowchart for an individual application Use Case."""
    lines = ["flowchart LR"]
    uc_safe = _node_safe_id(uc.id)

    # 1. Triggers (HTTP Routes)
    routes = graph.get_entrypoints_for_use_case(uc.id)
    if routes:
        lines.append("    subgraph Triggers [\"🌐 Entrypoints\"]")
        for r in routes:
            r_safe = _node_safe_id(r.id)
            lines.append(f"        {r_safe}[\"{r.name}\"]")
        lines.append("    end\n")

    # 2. Use Case
    lines.append(f"    subgraph Workflow [\"🎬 Use Case\"]\n        {uc_safe}[\"{uc.name}\"]\n    end\n")

    # 3. Services
    services = [e.target_id for e in graph.edges if e.source_id == uc.id and e.edge_type == EdgeType.ORCHESTRATES]
    if services:
        lines.append("    subgraph DomainServices [\"🚀 Domain Services\"]")
        for sid in services:
            snode = graph.find_node(sid)
            if snode:
                lines.append(f"        {_node_safe_id(sid)}[\"{snode.name}\"]")
        lines.append("    end\n")

    # 4. Storage Entities
    reads, writes = graph.get_storage_for_node(uc.id)
    # Also include storage from called services
    for sid in services:
        s_reads, s_writes = graph.get_storage_for_node(sid)
        reads.extend(s_reads)
        writes.extend(s_writes)
    reads = list({st.id: st for st in reads}.values())
    writes = list({st.id: st for st in writes}.values())
    all_storage = list({st.id: st for st in (reads + writes)}.values())

    if reads or writes:
        lines.append("    subgraph Persistence [\"💾 Storage / DB\"]")
        for st in all_storage:
            lines.append(f"        {_node_safe_id(st.id)}[(\"{st.name}\")]")
        lines.append("    end\n")

    # 5. Published Events
    published_events_map: dict[str, DomainEventNode] = {}
    for sid in [uc.id] + services:
        ev_ids = [e.target_id for e in graph.edges if e.source_id == sid and e.edge_type == EdgeType.PUBLISHES]
        for eid in ev_ids:
            ev = graph.find_event(eid)
            if ev and ev.id not in published_events_map:
                published_events_map[ev.id] = ev
    published_events = list(published_events_map.values())

    if published_events:
        lines.append("    subgraph EventsEmitted [\"📦 Emitted Events\"]")
        for ev in published_events:
            lines.append(f"        {_node_safe_id(ev.id)}[\"📦 {ev.name}\"]")
        lines.append("    end\n")

    # Connect nodes accurately using real graph edges (no Cartesian product)
    added_uc_edges: set[str] = set()

    def add_uc_edge(src: str, dst: str, style: str = "-->", lbl: str = "") -> None:
        key = f"{src}->{dst}"
        if key not in added_uc_edges:
            added_uc_edges.add(key)
            if lbl:
                lines.append(f"    {src} {style}|{lbl}| {dst}")
            else:
                lines.append(f"    {src} {style} {dst}")

    if routes:
        for r in routes:
            add_uc_edge(_node_safe_id(r.id), uc_safe)

    if services:
        for sid in services:
            add_uc_edge(uc_safe, _node_safe_id(sid))
            # Connect only storage/events this specific service touches
            for e in graph.edges:
                if e.source_id == sid:
                    if e.edge_type == EdgeType.WRITES_TO and any(st.id == e.target_id for st in writes):
                        add_uc_edge(_node_safe_id(sid), _node_safe_id(e.target_id), "-.->", "writes")
                    elif e.edge_type == EdgeType.READS_FROM and any(st.id == e.target_id for st in reads):
                        add_uc_edge(_node_safe_id(sid), _node_safe_id(e.target_id), "-.->", "reads")
                    elif e.edge_type == EdgeType.PUBLISHES and any(ev.id == e.target_id for ev in published_events):
                        add_uc_edge(_node_safe_id(sid), _node_safe_id(e.target_id), "-->", "publishes")

    # Direct operations by UseCase itself (without service)
    for e in graph.edges:
        if e.source_id == uc.id:
            if e.edge_type == EdgeType.WRITES_TO and any(st.id == e.target_id for st in writes):
                add_uc_edge(uc_safe, _node_safe_id(e.target_id), "-.->", "persists")
            elif e.edge_type == EdgeType.READS_FROM and any(st.id == e.target_id for st in reads):
                add_uc_edge(uc_safe, _node_safe_id(e.target_id), "-.->", "reads")
            elif e.edge_type == EdgeType.PUBLISHES and any(ev.id == e.target_id for ev in published_events):
                add_uc_edge(uc_safe, _node_safe_id(e.target_id), "-->", "publishes")

    lines.extend([
        "",
        "    classDef entrypoint fill:#e0f2f1,stroke:#00897b,stroke-width:2px;",
        "    classDef uc fill:#fce4ec,stroke:#c2185b,stroke-width:2px;",
        "    classDef service fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;",
        "    classDef storage fill:#ede7f6,stroke:#512da8,stroke-width:2px;",
        "    classDef event fill:#fff3e0,stroke:#f57c00,stroke-width:2px;",
        f"    class {uc_safe} uc;",
    ])
    if routes:
        lines.append(f"    class {','.join(_node_safe_id(r.id) for r in routes)} entrypoint;")
    if services:
        lines.append(f"    class {','.join(_node_safe_id(s) for s in services)} service;")

    return "\n".join(lines)


def generate_domain_diagram(domain: str, graph: ArchitectureGraph) -> str:
    """Generate clean, untangled end-to-end architecture diagram for a single bounded context."""
    comps = graph.get_domain_components(domain)
    routes = comps["entrypoints"]
    use_cases = comps["use_cases"]
    services = comps["services"]
    storage = comps["storage"]
    events = comps["events"]

    # 1. Sort use cases in logical domain workflow order
    def _uc_sort_key(u: UseCaseNode) -> tuple[int, str]:
        name = u.name.lower()
        if name.startswith(("create", "add", "register", "insert", "new")):
            return (0, u.name)
        if name.startswith(("get", "find", "fetch", "read", "view", "list")):
            return (1, u.name)
        if name.startswith(("update", "edit", "patch", "modify", "change")):
            return (2, u.name)
        if name.startswith(("delete", "remove", "destroy", "cancel")):
            return (3, u.name)
        return (4, u.name)

    sorted_ucs = sorted(use_cases, key=_uc_sort_key)[:8]
    uc_ids = {u.id for u in sorted_ucs}

    # 2. Align routes opposite the use cases they trigger (prevents 'X' crossed lines!)
    aligned_routes: list[EntrypointNode] = []
    seen_route_ids: set[str] = set()
    for u in sorted_ucs:
        for r in routes:
            if u.id in r.target_use_case_ids and r.id not in seen_route_ids:
                aligned_routes.append(r)
                seen_route_ids.add(r.id)

    # Append remaining routes (e.g. direct query endpoints)
    for r in routes:
        if r.id not in seen_route_ids:
            aligned_routes.append(r)
            seen_route_ids.add(r.id)

    aligned_routes = aligned_routes[:8]

    # 3. Determine relevant services orchestrated by displayed use cases
    rel_svc_ids: set[str] = set()
    for u in sorted_ucs:
        for e in graph.edges:
            if e.source_id == u.id and e.edge_type == EdgeType.ORCHESTRATES:
                rel_svc_ids.add(e.target_id)
    for r in aligned_routes:
        if not any(ucid in uc_ids for ucid in r.target_use_case_ids):
            rel_svc_ids.update(r.target_service_ids)

    disp_services = [s for s in services if s.id in rel_svc_ids][:4]
    if not disp_services and services:
        disp_services = services[:4]
    disp_svc_ids = {s.id for s in disp_services}

    disp_storage = storage[:4]
    disp_events = events[:4]

    lines = ["flowchart LR"]

    if aligned_routes:
        lines.append('    subgraph Ingress ["🌐 API Endpoints"]')
        for r in aligned_routes:
            lines.append(f'        {_node_safe_id(r.id)}["{_escape_mermaid(r.name)}"]')
        lines.append("    end\n")

    if sorted_ucs:
        lines.append('    subgraph Workflows ["🎬 Use Cases"]')
        for u in sorted_ucs:
            lines.append(f'        {_node_safe_id(u.id)}["{_escape_mermaid(u.name)}"]')
        lines.append("    end\n")

    if disp_services:
        lines.append('    subgraph Svc ["🚀 Domain Services"]')
        for s in disp_services:
            lines.append(f'        {_node_safe_id(s.id)}["{_escape_mermaid(s.name)}"]')
        lines.append("    end\n")

    if disp_storage:
        lines.append('    subgraph DB ["💾 Storage & Tables"]')
        for st in disp_storage:
            lines.append(f'        {_node_safe_id(st.id)}[(\"{_escape_mermaid(st.name)}\")]')
        lines.append("    end\n")

    if disp_events:
        lines.append('    subgraph Ev ["📦 Domain Events"]')
        for ev in disp_events:
            lines.append(f'        {_node_safe_id(ev.id)}["📦 {_escape_mermaid(ev.name)}"]')
        lines.append("    end\n")

    added_edges: set[str] = set()

    def add_edge(src: str, dst: str, style: str = "-->", lbl: str = "") -> None:
        key = f"{src}->{dst}"
        if key not in added_edges:
            added_edges.add(key)
            if lbl:
                lines.append(f"    {src} {style}|{lbl}| {dst}")
            else:
                lines.append(f"    {src} {style} {dst}")

    # 1. Routes -> Use Cases (parallel horizontal lines; NO bypass to service if UC exists!)
    for r in aligned_routes:
        triggered_any_uc = False
        for ucid in r.target_use_case_ids:
            if ucid in uc_ids:
                add_edge(_node_safe_id(r.id), _node_safe_id(ucid))
                triggered_any_uc = True
        if not triggered_any_uc:
            for sid in r.target_service_ids:
                if sid in disp_svc_ids:
                    add_edge(_node_safe_id(r.id), _node_safe_id(sid))

    # 2. Use Cases -> Services
    for u in sorted_ucs:
        for e in graph.edges:
            if e.source_id == u.id and e.edge_type == EdgeType.ORCHESTRATES and e.target_id in disp_svc_ids:
                add_edge(_node_safe_id(u.id), _node_safe_id(e.target_id))

    # 3. Services -> Storage & Events
    for s in disp_services:
        for e in graph.edges:
            if e.source_id == s.id:
                if e.edge_type == EdgeType.WRITES_TO and any(st.id == e.target_id for st in disp_storage):
                    add_edge(_node_safe_id(s.id), _node_safe_id(e.target_id), "-.->", "writes")
                elif e.edge_type == EdgeType.READS_FROM and any(st.id == e.target_id for st in disp_storage):
                    add_edge(_node_safe_id(s.id), _node_safe_id(e.target_id), "-.->", "reads")
                elif e.edge_type == EdgeType.PUBLISHES and any(ev.id == e.target_id for ev in disp_events):
                    add_edge(_node_safe_id(s.id), _node_safe_id(e.target_id), "-->", "publishes")

    # 4. Direct Use Case persistence/publishing if not routed through a service
    for u in sorted_ucs:
        for e in graph.edges:
            if e.source_id == u.id:
                if e.edge_type == EdgeType.WRITES_TO and any(st.id == e.target_id for st in disp_storage):
                    add_edge(_node_safe_id(u.id), _node_safe_id(e.target_id), "-.->", "persists")
                elif e.edge_type == EdgeType.READS_FROM and any(st.id == e.target_id for st in disp_storage):
                    add_edge(_node_safe_id(u.id), _node_safe_id(e.target_id), "-.->", "reads")
                elif e.edge_type == EdgeType.PUBLISHES and any(ev.id == e.target_id for ev in disp_events):
                    add_edge(_node_safe_id(u.id), _node_safe_id(e.target_id), "-->", "publishes")

    lines.extend([
        "",
        "    classDef entrypoint fill:#e0f2f1,stroke:#00897b,stroke-width:2px;",
        "    classDef uc fill:#fce4ec,stroke:#c2185b,stroke-width:2px;",
        "    classDef service fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;",
        "    classDef storage fill:#ede7f6,stroke:#512da8,stroke-width:2px;",
        "    classDef event fill:#fff3e0,stroke:#f57c00,stroke-width:2px;",
    ])
    return "\n".join(lines)


def generate_system_overview(graph: ArchitectureGraph) -> str:
    """Generate high-level Bounded Context Architecture Map with full system topology."""
    from karkas.core.domain import DOMAIN_DISPLAY_TITLES

    lines = [
        "flowchart TB",
        "    subgraph Ingress [\"🌐 Ingress & Client Entrypoints\"]",
        f"        API[\"⚡ FastAPI REST Services ({len(graph.entrypoints)} routes)\"]",
        "        WORKER[\"⚙️ Taskiq Background Workers & Schedulers\"]",
        "    end\n",
        "    subgraph Contexts [\"🏰 Domain Bounded Contexts\"]",
    ]

    discovered_domains = graph.get_domains()
    if not discovered_domains:
        discovered_domains = ["auth", "booking", "ticket", "order", "listing", "event", "notification", "storage", "dashboard"]

    for domain in discovered_domains:
        d_name = domain.capitalize()
        d_title = DOMAIN_DISPLAY_TITLES.get(domain, d_name)
        comps = graph.get_domain_components(domain)
        d_routes = comps["entrypoints"]
        d_ucs = comps["use_cases"]
        d_services = comps["services"]
        d_tables = comps["storage"]
        d_events = comps["events"]

        details = []
        if d_routes:
            details.append(f"Routes: {len(d_routes)}")
        if d_ucs:
            details.append(f"Workflows: {len(d_ucs)}")
        if d_services:
            details.append(f"Services: {len(d_services)}")
        if d_tables:
            tbl_preview = ", ".join(t.name for t in d_tables[:2])
            details.append(f"Tables: {tbl_preview}")
        if d_events:
            details.append(f"Events: {len(d_events)}")

        summary_text = "<br/>".join(details) if details else "Domain logic"
        lines.append(f"        subgraph Ctx_{domain} [\"{d_name} Context\"]")
        lines.append(f"            node_{domain}[\"<b>{d_title}</b><br/>{summary_text}\"]")
        lines.append("        end\n")

    lines.append("    end\n")

    # Messaging Infrastructure
    lines.extend([
        "    subgraph Transport [\"⚡ Async Messaging & Batching Infrastructure\"]",
        "        BUS[\"InMemory EventBus (Domain Events Dispatcher)\"]",
        "        REDIS_BUF[\"Redis Batch Buffers (Sliding Window: 30s / 25 items)\"]",
        "        HANDLERS[\"🎯 Async Event Handlers & Analytics Sync\"]",
        "        BUS --> REDIS_BUF --> HANDLERS",
        "    end\n",
        "    subgraph DataTier [\"💾 Unified Persistence Tier\"]",
        "        DB_PG[(\"PostgreSQL (ACID Relational Core)\")]",
        "        DB_REDIS[(\"Redis (Token Blacklist & Buffers)\")]",
        "        DB_CH[(\"ClickHouse (Analytical Event Log)\")]",
        "    end\n",
    ])

    # Connect Ingress to Contexts
    for domain in discovered_domains:
        comps = graph.get_domain_components(domain)
        if comps["entrypoints"]:
            lines.append(f"    API --> Ctx_{domain}")

    lines.append("    WORKER ==> Transport\n")

    # Domain -> EventBus publications
    for domain in discovered_domains:
        comps = graph.get_domain_components(domain)
        if comps["events"]:
            lines.append(f"    Ctx_{domain} -.->|{len(comps['events'])} events| BUS")

    # Key cross-domain business flows
    if "booking" in discovered_domains and "ticket" in discovered_domains:
        lines.append("    Ctx_booking -.->|allocates inventory| Ctx_ticket")
    if "order" in discovered_domains and "ticket" in discovered_domains:
        lines.append("    Ctx_order -.->|fulfills items| Ctx_ticket")

    lines.extend([
        "    HANDLERS -.->|batch sync| DB_CH",
        "    HANDLERS -.->|async updates| DB_PG",
        "    Contexts --> DB_PG",
        "    Ctx_auth --> DB_REDIS",
        "    Transport --> DB_REDIS",
        "",
        "    classDef ctx fill:#f8f9fa,stroke:#455a64,stroke-width:2px;",
        "    classDef transport fill:#ede7f6,stroke:#512da8,stroke-width:2px;",
        "    classDef ingress fill:#e0f2f1,stroke:#00897b,stroke-width:2px;",
        "    classDef datatier fill:#f3e5f5,stroke:#4a148c,stroke-width:2px;",
        "    class Ingress ingress;",
        "    class Transport transport;",
        "    class Contexts ctx;",
        "    class DataTier datatier;",
    ])

    return "\n".join(lines)


def generate_flow_sequence_diagram(flow: ProcessFlow, graph: ArchitectureGraph) -> str:
    """Generate Mermaid sequence diagram for end-to-end business flow."""
    lines = [
        "sequenceDiagram",
        "    autonumber",
        "    participant Service as 🚀 Domain Service",
        "    participant Bus as ⚡ Event Bus",
        "    participant Redis as 🔄 Redis Batch Buffer",
        "    participant Handler as 🎯 Event Handler",
        "    participant DB as 💾 Database / Storage",
    ]

    for ev_id in flow.event_ids:
        ev = graph.find_event(ev_id)
        if not ev:
            continue

        producers = graph.get_producers_for_event(ev.id)
        prod_name = producers[0].name if producers else "DomainService"
        handlers = graph.get_handlers_for_event(ev.id)

        lines.append(f"    Note over Service,DB: {ev.name}")
        lines.append(f"    Service->>Bus: {prod_name}.publish({ev.name})")

        has_batch = any(h.is_batch for h in handlers)
        if has_batch:
            lines.append("    Bus->>Redis: accumulate_batch(event, window=30s)")
            lines.append("    Redis-->>Handler: flush_batch(events)")
        else:
            lines.append("    Bus->>Handler: dispatch(event)")

        for h in handlers:
            lines.append(f"    Handler->>DB: execute({h.name})")

    return "\n".join(lines)


def _node_safe_id(raw_id: str) -> str:
    """Convert an arbitrary string ID into a valid Mermaid node identifier."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", raw_id)
    if clean and clean[0].isdigit():
        clean = f"n_{clean}"
    return clean or "node"


def _escape_mermaid(text: str) -> str:
    return text.replace('"', "'").replace("[[", "").replace("]]", "")
