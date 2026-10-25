"""Breaking change diff engine for comparing ArchitectureGraph snapshots."""

from enum import StrEnum

from pydantic import BaseModel, Field

from karkas.core.ir import ArchitectureGraph, DomainEventNode


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
            return "### 🟢 Karkas Contract Check: No architectural breaking changes detected."

        status_emoji = "🔴" if self.has_breaking_changes else "🟡"
        lines = [
            f"### {status_emoji} Karkas Architecture & Contract Diff Report",
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
    """Compare base and head ArchitectureGraphs and flag breaking changes."""
    report = DiffReport()

    base_events: dict[str, DomainEventNode] = {e.name: e for e in base.events}
    head_events: dict[str, DomainEventNode] = {e.name: e for e in head.events}

    # 1. Detect removed events
    for name, ev in base_events.items():
        if name not in head_events:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.BREAKING,
                    component_type="event",
                    component_id=name,
                    message=f"Event `{name}` was removed.",
                )
            )
            report.has_breaking_changes = True

    # 2. Compare schema fields for existing events
    for name, base_ev in base_events.items():
        if name not in head_events:
            continue
        head_ev = head_events[name]

        base_fields = {f.name: f for f in base_ev.fields}
        head_fields = {f.name: f for f in head_ev.fields}

        # Removed fields
        for fname, bfield in base_fields.items():
            if fname not in head_fields:
                report.items.append(
                    ChangeItem(
                        level=ChangeLevel.BREAKING,
                        component_type="event",
                        component_id=f"{name}.{fname}",
                        message=f"Field `{fname}` was removed from event `{name}`.",
                    )
                )
                report.has_breaking_changes = True
            else:
                hfield = head_fields[fname]
                # Type changes
                if bfield.type_repr != hfield.type_repr:
                    report.items.append(
                        ChangeItem(
                            level=ChangeLevel.BREAKING,
                            component_type="event",
                            component_id=f"{name}.{fname}",
                            message=f"Type of field `{fname}` in `{name}` changed from `{bfield.type_repr}` to `{hfield.type_repr}`.",
                        )
                    )
                    report.has_breaking_changes = True

        # Added fields
        for fname, hfield in head_fields.items():
            if fname not in base_fields:
                if hfield.required:
                    report.items.append(
                        ChangeItem(
                            level=ChangeLevel.BREAKING,
                            component_type="event",
                            component_id=f"{name}.{fname}",
                            message=f"Required field `{fname}` was added to `{name}` without default value.",
                        )
                    )
                    report.has_breaking_changes = True
                else:
                    report.items.append(
                        ChangeItem(
                            level=ChangeLevel.COMPATIBLE,
                            component_type="event",
                            component_id=f"{name}.{fname}",
                            message=f"Optional field `{fname}` was added to `{name}`.",
                        )
                    )

    # 3. Detect handlers missing consumer registration
    base_handlers = {h.id: h for h in base.handlers}
    head_handlers = {h.id: h for h in head.handlers}

    for hid, bh in base_handlers.items():
        if hid not in head_handlers:
            report.items.append(
                ChangeItem(
                    level=ChangeLevel.WARNING,
                    component_type="handler",
                    component_id=hid,
                    message=f"Event handler `{hid}` was removed.",
                )
            )

    return report
