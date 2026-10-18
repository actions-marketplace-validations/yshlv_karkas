"""Unit tests for ArchDoc breaking changes diff engine."""

from archdoc.core.diff import ChangeLevel, diff_graphs
from archdoc.core.ir import ArchitectureGraph, DomainEventNode, EventField


def test_diff_detects_breaking_and_compatible_changes() -> None:
    base = ArchitectureGraph(project_name="demo", project_root="/demo")
    base.events.append(
        DomainEventNode(
            id="event.OrderPlaced",
            name="OrderPlaced",
            fields=[
                EventField(name="order_id", type_repr="str", required=True),
                EventField(name="amount", type_repr="float", required=True),
            ],
        )
    )

    # 1. Test compatible change: added optional field
    head_compatible = ArchitectureGraph(project_name="demo", project_root="/demo")
    head_compatible.events.append(
        DomainEventNode(
            id="event.OrderPlaced",
            name="OrderPlaced",
            fields=[
                EventField(name="order_id", type_repr="str", required=True),
                EventField(name="amount", type_repr="float", required=True),
                EventField(name="discount_code", type_repr="str", required=False, default_repr="None"),
            ],
        )
    )

    report_comp = diff_graphs(base, head_compatible)
    assert report_comp.has_breaking_changes is False
    assert any(i.level == ChangeLevel.COMPATIBLE for i in report_comp.items)

    # 2. Test breaking change: field removed
    head_breaking = ArchitectureGraph(project_name="demo", project_root="/demo")
    head_breaking.events.append(
        DomainEventNode(
            id="event.OrderPlaced",
            name="OrderPlaced",
            fields=[
                EventField(name="order_id", type_repr="str", required=True),
                # amount removed!
            ],
        )
    )

    report_break = diff_graphs(base, head_breaking)
    assert report_break.has_breaking_changes is True
    assert any(i.level == ChangeLevel.BREAKING and "removed" in i.message for i in report_break.items)

    # 3. Test breaking change: field type changed
    head_type_change = ArchitectureGraph(project_name="demo", project_root="/demo")
    head_type_change.events.append(
        DomainEventNode(
            id="event.OrderPlaced",
            name="OrderPlaced",
            fields=[
                EventField(name="order_id", type_repr="int", required=True),  # str -> int
                EventField(name="amount", type_repr="float", required=True),
            ],
        )
    )

    report_type = diff_graphs(base, head_type_change)
    assert report_type.has_breaking_changes is True
    assert any("type changed" in i.message for i in report_type.items)
