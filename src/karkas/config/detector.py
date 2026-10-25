"""Automatic heuristic detector and config loader for Karkas."""

from pathlib import Path

import yaml

from karkas.config.schema import KarkasConfig


def load_or_detect_config(project_root: str | Path) -> KarkasConfig:
    """Load karkas.yaml if exists, or heuristically infer project settings."""
    root = Path(project_root).resolve()
    config_file = root / "karkas.yaml"

    if config_file.exists():
        try:
            with open(config_file, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}
                raw_data.setdefault("project_root", str(root))
                return KarkasConfig.model_validate(raw_data)
        except Exception:
            pass

    # Heuristic discovery
    def format_project_title(name: str) -> str:
        if "inventx" in name.lower():
            return name.lower().replace("inventx", "InventX").replace("-", " ").replace("_", " ").title()
        return " ".join(p.capitalize() for p in name.replace("-", " ").replace("_", " ").split())

    project_name = format_project_title(root.name)
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        try:
            content = pyproject_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.strip().startswith("name ="):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        val = parts[1].strip().strip('"').strip("'")
                        if val and "template" not in val.lower():
                            project_name = format_project_title(val)
                            break
        except Exception:
            pass

    # Find candidate paths
    config = KarkasConfig(project_name=project_name, project_root=str(root))

    # Validate and filter source paths that actually exist
    existing_routes = [p for p in config.routes_paths if (root / p).exists()]
    if existing_routes:
        config.routes_paths = existing_routes

    existing_events = [p for p in config.events_paths if (root / p).exists()]
    if existing_events:
        config.events_paths = existing_events

    existing_handlers = [p for p in config.handlers_paths if (root / p).exists()]
    if existing_handlers:
        config.handlers_paths = existing_handlers

    existing_tasks = [p for p in config.tasks_paths if (root / p).exists()]
    if existing_tasks:
        config.tasks_paths = existing_tasks

    existing_services = [p for p in config.services_paths if (root / p).exists()]
    if existing_services:
        config.services_paths = existing_services

    existing_repos = [p for p in config.repositories_paths if (root / p).exists()]
    if existing_repos:
        config.repositories_paths = existing_repos

    existing_models = [p for p in config.models_paths if (root / p).exists()]
    if existing_models:
        config.models_paths = existing_models

    return config
