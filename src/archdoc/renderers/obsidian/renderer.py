"""Obsidian Vault markdown generator with Mermaid diagrams and wikilinks."""

import json
from pathlib import Path

from archdoc.core.docstring import format_docstring_markdown
from archdoc.core.ir import (
    ArchitectureGraph,
    DomainEventNode,
    EdgeType,
    EntrypointNode,
    HandlerNode,
    ProcessFlow,
    ServiceNode,
    StorageEntityNode,
    UseCaseNode,
)
from archdoc.renderers.mermaid import (
    generate_domain_diagram,
    generate_event_flowchart,
    generate_flow_sequence_diagram,
    generate_system_overview,
    generate_use_case_flowchart,
)


class ObsidianVaultRenderer:
    """Renders complete interconnected Obsidian vault from ArchitectureGraph."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).resolve()

    def render(self, graph: ArchitectureGraph) -> None:
        """Render all vault directories and markdown files."""
        entrypoints_dir = self.output_dir / "entrypoints"
        use_cases_dir = self.output_dir / "use_cases"
        services_dir = self.output_dir / "services"
        events_dir = self.output_dir / "events"
        handlers_dir = self.output_dir / "handlers"
        storage_dir = self.output_dir / "storage"
        flows_dir = self.output_dir / "flows"
        domains_dir = self.output_dir / "domains"

        for d in (entrypoints_dir, use_cases_dir, services_dir, events_dir, handlers_dir, storage_dir, flows_dir, domains_dir):
            d.mkdir(parents=True, exist_ok=True)

        # 1. Render Entrypoints
        for ep in graph.entrypoints:
            safe_fname = _safe_filename(ep.name)
            self._render_entrypoint(ep, graph, entrypoints_dir / f"{safe_fname}.md")

        # 2. Render Use Cases
        for uc in graph.use_cases:
            self._render_use_case(uc, graph, use_cases_dir / f"{uc.name}.md")

        # 3. Render Services
        for s in graph.services:
            self._render_service(s, graph, services_dir / f"{s.name}.md")

        # 4. Render Events
        for ev in graph.events:
            self._render_event(ev, graph, events_dir / f"{ev.name}.md")

        # 5. Render Handlers
        for h in graph.handlers:
            self._render_handler(h, graph, handlers_dir / f"{h.name}.md")

        # 6. Render Storage
        for st in graph.storage_entities:
            self._render_storage(st, graph, storage_dir / f"{st.name}.md")

        # 7. Render Flows
        for fl in graph.flows:
            self._render_flow(fl, graph, flows_dir / f"{fl.name}.md")

        # 8. Render Domains
        for dom in graph.get_domains():
            self._render_domain(dom, graph, domains_dir / f"{dom}.md")

        # 9. Render Index (MOC)
        self._render_index(graph, self.output_dir / "index.md")

    def _render_entrypoint(self, ep: EntrypointNode, graph: ArchitectureGraph, path: Path) -> None:
        lines = [
            "---",
            "type: entrypoint",
            f"name: \"{ep.name}\"",
            f"entrypoint_type: {ep.entrypoint_type}",
            f"domain: {ep.domain or 'general'}",
            "tags:",
            "  - architecture/entrypoint",
            f"  - domain/{ep.domain or 'general'}",
            "---",
            "",
            f"# 🌐 `{ep.name}`",
            "",
        ]

        if ep.docstring:
            lines.append(format_docstring_markdown(ep.docstring))
            lines.append("")

        if ep.location:
            lines.append(f"📁 **Location:** `{ep.location.file_path}:{ep.location.start_line}`\n")

        lines.extend([
            "---",
            "",
            "## 🎬 Triggered Application Workflows",
            "",
        ])

        if ep.target_use_case_ids:
            for ucid in ep.target_use_case_ids:
                uc = graph.find_node(ucid)
                uc_name = uc.name if uc else ucid
                summary = f" — *{uc.summary}*" if uc and uc.summary else ""
                lines.append(f"- [[{uc_name}]]{summary}")
        else:
            lines.append("*Direct handler or repository execution.*")

        lines.extend([
            "",
            "## 🚀 Directly Called Services",
            "",
        ])
        if ep.target_service_ids:
            for sid in ep.target_service_ids:
                s = graph.find_node(sid)
                s_name = s.name if s else sid
                summary = f" — *{s.summary}*" if s and s.summary else ""
                lines.append(f"- [[{s_name}]]{summary}")
        else:
            lines.append("*No direct service dependencies.*")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_use_case(self, uc: UseCaseNode, graph: ArchitectureGraph, path: Path) -> None:
        flowchart_code = generate_use_case_flowchart(uc, graph)
        routes = graph.get_entrypoints_for_use_case(uc.id)
        services = [graph.find_node(e.target_id) for e in graph.edges if e.source_id == uc.id and e.edge_type == EdgeType.ORCHESTRATES]
        services = [s for s in services if s]

        reads, writes = graph.get_storage_for_node(uc.id)
        for s in services:
            s_reads, s_writes = graph.get_storage_for_node(s.id)
            reads.extend(s_reads)
            writes.extend(s_writes)
        reads = list({st.id: st for st in reads}.values())
        writes = list({st.id: st for st in writes}.values())

        published_ev_map: dict[str, DomainEventNode] = {}
        for e in graph.edges:
            if (e.source_id == uc.id or any(s.id == e.source_id for s in services)) and e.edge_type == EdgeType.PUBLISHES:
                ev = graph.find_event(e.target_id)
                if ev and ev.id not in published_ev_map:
                    published_ev_map[ev.id] = ev
        published_ev_nodes = list(published_ev_map.values())

        lines = [
            "---",
            "type: use_case",
            f"name: {uc.name}",
            f"domain: {uc.domain}",
            "tags:",
            "  - architecture/use_case",
            f"  - domain/{uc.domain}",
            "---",
            "",
            f"# 🎬 {uc.name}",
            "",
        ]

        if uc.docstring:
            lines.append(format_docstring_markdown(uc.docstring))
            lines.append("")

        if uc.location:
            lines.append(f"📁 **Location:** `{uc.location.file_path}:{uc.location.start_line}`\n")

        lines.extend([
            "---",
            "",
            "## 🔄 Workflow Execution Flow",
            "",
            "```mermaid",
            flowchart_code,
            "```",
            "",
            "---",
            "",
            "## 🌐 Triggering Entrypoints",
            "",
        ])

        if routes:
            for r in routes:
                r_fname = _safe_filename(r.name)
                summary = f" — *{r.summary}*" if r.summary else ""
                lines.append(f"- [[{r_fname}|`{r.name}`]]{summary}")
        else:
            lines.append("*Internal use case (invoked programmatically).*")

        lines.extend([
            "",
            "## 🚀 Orchestrated Domain Services",
            "",
        ])
        if services:
            for s in services:
                summary = f" — *{s.summary}*" if s.summary else ""
                lines.append(f"- [[{s.name}]]{summary}")
        elif uc.orchestrated_services:
            for sc in uc.orchestrated_services:
                lines.append(f"- `⚙️ {sc}()`")
        else:
            lines.append("*Direct repository / UoW execution.*")

        lines.extend([
            "",
            "## 💾 Persistence & Storage Access",
            "",
        ])
        if writes:
            for st in writes:
                lines.append(f"- ✍️ **Writes:** [[{st.name}]] ({st.engine.upper()})")
        if reads:
            for st in reads:
                lines.append(f"- 📖 **Reads:** [[{st.name}]] ({st.engine.upper()})")
        if not writes and not reads and uc.repositories:
            for r in uc.repositories:
                lines.append(f"- `💾 {r}`")
        elif not writes and not reads:
            lines.append("*No database persistence operations recorded.*")

        lines.extend([
            "",
            "## 📦 Emitted Domain Events",
            "",
        ])
        if published_ev_nodes:
            for ev in published_ev_nodes:
                summary = f" — *{ev.summary}*" if ev.summary else ""
                lines.append(f"- [[{ev.name}]]{summary}")
        else:
            lines.append("*No domain events emitted.*")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_event(self, ev: DomainEventNode, graph: ArchitectureGraph, path: Path) -> None:
        producers = graph.get_producers_for_event(ev.id)
        handlers = graph.get_handlers_for_event(ev.id)
        flowchart_code = generate_event_flowchart(ev, graph)

        lines = [
            "---",
            "type: domain_event",
            f"name: {ev.name}",
            f"domain: {ev.domain or 'general'}",
            "tags:",
            "  - architecture/event",
            f"  - domain/{ev.domain or 'general'}",
            "---",
            "",
            f"# 📦 {ev.name}",
            "",
        ]

        if ev.docstring:
            lines.append(format_docstring_markdown(ev.docstring))
            lines.append("")

        if ev.location:
            lines.append(f"📁 **Location:** `{ev.location.file_path}:{ev.location.start_line}`\n")

        lines.extend([
            "---",
            "",
            "## 🔄 Event Lifecycle Flow",
            "",
            "```mermaid",
            flowchart_code,
            "```",
            "",
            "---",
            "",
            "## 📋 Data Contract Payload",
            "",
            "| Field | Type | Required | Description |",
            "| :--- | :--- | :---: | :--- |",
        ])

        if ev.fields:
            for f in ev.fields:
                req_badge = "✅" if f.required else "❌"
                desc = f.description or "-"
                clean_type = f.type_repr.replace("|", r"\|")
                lines.append(f"| `{f.name}` | `{clean_type}` | {req_badge} | {desc} |")
        else:
            lines.append("| *No fields extracted* | - | - | - |")

        if ev.json_schema:
            json_str = json.dumps(ev.json_schema, indent=2)
            callout_lines = [f"> {line}" for line in json_str.splitlines()]
            lines.extend([
                "",
                "> [!NOTE]- 🔍 Pydantic v2 JSON Schema Contract",
                "> ```json",
                *callout_lines,
                "> ```",
            ])

        lines.extend([
            "",
            "---",
            "",
            "## 🔗 Interconnected Nodes",
            f"- **Emitted by:** {', '.join(f'[[{p.name}]]' for p in producers) if producers else 'Direct Use Case / Service'}",
            f"- **Handled by:** {', '.join(f'[[{h.name}]]' for h in handlers) if handlers else 'No active handlers'}",
        ])

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_service(self, s: ServiceNode, graph: ArchitectureGraph, path: Path) -> None:
        published_events = []
        for e in graph.edges:
            if e.source_id == s.id and e.edge_type == EdgeType.PUBLISHES:
                ev = graph.find_node(e.target_id)
                if ev:
                    published_events.append(f"[[{ev.name}]]")

        reads, writes = graph.get_storage_for_node(s.id)

        lines = [
            "---",
            "type: service",
            f"name: {s.name}",
            f"domain: {s.domain or 'general'}",
            "tags:",
            "  - architecture/service",
            f"  - domain/{s.domain or 'general'}",
            "---",
            "",
            f"# 🚀 {s.name}",
            "",
        ]
        if s.docstring:
            lines.append(format_docstring_markdown(s.docstring))
            lines.append("")

        lines.extend([
            "## 💾 Persistence Operations",
            "",
        ])
        if writes:
            for st in writes:
                lines.append(f"- ✍️ **Writes:** [[{st.name}]] ({st.engine.upper()})")
        if reads:
            for st in reads:
                lines.append(f"- 📖 **Reads:** [[{st.name}]] ({st.engine.upper()})")
        if not writes and not reads and s.repositories:
            for r in s.repositories:
                lines.append(f"- `💾 {r}`")
        elif not writes and not reads:
            lines.append("*No direct repository operations recorded.*")

        lines.extend([
            "",
            "## 📤 Published Domain Events",
            "",
        ])
        if published_events:
            for pe in sorted(set(published_events)):
                lines.append(f"- {pe}")
        else:
            lines.append("*No published events detected.*")

        lines.extend([
            "",
            "## 🛠 Discovered Methods",
            "",
        ])
        for m in s.methods:
            lines.append(f"- `{m}()`")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_handler(self, h: HandlerNode, graph: ArchitectureGraph, path: Path) -> None:
        handled_events = []
        for ev_id in h.handled_event_ids:
            ev = graph.find_event(ev_id)
            if ev:
                handled_events.append(f"[[{ev.name}]]")

        writes = [graph.find_node(sid) for sid in h.persisted_storage_ids]
        writes = [st for st in writes if st]

        lines = [
            "---",
            "type: handler",
            f"name: {h.name}",
            f"is_batch: {h.is_batch}",
            "tags:",
            "  - architecture/handler",
            "---",
            "",
            f"# 🎯 {h.name}",
            "",
        ]
        if h.docstring:
            lines.append(format_docstring_markdown(h.docstring))
            lines.append("")

        if h.is_batch and h.batch_config:
            w = h.batch_config.get("window_seconds", 30)
            m = h.batch_config.get("max_batch_size", 25)
            lines.extend([
                "> [!TIP] **Redis Batch Buffer Configuration**",
                f"> - **Time Window:** {w} seconds",
                f"> - **Max Batch Size:** {m} events",
                "",
            ])

        lines.extend([
            "## 📥 Handled Events",
            "",
        ])
        if handled_events:
            for he in sorted(set(handled_events)):
                lines.append(f"- {he}")
        else:
            lines.append("*No handled events linked.*")

        if writes:
            lines.extend([
                "",
                "## 💾 Persists To",
                "",
            ])
            for st in writes:
                lines.append(f"- [[{st.name}]] ({st.engine.upper()})")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_storage(self, st: StorageEntityNode, graph: ArchitectureGraph, path: Path) -> None:
        writers: list[str] = []
        readers: list[str] = []

        for e in graph.edges:
            if e.target_id == st.id:
                src = graph.find_node(e.source_id)
                sname = src.name if src else e.source_id
                if e.edge_type == EdgeType.WRITES_TO:
                    writers.append(f"[[{sname}]]")
                elif e.edge_type == EdgeType.READS_FROM:
                    readers.append(f"[[{sname}]]")

        lines = [
            "---",
            "type: storage_entity",
            f"name: {st.name}",
            f"engine: {st.engine}",
            "tags:",
            "  - architecture/storage",
            "---",
            "",
            f"# 💾 {st.name} ({st.engine.upper()})",
            "",
            f"**Physical Name / Key:** `{st.table_or_key}`",
            "",
            "## 🔗 Accessing Services & Workflows",
            f"- **Writers:** {', '.join(sorted(set(writers))) if writers else 'None recorded'}",
            f"- **Readers:** {', '.join(sorted(set(readers))) if readers else 'None recorded'}",
            "",
            "## 📊 Schema Definition",
            "",
            "| Column / Key | Type | PK | Nullable |",
            "| :--- | :--- | :---: | :---: |",
        ]
        for col in st.columns_or_fields:
            pk = "🔑" if col.get("primary_key") else "-"
            nul = "Yes" if col.get("nullable") else "No"
            lines.append(f"| `{col.get('name')}` | `{col.get('type')}` | {pk} | {nul} |")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_domain(self, domain: str, graph: ArchitectureGraph, path: Path) -> None:
        dom_diagram = generate_domain_diagram(domain, graph)
        domain_lower = domain.lower()
        d_routes = [r for r in graph.entrypoints if r.domain == domain_lower]
        d_ucs = [u for u in graph.use_cases if u.domain == domain_lower]
        d_services = [s for s in graph.services if s.domain == domain_lower or domain_lower in s.name.lower()]
        d_events = [e for e in graph.events if e.domain == domain_lower or domain_lower in e.name.lower()]
        d_storage = [t for t in graph.storage_entities if t.domain == domain_lower or domain_lower in t.name.lower()]

        lines = [
            "---",
            "type: domain_context",
            f"name: {domain.capitalize()}",
            "tags:",
            "  - architecture/domain",
            f"  - domain/{domain_lower}",
            "---",
            "",
            f"# 🏰 {domain.capitalize()} Domain Architecture",
            "",
            "## 🔄 End-to-End Domain Architecture Flow",
            "",
            "```mermaid",
            dom_diagram,
            "```",
            "",
            "---",
            "",
            f"## 🌐 API Routes ({len(d_routes)})",
            "",
        ]
        for r in d_routes:
            r_fname = _safe_filename(r.name)
            summary = f" — *{r.summary}*" if r.summary else ""
            lines.append(f"- [[{r_fname}|`{r.name}`]]{summary}")

        lines.extend([
            "",
            f"## 🎬 Use Cases ({len(d_ucs)})",
            "",
        ])
        for u in d_ucs:
            summary = f" — *{u.summary}*" if u.summary else ""
            lines.append(f"- [[{u.name}]]{summary}")

        lines.extend([
            "",
            f"## 🚀 Domain Services ({len(d_services)})",
            "",
        ])
        for s in d_services:
            summary = f" — *{s.summary}*" if s.summary else ""
            lines.append(f"- [[{s.name}]]{summary}")

        lines.extend([
            "",
            f"## 💾 Storage & Tables ({len(d_storage)})",
            "",
        ])
        for t in d_storage:
            lines.append(f"- [[{t.name}]] ({t.engine.upper()})")

        lines.extend([
            "",
            f"## 📦 Domain Events ({len(d_events)})",
            "",
        ])
        for e in d_events:
            summary = f" — *{e.summary}*" if e.summary else ""
            lines.append(f"- [[{e.name}]]{summary}")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_flow(self, fl: ProcessFlow, graph: ArchitectureGraph, path: Path) -> None:
        seq_code = generate_flow_sequence_diagram(fl, graph)
        lines = [
            "---",
            "type: process_flow",
            f"name: {fl.name}",
            "tags:",
            "  - architecture/flow",
            "---",
            "",
            f"# 🔄 {fl.name}",
            "",
            f"> {fl.description or 'Business process flow.'}",
            "",
            "## 📊 Sequence Diagram",
            "",
            "```mermaid",
            seq_code,
            "```",
            "",
            "## 📦 Involved Events",
            "",
        ]
        for ev_id in fl.event_ids:
            ev = graph.find_event(ev_id)
            if ev:
                summary = f" — *{ev.summary}*" if ev.summary else ""
                lines.append(f"- [[{ev.name}]]{summary}")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _render_index(self, graph: ArchitectureGraph, path: Path) -> None:
        overview_code = generate_system_overview(graph)

        lines = [
            "---",
            "type: architecture_index",
            "tags:",
            "  - architecture/moc",
            "---",
            "",
            f"# 🗺️ {graph.project_name.upper()} Architecture Map of Content (MOC)",
            "",
            f"*Generated automatically on: `{graph.generated_at}`*",
            "",
            "## 📊 Architecture Metrics",
            f"- **API Routes & Ingress Points:** {len(graph.entrypoints)}",
            f"- **Application Use Cases:** {len(graph.use_cases)}",
            f"- **Domain Services:** {len(graph.services)}",
            f"- **Domain Events:** {len(graph.events)}",
            f"- **Event Handlers & Background Tasks:** {len(graph.handlers)}",
            f"- **Storage Entities & Tables:** {len(graph.storage_entities)}",
            f"- **End-to-End Business Flows:** {len(graph.flows)}",
            "",
            "---",
            "",
            "## 🌐 High-Level Bounded Context Architecture Topology",
            "",
            "```mermaid",
            overview_code,
            "```",
            "",
            "---",
            "",
            "## 🏰 Domain Bounded Contexts",
            "",
        ]
        for dom in graph.get_domains():
            d_name = dom.capitalize()
            lines.append(f"- 🏰 [[{dom}|{d_name} Domain Architecture]]")

        lines.extend([
            "",
            "---",
            "",
            "## 🌐 API Routes Catalog",
            "",
        ])
        for ep in graph.entrypoints:
            safe_fname = _safe_filename(ep.name)
            summary = f" — *{ep.summary}*" if ep.summary else ""
            lines.append(f"- [[{safe_fname}|`{ep.name}`]]{summary}")

        lines.extend([
            "",
            "## 🎬 Application Use Cases Catalog",
            "",
        ])
        for uc in sorted(graph.use_cases, key=lambda x: x.name):
            summary = f" — *{uc.summary}*" if uc.summary else ""
            lines.append(f"- [[{uc.name}]]{summary}")

        lines.extend([
            "",
            "## 🔄 End-to-End Business Flows",
            "",
        ])
        for fl in graph.flows:
            lines.append(f"- [[{fl.name}]] — {fl.description}")

        lines.extend([
            "",
            "## 🚀 Domain Services Catalog",
            "",
        ])
        for s in sorted(graph.services, key=lambda x: x.name):
            summary = f" — *{s.summary}*" if s.summary else ""
            lines.append(f"- [[{s.name}]]{summary}")

        lines.extend([
            "",
            "## 💾 Storage & Databases Catalog",
            "",
        ])
        for st in sorted(graph.storage_entities, key=lambda x: x.name):
            lines.append(f"- [[{st.name}]] ({st.engine.upper()})")

        lines.extend([
            "",
            "## 📦 Domain Events Catalog",
            "",
        ])
        for ev in sorted(graph.events, key=lambda x: x.name):
            summary = f" — *{ev.summary}*" if ev.summary else ""
            lines.append(f"- [[{ev.name}]]{summary}")

        lines.extend([
            "",
            "## 🎯 Handlers & Tasks Catalog",
            "",
        ])
        for h in sorted(graph.handlers, key=lambda x: x.name):
            badge = " *(Batch Buffer)*" if h.is_batch else ""
            summary = f" — *{h.summary}*" if h.summary else ""
            lines.append(f"- [[{h.name}]]{badge}{summary}")

        path.write_text("\n".join(lines), encoding="utf-8")


def _safe_filename(name: str) -> str:
    """Format string for clean cross-platform filename."""
    return (
        name.replace(" ", "_")
        .replace("/", "_")
        .replace(":", "_")
        .replace("{", "")
        .replace("}", "")
        .strip("_")
    )
