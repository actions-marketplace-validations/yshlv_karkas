"""Breaking change diff engine for comparing ArchitectureGraph snapshots."""

from enum import StrEnum

from pydantic import BaseModel, Field

from archdoc.core.ir import ArchitectureGraph, DomainEventNode


class ChangeLevel(StrEnum):
    BREAKING = "BREAKING"
    WARNING = "WARNING"
    COMPATIBLE = "COMPATIBLE"
    INFO = "INFO"


class ChangeItem(BaseModel):
    level: ChangeLevel
    component_type: str  # "event", "handler", "service", "channel"
    component_id: str
    message: str
    details: dict[str, str] = Field(default_factory=dict)


class DiffReport(BaseModel):
    has_breaking_changes: bool = False
    items: list[ChangeItem] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Render diff report as markdown for CI/CD or PR comments."""
        if not self.items:
            return "### 🟢 ArchDoc Contract Check: No architectural breaking changes detected."

        status_emoji = "🔴" if self.has_breaking_changes else "🟡"
        lines = [
            f"### {status_emoji} ArchDoc Architecture & Contract Diff Report",
            "",
            f"**Status:** {'BREAKING CHANGES DETECTED' if self.has_breaking_changes else 'Changes are backward-compatible.'}",
            "",
            "| Level | Component | Change |",
            "| :---: | :--- | :--- |",
        ]

        for item in self.items:
            badge = "🔴 BREAKING" if item.level == ChangeLevel.BREAKING else ("🟡 WARNING" if item.level == ChangeLevel.WARNING else "🟢 COMPATIBLE")
            lines.append(f"| {badge} | `{item.component_id}` | {item.message} |")

        return "\n".join(lines)


def diff_graphs(base: ArchitectureGraph, head: ArchitectureGraph) -> DiffReport:
    """Compare base graph (e.g. main branch) and head graph (PR)."""
    report = DiffReport()

    base_events = {e.name: e for e in base.events}
    head_events = {e.name: e for e in head.events}

    # 1. Check Events
    for name, base_ev in base_events.items():
        if name not in head_events:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.BREAKING,
                    component_type="event",
                    component_id=name,
                    message=f"Domain event `{name}` was removed.",
                )
            )
            report.has_breaking_changes = True
            continue

        head_ev = head_events[name]
        _compare_event_fields(base_ev, head_ev, report)

    # Check newly added events
    for name, head_ev in head_events.items():
        if name not in base_events:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.COMPATIBLE,
                    component_type="event",
                    component_id=name,
                    message=f"New domain event `{name}` added.",
                )
            )

    # 2. Check Handlers & Orphaned Events
    base_handlers = {h.name: h for h in base.handlers}
    head_handlers = {h.name: h for h in head.handlers}

    for name in base_handlers:
        if name not in head_handlers:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.WARNING,
                    component_type="handler",
                    component_id=name,
                    message=f"Handler `{name}` was removed.",
                )
            )

    # Check for newly orphaned events (events with consumers in base that lost all consumers in head)
    for name in head_events:
        base_h = base.get_handlers_for_event(name) if name in base_events else []
        head_h = head.get_handlers_for_event(name)
        if base_h and not head_h:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.WARNING,
                    component_type="event",
                    component_id=name,
                    message=f"Domain event `{name}` no longer has any active consumers/handlers.",
                )
            )

    # 3. Check Removed Entrypoints (API Routes)
    base_routes = {ep.name: ep for ep in base.entrypoints}
    head_routes = {ep.name: ep for ep in head.entrypoints}
    for name in base_routes:
        if name not in head_routes:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.WARNING,
                    component_type="entrypoint",
                    component_id=name,
                    message=f"API Entrypoint `{name}` was removed.",
                )
            )

    return report


def _compare_event_fields(base_ev: DomainEventNode, head_ev: DomainEventNode, report: DiffReport) -> None:
    base_fields = {f.name: f for f in base_ev.fields}
    head_fields = {f.name: f for f in head_ev.fields}

    for f_name, b_field in base_fields.items():
        if f_name not in head_fields:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.BREAKING,
                    component_type="event",
                    component_id=base_ev.name,
                    message=f"Field `{f_name}` was removed from event `{base_ev.name}` payload.",
                )
            )
            report.has_breaking_changes = True
        else:
            h_field = head_fields[f_name]
            if b_field.type_repr != h_field.type_repr:
                report.items.append(
                    ChangeItem(
                        level=ChangeLevel.BREAKING,
                        component_type="event",
                        component_id=base_ev.name,
                        message=f"Field `{f_name}` type changed from `{b_field.type_repr}` to `{h_field.type_repr}`.",
                    )
                )
                report.has_breaking_changes = True

    for f_name, h_field in head_fields.items():
        if f_name not in base_fields:
            if h_field.required and not h_field.default_repr:
                report.items.append(
                    ChangeItem(
                        level=ChangeLevel.BREAKING,
                        component_type="event",
                        component_id=base_ev.name,
                        message=f"Required field `{f_name}` without default added to `{base_ev.name}`.",
                    )
                )
                report.has_breaking_changes = True
            else:
                report.items.append(
                    ChangeItem(
                        level=ChangeLevel.COMPATIBLE,
                        component_type="event",
                        component_id=base_ev.name,
                        message=f"Optional field `{f_name}` added to `{base_ev.name}`.",
                    )
                )
