"""Subprocess runner for headless runtime introspection."""

import json
import subprocess
from pathlib import Path
from typing import Any

from archdoc.config.schema import ArchDocConfig


def run_headless_introspection(config: ArchDocConfig) -> dict[str, Any]:
    """Execute the introspection worker inside the target project environment."""
    root = Path(config.project_root).resolve()
    worker_script = Path(__file__).parent / "_worker.py"

    # Locate python executable in target project
    python_candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ]

    target_python = None
    for cand in python_candidates:
        if cand.exists():
            target_python = str(cand)
            break

    cmd = []
    if target_python:
        cmd = [target_python, str(worker_script), str(root), config.model_dump_json()]
    else:
        # Fallback to uv run or current python
        cmd = ["uv", "run", "--project", str(root), "python", str(worker_script), str(root), config.model_dump_json()]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        stdout = proc.stdout
        if "---ARCHDOC_JSON_START---" in stdout and "---ARCHDOC_JSON_END---" in stdout:
            part = stdout.split("---ARCHDOC_JSON_START---")[1].split("---ARCHDOC_JSON_END---")[0]
            return json.loads(part.strip())
        else:
            return {"events": [], "registry_handlers": [], "tables": [], "errors": [proc.stderr or proc.stdout]}
    except Exception as e:
        return {"events": [], "registry_handlers": [], "tables": [], "errors": [str(e)]}
