"""Static AST Extractor for ArchDoc.

Visits Python ASTs to extract:
1. Entrypoints: HTTP API routes (@router.post, etc.), CLI commands, Taskiq background tasks (@broker.task).
2. Use Cases: Application orchestrators calling domain services and repositories.
3. Domain Services: Service classes, their methods, repository interactions, and event publications.
4. Event Publishers: `event_bus.publish(...)` and `publish_many(...)` call sites.
5. Handler Decorators: `@event_handler(...)` and `@batch_event_handler(...)` bindings.
6. Persistence Operations: `self.db_uow[Repository]` or `db_uow[Repository]` usage.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archdoc.config.schema import ArchDocConfig
from archdoc.core.docstring import clean_summary
from archdoc.core.ir import SourceLocation


@dataclass
class AstEntrypointDef:
    """Recorded application entrypoint (HTTP route, CLI, background task)."""

    func_name: str
    http_method: str | None
    path: str | None
    domain: str
    summary: str
    docstring: str | None
    called_use_cases: list[str] = field(default_factory=list)
    called_services: list[str] = field(default_factory=list)
    location: SourceLocation | None = None


@dataclass
class AstUseCaseDef:
    """Recorded application use case definition."""

    name: str
    domain: str
    summary: str
    docstring: str | None
    orchestrated_services: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    published_events: list[str] = field(default_factory=list)
    location: SourceLocation | None = None


@dataclass
class AstServiceDef:
    """Recorded domain service class definition."""

    name: str
    domain: str
    summary: str
    docstring: str | None
    methods: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    published_events: list[str] = field(default_factory=list)
    location: SourceLocation | None = None


@dataclass
class AstPublishCall:
    """Recorded event publish call site."""

    event_class_names: list[str]
    caller_class: str | None
    caller_method: str
    location: SourceLocation
    docstring: str | None = None


@dataclass
class AstHandlerDef:
    """Recorded event handler definition."""

    handler_name: str
    handled_event_names: list[str]
    is_batch: bool
    batch_kwargs: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None
    docstring: str | None = None
    summary: str = ""
    invoked_targets: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)


@dataclass
class AstTaskiqTaskDef:
    """Recorded Taskiq task definition."""

    task_name: str
    location: SourceLocation
    docstring: str | None = None
    summary: str = ""
    invoked_targets: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)


@dataclass
class AstScanResult:
    """Aggregated results from scanning a codebase with AST visitor."""

    entrypoints: list[AstEntrypointDef] = field(default_factory=list)
    use_cases: list[AstUseCaseDef] = field(default_factory=list)
    services: list[AstServiceDef] = field(default_factory=list)
    publish_calls: list[AstPublishCall] = field(default_factory=list)
    handlers: list[AstHandlerDef] = field(default_factory=list)
    tasks: list[AstTaskiqTaskDef] = field(default_factory=list)


class CodebaseAstVisitor(ast.NodeVisitor):
    """AST visitor traversing a single Python source file."""

    def __init__(self, file_path: str, config: ArchDocConfig) -> None:
        self.file_path = file_path
        self.config = config
        self.norm_path = file_path.replace("\\", "/")
        self.domain = self._infer_domain(file_path)

        self.current_class: str | None = None
        self.current_class_doc: str | None = None
        self.current_func: str | None = None
        self.current_func_doc: str | None = None

        self.local_var_types: dict[str, str] = {}
        self.current_func_invocations: list[str] = []
        self.current_func_repos: list[str] = []
        self.current_func_publishes: list[str] = []

        self.entrypoints: list[AstEntrypointDef] = []
        self.use_cases: list[AstUseCaseDef] = []
        self.services: list[AstServiceDef] = []
        self.publish_calls: list[AstPublishCall] = []
        self.handlers: list[AstHandlerDef] = []
        self.tasks: list[AstTaskiqTaskDef] = []

        self._current_service_repos: list[str] = []
        self._current_service_publishes: list[str] = []
        self._current_service_methods: list[str] = []

    def _infer_domain(self, file_path: str) -> str:
        """Infer domain name from file path."""
        p = Path(file_path)
        stem = p.stem.lower()
        if stem not in ("__init__", "base", "service", "handler", "router", "routes", "views"):
            return stem
        # Look at parent folder name
        parent = p.parent.name.lower()
        if parent not in ("routes", "handlers", "services", "use_cases", "v1", "api"):
            return parent
        return "general"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self.current_class
        old_doc = self.current_class_doc
        old_s_repos = list(self._current_service_repos)
        old_s_pubs = list(self._current_service_publishes)
        old_s_methods = list(self._current_service_methods)

        self.current_class = node.name
        self.current_class_doc = ast.get_docstring(node)
        self._current_service_repos = []
        self._current_service_publishes = []
        self._current_service_methods = []

        is_service_class = "service" in node.name.lower() and not node.name.startswith("Test")

        self.generic_visit(node)

        if is_service_class:
            loc = SourceLocation(
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno,
                symbol_name=node.name,
            )
            raw_doc = self.current_class_doc
            self.services.append(
                AstServiceDef(
                    name=node.name,
                    domain=self.domain,
                    summary=clean_summary(raw_doc),
                    docstring=raw_doc,
                    methods=list(dict.fromkeys(self._current_service_methods)),
                    repositories=list(dict.fromkeys(self._current_service_repos)),
                    published_events=list(dict.fromkeys(self._current_service_publishes)),
                    location=loc,
                )
            )

        self.current_class = old_class
        self.current_class_doc = old_doc
        self._current_service_repos = old_s_repos
        self._current_service_publishes = old_s_pubs
        self._current_service_methods = old_s_methods

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        old_func = self.current_func
        old_doc = self.current_func_doc
        old_vars = self.local_var_types.copy()
        old_invocations = list(self.current_func_invocations)
        old_repos = list(self.current_func_repos)
        old_publishes = list(self.current_func_publishes)

        self.current_func = node.name
        self.current_func_doc = ast.get_docstring(node)
        self.local_var_types.clear()
        self.current_func_invocations = []
        self.current_func_repos = []
        self.current_func_publishes = []

        if self.current_class and not node.name.startswith("_"):
            self._current_service_methods.append(node.name)

        # Inspect decorators (HTTP route, handler, broker task)
        route_meta, handler_meta, task_meta = self._inspect_decorators(node)

        # Visit function body to discover assignments, invocations, repos, publishes
        self.generic_visit(node)

        # Track service-level metrics if inside a class
        if self.current_class:
            self._current_service_repos.extend(self.current_func_repos)
            self._current_service_publishes.extend(self.current_func_publishes)

        loc = SourceLocation(
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno,
            symbol_name=f"{self.current_class}.{node.name}" if self.current_class else node.name,
        )

        # 1. Handle HTTP Route Entrypoint
        if route_meta:
            http_method, route_path = route_meta
            called_ucs = [
                inv.split(".")[-1]
                for inv in self.current_func_invocations
                if "use_case" in inv.lower() or inv.endswith("_use_case")
            ]
            called_svcs = [
                inv
                for inv in self.current_func_invocations
                if "service" in inv.lower()
            ]
            self.entrypoints.append(
                AstEntrypointDef(
                    func_name=node.name,
                    http_method=http_method,
                    path=route_path,
                    domain=self.domain,
                    summary=clean_summary(self.current_func_doc),
                    docstring=self.current_func_doc,
                    called_use_cases=list(dict.fromkeys(called_ucs)),
                    called_services=list(dict.fromkeys(called_svcs)),
                    location=loc,
                )
            )

        # 2. Handle Event Handler
        if handler_meta:
            h_name, handled_events, is_batch, batch_kw = handler_meta
            self.handlers.append(
                AstHandlerDef(
                    handler_name=h_name,
                    handled_event_names=handled_events,
                    is_batch=is_batch,
                    batch_kwargs=batch_kw,
                    location=loc,
                    docstring=self.current_func_doc,
                    summary=clean_summary(self.current_func_doc),
                    invoked_targets=list(dict.fromkeys(self.current_func_invocations)),
                    repositories=list(dict.fromkeys(self.current_func_repos)),
                )
            )

        # 3. Handle Taskiq Task
        if task_meta:
            t_name = task_meta
            self.tasks.append(
                AstTaskiqTaskDef(
                    task_name=t_name,
                    location=loc,
                    docstring=self.current_func_doc,
                    summary=clean_summary(self.current_func_doc),
                    invoked_targets=list(dict.fromkeys(self.current_func_invocations)),
                    repositories=list(dict.fromkeys(self.current_func_repos)),
                )
            )

        # 4. Handle Use Case function (files in use_cases/ or functions ending with _use_case)
        is_use_case = (
            ("use_case" in self.norm_path or node.name.endswith("_use_case"))
            and not node.name.startswith("_")
            and not self.current_class
        )
        if is_use_case:
            services_called = list(dict.fromkeys([
                inv for inv in self.current_func_invocations if "service" in inv.lower()
            ]))
            repos_called = list(dict.fromkeys(self.current_func_repos))
            self.use_cases.append(
                AstUseCaseDef(
                    name=node.name,
                    domain=self.domain,
                    summary=clean_summary(self.current_func_doc),
                    docstring=self.current_func_doc,
                    orchestrated_services=services_called,
                    repositories=repos_called,
                    published_events=list(dict.fromkeys(self.current_func_publishes)),
                    location=loc,
                )
            )

        self.current_func = old_func
        self.current_func_doc = old_doc
        self.local_var_types = old_vars
        self.current_func_invocations = old_invocations
        self.current_func_repos = old_repos
        self.current_func_publishes = old_publishes

    def visit_Assign(self, node: ast.Assign) -> None:
        # Track local assignments: event = BookingCreatedEvent(...)
        if isinstance(node.value, ast.Call):
            func_name = self._resolve_call_func_name(node.value.func)
            if func_name:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.local_var_types[target.id] = func_name
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Detect: self.db_uow[BookingRepository] or db_uow[BookingRepository] or redis_uow[RedisBatchRepository]
        val_name = self._resolve_call_func_name(node.value)
        if val_name and any(u in val_name.lower() for u in ("uow", "unit_of_work")):
            slice_name = self._resolve_call_func_name(node.slice)
            if slice_name:
                clean_repo = slice_name.split(".")[-1]
                if clean_repo not in self.current_func_repos:
                    self.current_func_repos.append(clean_repo)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_name = self._resolve_call_func_name(node.func)

        # 1. Check if call is on Subscript: self.db_uow[BookingRepository].create_booking(...)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Subscript):
            sub = node.func.value
            sub_val = self._resolve_call_func_name(sub.value)
            if sub_val and any(u in sub_val.lower() for u in ("uow", "unit_of_work")):
                slice_name = self._resolve_call_func_name(sub.slice)
                if slice_name:
                    clean_repo = slice_name.split(".")[-1]
                    if clean_repo not in self.current_func_repos:
                        self.current_func_repos.append(clean_repo)
                    self.current_func_invocations.append(f"{clean_repo}.{node.func.attr}")

        # 2. General invocation tracking
        if func_name:
            self.current_func_invocations.append(func_name)
            if any(k in func_name.lower() for k in ("repo", "repository")):
                clean_r = func_name.split(".")[0]
                if clean_r not in self.current_func_repos:
                    self.current_func_repos.append(clean_r)

        # 3. Check event publishing
        if func_name and any(func_name.endswith(f".{m}") or func_name == m for m in self.config.publish_methods):
            events = self._extract_published_events(node)
            if events and self.current_func:
                self.current_func_publishes.extend(events)
                loc = SourceLocation(
                    file_path=self.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno,
                    symbol_name=f"{self.current_class}.{self.current_func}" if self.current_class else self.current_func,
                )
                self.publish_calls.append(
                    AstPublishCall(
                        event_class_names=events,
                        caller_class=self.current_class,
                        caller_method=self.current_func,
                        location=loc,
                        docstring=self.current_func_doc,
                    )
                )

        self.generic_visit(node)

    def _resolve_call_func_name(self, func_node: ast.AST) -> str | None:
        """Resolve attribute expression like self.event_bus.publish to string."""
        if isinstance(func_node, ast.Name):
            return func_node.id
        elif isinstance(func_node, ast.Attribute):
            val = self._resolve_call_func_name(func_node.value)
            if val:
                return f"{val}.{func_node.attr}"
            return func_node.attr
        elif isinstance(func_node, ast.Constant) and isinstance(func_node.value, str):
            return func_node.value
        return None

    def _extract_published_events(self, call_node: ast.Call) -> list[str]:
        """Extract event class names from publish(event) or publish_many([e1, e2])."""
        events: list[str] = []
        for arg in call_node.args:
            if isinstance(arg, ast.Call):
                name = self._resolve_call_func_name(arg.func)
                if name:
                    events.append(name.split(".")[-1])
            elif isinstance(arg, ast.Name):
                if arg.id in self.local_var_types:
                    events.append(self.local_var_types[arg.id].split(".")[-1])
            elif isinstance(arg, ast.List):
                for elem in arg.elts:
                    if isinstance(elem, ast.Call):
                        name = self._resolve_call_func_name(elem.func)
                        if name:
                            events.append(name.split(".")[-1])
                    elif isinstance(elem, ast.Name) and elem.id in self.local_var_types:
                        events.append(self.local_var_types[elem.id].split(".")[-1])
        return events

    def _inspect_decorators(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> tuple[
        tuple[str, str] | None,  # (http_method, path)
        tuple[str, list[str], bool, dict[str, Any]] | None,  # (h_name, events, is_batch, batch_kw)
        str | None,  # task_name
    ]:
        route_meta = None
        handler_meta = None
        task_meta = None

        for dec in node.decorator_list:
            dec_name = ""
            args: list[ast.AST] = []
            keywords: list[ast.keyword] = []

            if isinstance(dec, ast.Name):
                dec_name = dec.id
            elif isinstance(dec, ast.Attribute):
                dec_name = self._resolve_call_func_name(dec) or ""
            elif isinstance(dec, ast.Call):
                dec_name = self._resolve_call_func_name(dec.func) or ""
                args = dec.args
                keywords = dec.keywords

            dec_parts = dec_name.split(".")
            last_part = dec_parts[-1].lower()

            # 1. Detect HTTP Route: @router.post(""), @router.get("/search"), @app.get(...)
            if any(dec_name.startswith(p) for p in ("router.", "api_router.", "app.")) and last_part in self.config.http_route_decorators:
                http_method = last_part.upper()
                route_path = ""
                if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                    route_path = args[0].value
                elif keywords:
                    for kw in keywords:
                        if kw.arg == "path" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            route_path = kw.value.value
                            break
                route_meta = (http_method, route_path)

            # 2. Detect Event Handlers: @event_handler, @batch_event_handler
            elif any(dec_name.endswith(d) for d in self.config.handler_decorators):
                is_batch = "batch" in dec_name.lower()
                handled_events: list[str] = []
                if args and isinstance(args[0], (ast.Name, ast.Attribute)):
                    event_sym = self._resolve_call_func_name(args[0])
                    if event_sym:
                        handled_events.append(event_sym.split(".")[-1])

                batch_kwargs: dict[str, Any] = {}
                for kw in keywords:
                    if kw.arg and isinstance(kw.value, ast.Constant):
                        batch_kwargs[kw.arg] = kw.value.value

                handler_meta = (node.name, handled_events, is_batch, batch_kwargs)

            # 3. Detect Taskiq task: @broker.task(name=...)
            elif any(dec_name.endswith(t) for t in self.config.taskiq_task_decorators):
                t_name = node.name
                for kw in keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        t_name = kw.value.value
                        break
                task_meta = t_name

        return route_meta, handler_meta, task_meta


def scan_directory_ast(target_dir: str | Path, config: ArchDocConfig) -> AstScanResult:
    """Recursively scan Python files in target_dir and aggregate AST results."""
    result = AstScanResult()
    root = Path(target_dir)

    for py_file in root.rglob("*.py"):
        if any(ignored in py_file.parts for ignored in (".venv", "__pycache__", ".git", ".mypy_cache")):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            visitor = CodebaseAstVisitor(file_path=str(py_file), config=config)
            visitor.visit(tree)

            result.entrypoints.extend(visitor.entrypoints)
            result.use_cases.extend(visitor.use_cases)
            result.services.extend(visitor.services)
            result.publish_calls.extend(visitor.publish_calls)
            result.handlers.extend(visitor.handlers)
            result.tasks.extend(visitor.tasks)
        except Exception:
            continue

    return result
