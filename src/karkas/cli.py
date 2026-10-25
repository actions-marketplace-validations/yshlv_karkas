"""Command Line Interface (CLI) for Karkas."""

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

from karkas.config.detector import load_or_detect_config
from karkas.core.diff import diff_graphs
from karkas.core.ir import ArchitectureGraph
from karkas.core.linker import ArchitectureLinker
from karkas.extractors.ast_visitor import scan_directory_ast
from karkas.extractors.runtime_runner import run_headless_introspection
from karkas.renderers.agent_context import (
    render_agent_context_markdown,
    render_ir_json,
)
from karkas.renderers.obsidian.renderer import ObsidianVaultRenderer

app = typer.Typer(
    name="karkas",
    help="Live Architecture Skeleton & Contract Validator for Python Backends",
    add_completion=False,
)
console = Console(legacy_windows=False)


def _build_graph_for_project(project_root: str | Path) -> ArchitectureGraph:
    """Internal helper to scan and link an ArchitectureGraph for a project."""
    config = load_or_detect_config(project_root)
    root = Path(config.project_root).resolve()

    with console.status(f"[bold cyan]Scanning AST skeleton in {root}...[/bold cyan]"):
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
    """Scan a Python backend project, build the architectural skeleton, and generate documentation.

    Outputs produced:
    1. Obsidian Vault: Structured markdown notes with [[wikilinks]], metadata tags, and Mermaid diagrams.
    2. AI Agent Context: Token-optimized architecture_context.md for LLM pair programmers.
    3. Architecture IR: Machine-readable architecture_graph.json for CI/CD diffing.

    Examples:
      karkas generate .
      karkas generate ./my-backend --obsidian ./docs/architecture
      karkas generate . -o ./docs/vault -a ./docs/agent_context.md --ir ./docs/arch_graph.json
    """
    root = Path(path).resolve()
    if not root.exists():
        console.print(f"[bold red]Error:[/bold red] Path `{root}` does not exist.")
        raise typer.Exit(code=1)

    config = load_or_detect_config(root)

    out_obsidian = Path(obsidian_dir) if obsidian_dir else (root / config.output_obsidian_dir)
    out_agent = Path(agent_file) if agent_file else (root / config.output_agent_context_file)
    out_ir = Path(ir_file) if ir_file else (root / config.output_ir_json_file)

    console.print(Panel(f"[bold green]Karkas Generator[/bold green]\nTarget: [cyan]{root}[/cyan]"))

    graph = _build_graph_for_project(root)

    with console.status("[bold green]Rendering Obsidian notes & Mermaid diagrams...[/bold green]"):
        obsidian_renderer = ObsidianVaultRenderer(out_obsidian)
        obsidian_renderer.render(graph)

    with console.status("[bold green]Generating AI agent context and JSON snapshot...[/bold green]"):
        render_agent_context_markdown(graph, out_agent)
        render_ir_json(graph, out_ir)

    table = Table(title="Karkas Architecture Discovery Summary", header_style="bold magenta")
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
    console.print("\n✨ [bold green]Successfully generated live architecture skeleton:[/bold green]")
    console.print(f"  📁 Obsidian Vault: [cyan]{out_obsidian}[/cyan]")
    console.print(f"  📄 AI Context:    [cyan]{out_agent}[/cyan]")
    console.print(f"  📦 JSON Graph:     [cyan]{out_ir}[/cyan]\n")


@app.command()
def diff(
    base: Annotated[str, typer.Argument(help="Path to base architecture_graph.json (e.g. from main branch)")],
    head: Annotated[str, typer.Argument(help="Path to head architecture_graph.json or current project dir")],
    fail_on_breaking: Annotated[bool, typer.Option("--fail-on-breaking", help="Exit with code 1 if breaking changes exist")] = True,
) -> None:
    """Compare two architecture snapshots and detect breaking contract changes in CI/CD.

    Validates Pydantic v2 schemas for domain events, detects removed fields, type mutations,
    and missing consumer event handlers.

    Examples:
      karkas diff base_graph.json head_graph.json
      karkas diff main_graph.json . --fail-on-breaking
    """
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
    console.print(Panel(report.to_markdown(), title="Karkas Contract Diff Report"))

    if report.has_breaking_changes and fail_on_breaking:
        console.print("[bold red]CI Failure:[/bold red] Breaking changes detected in domain event contracts!")
        raise typer.Exit(code=1)


@app.command()
def check(
    path: Annotated[str, typer.Argument(help="Path to project root directory")] = ".",
) -> None:
    """Fast sanity check verifying that architecture contracts, events, and handlers are valid.

    Examples:
      karkas check .
      karkas check /path/to/project
    """
    root = Path(path).resolve()
    graph = _build_graph_for_project(root)
    console.print(f"[bold green]Check passed:[/bold green] Discovered {len(graph.events)} valid domain events and {len(graph.handlers)} handlers.")


if __name__ == "__main__":
    app()
