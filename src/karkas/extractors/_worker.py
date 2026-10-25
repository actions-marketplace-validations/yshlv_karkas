"""Worker script executed in the target project's virtualenv.

Performs safe headless runtime introspection:
1. Imports domain event modules and builds Pydantic v2 JSON schemas.
2. Imports event registry and reads registered handlers & batch configs.
3. Introspects SQLAlchemy Base.metadata.tables.
Outputs JSON to stdout.
"""

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def safe_introspect(project_root: str, config_json_str: str) -> dict[str, Any]:
    config = json.loads(config_json_str)
    root = Path(project_root).resolve()

    # Add src and root to sys.path
    for p in ("src", "."):
        path_dir = str(root / p)
        if path_dir not in sys.path and (root / p).exists():
            sys.path.insert(0, path_dir)

    # Set mock environment to prevent real network connections
    os.environ.setdefault("ENV", "testing")
    os.environ.setdefault("ENVIRONMENT", "testing")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://mock:mock@localhost:5432/mock")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

    result: dict[str, Any] = {
        "events": [],
        "registry_handlers": [],
        "tables": [],
        "errors": [],
    }

    # 1. Discover and import event classes
    event_classes: dict[str, type] = {}

    # Try importing BaseEvent first
    base_event_cls = None
    try:
        from core.domain.events.base import BaseEvent
        base_event_cls = BaseEvent
    except Exception:
        pass

    # Discover and import all event modules
    for rel_path in config.get("events_paths", []):
        full_path = root / rel_path
        if not full_path.exists():
            continue

        # Import modules in directory
        for py_file in full_path.rglob("*.py"):
            if py_file.name.startswith("__") and py_file.name != "__init__.py":
                continue
            # Calculate module name relative to src or root
            rel_to_src = None
            for base in (root / "src", root):
                try:
                    rel_to_src = py_file.relative_to(base).with_suffix("")
                    break
                except ValueError:
                    continue
            if rel_to_src:
                mod_name = ".".join(rel_to_src.parts)
                try:
                    importlib.import_module(mod_name)
                except Exception as e:
                    result["errors"].append(f"Failed to import event module {mod_name}: {e}")

    # Collect BaseEvent subclasses
    if base_event_cls and hasattr(base_event_cls, "_subclasses_by_name"):
        event_classes.update(base_event_cls._subclasses_by_name)
    elif base_event_cls:
        for sub in base_event_cls.__subclasses__():
            event_classes[sub.__name__] = sub

    # Generate Pydantic schemas for events
    from pydantic import TypeAdapter

    def parse_rest_docstring(raw_doc: str | None) -> tuple[str, dict[str, str]]:
        if not raw_doc:
            return "", {}
        main_lines = []
        field_docs = {}
        current_field = None

        for line in raw_doc.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith((":ivar ", ":param ")):
                parts = stripped.split(":", 2)
                if len(parts) >= 3:
                    tag_and_name = parts[1].strip()
                    f_desc = parts[2].strip()
                    f_name = tag_and_name.split()[-1]
                    field_docs[f_name] = f_desc
                    current_field = f_name
                continue
            elif stripped.startswith(":") and ":" in stripped[1:]:
                current_field = None
                continue
            elif current_field and line.startswith(("    ", "\t", "  ")):
                field_docs[current_field] += " " + stripped
                continue

            if not field_docs:
                main_lines.append(stripped)

        summary = " ".join(main_lines).strip()
        return summary, field_docs

    def clean_first_sentence(text: str) -> str:
        if not text:
            return ""
        # Take first sentence or first line
        import re
        match = re.search(r"^(.*?[.!?])(?:\s+|$)", text.strip())
        res = match.group(1).strip() if match else text.strip().splitlines()[0]
        return res.replace("[[", "").replace("]]", "").replace('"', "'")

    for name, cls in event_classes.items():
        doc = getattr(cls, "__doc__", None)
        full_summary, field_descriptions = parse_rest_docstring(doc)
        short_summary = clean_first_sentence(full_summary)

        try:
            adapter = TypeAdapter(cls)
            json_schema = adapter.json_schema()
        except Exception:
            json_schema = {}

        fields = []
        # Extract fields from dataclass or pydantic annotations
        annotations = getattr(cls, "__annotations__", {})
        for f_name, f_type in annotations.items():
            if f_name.startswith("_"):
                continue
            type_str = str(f_type)
            if hasattr(f_type, "__name__"):
                type_str = f_type.__name__
            fields.append({
                "name": f_name,
                "type_repr": type_str,
                "required": True,
                "description": field_descriptions.get(f_name),
            })

        result["events"].append({
            "id": f"{cls.__module__}.{cls.__name__}",
            "name": cls.__name__,
            "summary": short_summary,
            "docstring": full_summary or doc,
            "fields": fields,
            "json_schema": json_schema,
            "domain": cls.__module__.split(".")[-1] if "." in cls.__module__ else None,
        })

    # 2. Discover and inspect EventRegistry
    try:
        from application.bootstrap import load_event_handlers
        from application.events.registry import event_registry

        load_event_handlers()

        # Regular handlers
        for ev_cls, handlers in event_registry._handlers.items():
            ev_name = ev_cls.__name__ if hasattr(ev_cls, "__name__") else str(ev_cls)
            for h in handlers:
                h_name = getattr(h, "__name__", str(h))
                # Skip internal batch wrapper in regular handlers
                if h_name == "_batch_collector_wrapper":
                    continue
                h_mod = getattr(h, "__module__", "")
                h_doc = getattr(h, "__doc__", None)
                result["registry_handlers"].append({
                    "event_name": ev_name,
                    "handler_id": f"{h_mod}.{h_name}",
                    "handler_name": h_name,
                    "summary": clean_first_sentence(h_doc or ""),
                    "docstring": h_doc,
                    "is_batch": False,
                    "batch_config": None,
                })

        # Batch handlers
        for handler_id, cfg in event_registry._batch_handlers.items():
            ev_name = cfg.event_type.__name__ if hasattr(cfg.event_type, "__name__") else str(cfg.event_type)
            h = cfg.handler
            h_name = getattr(h, "__name__", str(h))
            h_mod = getattr(h, "__module__", "")
            h_doc = getattr(h, "__doc__", None)
            result["registry_handlers"].append({
                "event_name": ev_name,
                "handler_id": f"{h_mod}.{h_name}",
                "handler_name": h_name,
                "summary": clean_first_sentence(h_doc or ""),
                "docstring": h_doc,
                "is_batch": True,
                "batch_config": {
                    "window_seconds": cfg.window_seconds,
                    "max_batch_size": cfg.max_batch_size,
                    "group_by": cfg.group_by.__name__ if cfg.group_by and hasattr(cfg.group_by, "__name__") else None,
                },
            })
    except Exception as e:
        result["errors"].append(f"EventRegistry introspection note: {e}")

    # 3. Discover SQLAlchemy Tables
    try:
        # Try finding declarative base in infrastructure.adapters.db
        from infrastructure.adapters.db.sqlalchemy.models.base import Base
        if hasattr(Base, "metadata"):
            for table_name, table in Base.metadata.tables.items():
                cols = []
                for col in table.columns:
                    cols.append({
                        "name": col.name,
                        "type": str(col.type),
                        "primary_key": col.primary_key,
                        "nullable": col.nullable,
                    })
                result["tables"].append({
                    "id": f"db.table.{table_name}",
                    "name": table_name,
                    "engine": "postgresql",
                    "table_or_key": table_name,
                    "columns_or_fields": cols,
                })
    except Exception as e:
        result["errors"].append(f"SQLAlchemy introspection note: {e}")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Missing project_root or config argument"}))
        sys.exit(1)

    project_root_arg = sys.argv[1]
    config_arg = sys.argv[2]
    data = safe_introspect(project_root_arg, config_arg)
    print("---KARKAS_JSON_START---")
    print(json.dumps(data, default=str))
    print("---KARKAS_JSON_END---")
