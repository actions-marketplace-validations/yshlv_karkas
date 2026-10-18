"""Configuration schemas for ArchDoc."""

from pydantic import BaseModel, Field


class ArchDocConfig(BaseModel):
    """ArchDoc project configuration."""

    project_name: str = "project"
    project_root: str = "."

    # Source code search paths
    source_paths: list[str] = Field(default_factory=lambda: ["src"])
    routes_paths: list[str] = Field(
        default_factory=lambda: ["src/application/api", "src/api", "src/presentation/api", "src/routes"]
    )
    events_paths: list[str] = Field(
        default_factory=lambda: ["src/core/domain/events", "src/domain/events"]
    )
    handlers_paths: list[str] = Field(
        default_factory=lambda: ["src/application/events/handlers", "src/application/handlers"]
    )
    tasks_paths: list[str] = Field(
        default_factory=lambda: ["src/application/background/tasks", "src/background/tasks"]
    )
    services_paths: list[str] = Field(
        default_factory=lambda: ["src/core/services", "src/core/use_cases", "src/services"]
    )
    repositories_paths: list[str] = Field(
        default_factory=lambda: ["src/infrastructure/adapters/db", "src/infrastructure/db", "src/core/ports/db"]
    )
    models_paths: list[str] = Field(
        default_factory=lambda: ["src/infrastructure/adapters/db", "src/infrastructure/db", "src/models"]
    )

    # Architectural conventions
    event_base_classes: list[str] = Field(
        default_factory=lambda: ["BaseEvent", "DomainEvent", "Event"]
    )
    handler_decorators: list[str] = Field(
        default_factory=lambda: ["event_handler", "batch_event_handler"]
    )
    publish_methods: list[str] = Field(
        default_factory=lambda: ["publish", "publish_many"]
    )
    taskiq_task_decorators: list[str] = Field(
        default_factory=lambda: ["task", "broker.task"]
    )
    http_route_decorators: list[str] = Field(
        default_factory=lambda: ["get", "post", "put", "delete", "patch", "options", "head", "api_route"]
    )
    db_declarative_bases: list[str] = Field(
        default_factory=lambda: ["Base", "DeclarativeBase"]
    )

    # Output paths
    output_obsidian_dir: str = "docs/architecture"
    output_agent_context_file: str = "docs/architecture_context.md"
    output_ir_json_file: str = "docs/architecture_graph.json"
