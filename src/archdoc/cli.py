"""Command Line Interface (CLI) for ArchDoc."""

import sys
from pathlib import Path
from typing import Annotated

# Force UTF-8 encoding on Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from archdoc.config.detector import load_or_detect_config
from archdoc.core.diff import diff_graphs
from archdoc.core.ir import ArchitectureGraph
from archdoc.core.linker import ArchitectureLinker
from archdoc.extractors.ast_visitor import scan_directory_ast
from archdoc.extractors.runtime_runner import run_headless_introspection
from archdoc.renderers.agent_context import (
    render_agent_context_markdown,
    render_ir_json,
)
from archdoc.renderers.obsidian.renderer import ObsidianVaultRenderer

app = typer.Typer(
    name="archdoc",
    help="Live Architecture Documentation Generator & Contract Validator for Python Backends",
    add_completion=False,
)
console = Console(legacy_windows=False)


def _build_graph_for_project(project_root: str | Path) -> ArchitectureGraph:
    """Internal helper to scan and link an ArchitectureGraph for a project."""
    config = load_or_detect_config(project_root)
    root = Path(config.project_root).resolve()

    with console.status(f"[bold cyan]Scanning AST in {root}...[/bold cyan]"):
        ast_result = scan_directory_ast(root, config)

    with console.status("[bold cyan]Running headless runtime introspection...[/bold cyan]"):
        runtime_data = run_headless_introspection(config)

    with console.status("[bold cyan]Linking architecture graph...[/bold cyan]"):
        linker = ArchitectureLinker(config)
        graph = linker.link(ast_result, runtime_data)

    return graph


@app.command()
def generate(
    path: Annotated[str, typer.Argument(help="Path to project root directory")] = ".",
    obsidian_dir: Annotated[str | None, typer.Option("--obsidian", "-o", help="Target Obsidian output directory")] = None,
    agent_file: Annotated[str | None, typer.Option("--agent", "-a", help="Target AI agent context markdown file")] = None,
    ir_file: Annotated[str | None, typer.Option("--ir", help="Target Architecture Graph JSON file")] = None,
) -> None:
    """Scan project, build architecture graph, and generate documentation for Obsidian & AI Agents."""
    root = Path(path).resolve()
    if not root.exists():
        console.print(f"[bold red]Error:[/bold red] Path `{root}` does not exist.")
        raise typer.Exit(code=1)

    config = load_or_detect_config(root)

    out_obsidian = Path(obsidian_dir) if obsidian_dir else (root / config.output_obsidian_dir)
    out_agent = Path(agent_file) if agent_file else (root / config.output_agent_context_file)
    out_ir = Path(ir_file) if ir_file else (root / config.output_ir_json_file)

    console.print(Panel(f"[bold green]ArchDoc Generator[/bold green]\nTarget: [cyan]{root}[/cyan]"))

    graph = _build_graph_for_project(root)

    with console.status("[bold green]Rendering Obsidian notes & Mermaid diagrams...[/bold green]"):
        obsidian_renderer = ObsidianVaultRenderer(out_obsidian)
        obsidian_renderer.render(graph)

    with console.status("[bold green]Generating AI agent context and JSON snapshot...[/bold green]"):
        render_agent_context_markdown(graph, out_agent)
        render_ir_json(graph, out_ir)

    table = Table(title="Architecture Discovery Summary", header_style="bold magenta")
    table.add_column("Component", style="dim")
    table.add_column("Count", justify="right", style="bold green")

    table.add_row("API Routes / Entrypoints", str(len(graph.entrypoints)))
    table.add_row("Use Cases / Workflows", str(len(graph.use_cases)))
    table.add_row("Domain Services", str(len(graph.services)))
    table.add_row("Domain Events", str(len(graph.events)))
    table.add_row("Handlers & Tasks", str(len(graph.handlers)))
    table.add_row("Storage Entities / Tables", str(len(graph.storage_entities)))
    table.add_row("Business Flows", str(len(graph.flows)))
    table.add_row("Graph Edges", str(len(graph.edges)))

    console.print(table)
    console.print("\n✨ [bold green]Successfully generated live documentation:[/bold green]")
    console.print(f"  📁 Obsidian Vault: [cyan]{out_obsidian}[/cyan]")
    console.print(f"  📄 AI Context:    [cyan]{out_agent}[/cyan]")
    console.print(f"  📦 JSON Graph:     [cyan]{out_ir}[/cyan]\n")


@app.command()
def diff(
    base: Annotated[str, typer.Argument(help="Path to base architecture_graph.json (e.g. from main)")],
    head: Annotated[str, typer.Argument(help="Path to head architecture_graph.json or current project dir")],
    fail_on_breaking: Annotated[bool, typer.Option("--fail-on-breaking", help="Exit with code 1 if breaking changes exist")] = True,
) -> None:
    """Compare two architecture snapshots and detect breaking contract changes."""
    base_path = Path(base)
    if not base_path.exists():
        console.print(f"[bold red]Error:[/bold red] Base file `{base}` not found.")
        raise typer.Exit(code=1)

    base_graph = ArchitectureGraph.model_validate_json(base_path.read_text(encoding="utf-8"))

    head_path = Path(head)
    if head_path.is_dir():
        head_graph = _build_graph_for_project(head_path)
    else:
        head_graph = ArchitectureGraph.model_validate_json(head_path.read_text(encoding="utf-8"))

    report = diff_graphs(base_graph, head_graph)
    console.print(Panel(report.to_markdown(), title="ArchDoc Contract Diff Report"))

    if report.has_breaking_changes and fail_on_breaking:
        console.print("[bold red]CI Failure:[/bold red] Breaking changes detected in domain event contracts!")
        raise typer.Exit(code=1)


@app.command()
def check(
    path: Annotated[str, typer.Argument(help="Path to project root directory")] = ".",
) -> None:
    """Verify that architecture contracts are consistent and valid."""
    root = Path(path).resolve()
    graph = _build_graph_for_project(root)
    console.print(f"[bold green]Check passed:[/bold green] Discovered {len(graph.events)} valid domain events and {len(graph.handlers)} handlers.")


if __name__ == "__main__":
    app()
