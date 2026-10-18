"""AI Agent Context renderer: generates architecture_context.md and architecture_graph.json."""

from pathlib import Path

from archdoc.core.ir import ArchitectureGraph, EdgeType


def render_agent_context_markdown(graph: ArchitectureGraph, output_file: str | Path) -> None:
    """Generate high-density, token-optimized architecture context for LLMs."""
    path = Path(output_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {graph.project_name.upper()} Architecture Snapshot (for AI Agents)",
        "",
        "> Authoritative architectural contracts, top-down entrypoint call graphs, and event flow topology. Keep this context in mind when writing or modifying services, event handlers, and database models.",
        "",
        "## 1. System Topology Overview",
        f"- **Project Root:** `{graph.project_root}`",
        f"- **API Routes & Entrypoints:** {len(graph.entrypoints)}",
        f"- **Application Use Cases:** {len(graph.use_cases)}",
        f"- **Domain Services:** {len(graph.services)}",
        f"- **Domain Events:** {len(graph.events)}",
        f"- **Event Handlers & Background Tasks:** {len(graph.handlers)}",
        f"- **Storage Entities & Tables:** {len(graph.storage_entities)}",
        "",
        "## 2. API Entrypoints & Workflows (Top-Down)",
        "",
    ]

    for ep in graph.entrypoints[:25]:
        target_ucs = []
        for ucid in ep.target_use_case_ids:
            uc = graph.find_node(ucid)
            if uc:
                target_ucs.append(f"`{uc.name}()`")
        uc_str = f" -> invokes {', '.join(target_ucs)}" if target_ucs else ""
        summary_str = f": {ep.summary}" if ep.summary else ""
        lines.append(f"- **`{ep.name}`**{uc_str}{summary_str}")

    if len(graph.entrypoints) > 25:
        lines.append(f"- *...and {len(graph.entrypoints) - 25} more routes.*")

    lines.extend([
        "",
        "## 3. Core Application Use Cases & Persistence",
        "",
    ])

    for uc in graph.use_cases:
        _reads, writes = graph.get_storage_for_node(uc.id)
        service_ids = [e.target_id for e in graph.edges if e.source_id == uc.id and e.edge_type == EdgeType.ORCHESTRATES]
        for sid in service_ids:
            _s_reads, s_writes = graph.get_storage_for_node(sid)
            writes.extend(s_writes)
        storage_names = sorted({st.name for st in writes})
        service_names = sorted({sid.replace("service.", "") for sid in service_ids})
        lines.append(
            f"- **`{uc.name}`** (`{uc.domain}`): {uc.summary or 'Use case.'} "
            f"[Services: {', '.join(service_names) if service_names else 'Direct UoW'}; "
            f"Tables: {', '.join(storage_names) if storage_names else 'None'}]"
        )

    lines.extend([
        "",
        "## 4. Domain Events Contract Catalog & Delivery Routing",
        "",
    ])

    for ev in sorted(graph.events, key=lambda x: x.name):
        producers = graph.get_producers_for_event(ev.id)
        handlers = graph.get_handlers_for_event(ev.id)

        field_strs = []
        for f in ev.fields:
            opt = "?" if not f.required else ""
            field_strs.append(f"{f.name}{opt}: {f.type_repr}")
        payload_sig = "{" + ", ".join(field_strs) + "}" if field_strs else "{}"

        prod_names = ", ".join(p.name for p in producers) if producers else "Use Cases / Services"

        handler_details = []
        for h in handlers:
            if h.is_batch and h.batch_config:
                w = h.batch_config.get("window_seconds", 30)
                m = h.batch_config.get("max_batch_size", 25)
                handler_details.append(f"`{h.name}` (Redis Batch: {w}s / {m} items)")
            else:
                handler_details.append(f"`{h.name}` (Direct)")

        handlers_str = "; ".join(handler_details) if handler_details else "None"

        lines.extend([
            f"### `{ev.name}`",
            f"- **Doc:** {ev.summary or 'Domain fact.'}",
            f"- **Contract Payload:** `{payload_sig}`",
            f"- **Published by:** `{prod_names}`",
            f"- **Consumed by:** {handlers_str}",
            "",
        ])

    lines.extend([
        "## 5. Storage Entities & Persisted Tables",
        "",
    ])
    for st in sorted(graph.storage_entities, key=lambda x: x.name):
        pk_cols = [c["name"] for c in st.columns_or_fields if c.get("primary_key")]
        pk_str = f" (PK: {', '.join(pk_cols)})" if pk_cols else ""
        lines.append(f"- **{st.engine.upper()} Table:** `{st.name}`{pk_str}")

    path.write_text("\n".join(lines), encoding="utf-8")


def render_ir_json(graph: ArchitectureGraph, output_file: str | Path) -> None:
    """Dump complete machine-readable ArchitectureGraph to JSON."""
    path = Path(output_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
