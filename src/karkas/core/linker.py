"""Linker: combines AST scan results and runtime introspection into ArchitectureGraph."""

from pathlib import Path
from typing import Any

from karkas.config.schema import KarkasConfig
from karkas.core.docstring import clean_summary
from karkas.core.domain import normalize_domain_name
from karkas.core.ir import (
    ArchitectureEdge,
    ArchitectureGraph,
    ChannelNode,
    ChannelType,
    DomainEventNode,
    EdgeType,
    EntrypointNode,
    EntrypointType,
    EventField,
    HandlerNode,
    ProcessFlow,
    ServiceNode,
    StorageEntityNode,
    UseCaseNode,
)
from karkas.extractors.ast_visitor import AstScanResult


class ArchitectureLinker:
    """Combines AST and Runtime data into a validated ArchitectureGraph."""

    def __init__(self, config: KarkasConfig) -> None:
        self.config = config

    def link(self, ast_data: AstScanResult, runtime_data: dict[str, Any]) -> ArchitectureGraph:
        graph = ArchitectureGraph(
            project_name=self.config.project_name,
            project_root=".",
        )

        entrypoint_map: dict[str, EntrypointNode] = {}
        use_case_map: dict[str, UseCaseNode] = {}
        service_map: dict[str, ServiceNode] = {}
        event_map: dict[str, DomainEventNode] = {}
        handler_map: dict[str, HandlerNode] = {}
        channel_map: dict[str, ChannelNode] = {}
        storage_map: dict[str, StorageEntityNode] = {}

        # 1. Base Channels
        bus_channel = ChannelNode(
            id="channel.bus.in_memory",
            name="InMemoryEventBus",
            channel_type=ChannelType.IN_MEMORY_BUS,
        )
        channel_map[bus_channel.id] = bus_channel

        taskiq_channel = ChannelNode(
            id="channel.queue.taskiq",
            name="TaskiqBrokerQueue",
            channel_type=ChannelType.TASKIQ_QUEUE,
        )
        channel_map[taskiq_channel.id] = taskiq_channel

        for tbl in runtime_data.get("tables", []):
            tbl_name = tbl["name"]
            domain_name = normalize_domain_name(tbl_name)
            if domain_name == tbl_name and "_" in tbl_name:
                domain_name = normalize_domain_name(tbl_name.split("_")[0])

            storage_node = StorageEntityNode(
                id=tbl["id"],
                name=tbl_name,
                engine=tbl.get("engine", "postgresql"),
                table_or_key=tbl.get("table_or_key", tbl_name),
                columns_or_fields=tbl.get("columns_or_fields", []),
                domain=domain_name,
            )
            storage_map[storage_node.name] = storage_node

        # Add Redis buffer storage node
        redis_storage = StorageEntityNode(
            id="storage.redis.event_batch_buffer",
            name="redis_batch_buffer",
            engine="redis",
            table_or_key="events:buffer:{handler_id}:{group_key}",
            domain="notification",
            columns_or_fields=[
                {"name": "score", "type": "timestamp (float)", "primary_key": False, "nullable": False},
                {"name": "member", "type": "JSON serialized event payload", "primary_key": True, "nullable": False},
            ],
        )
        storage_map[redis_storage.name] = redis_storage

        # 3. Domain Events (Runtime + AST)
        for ev in runtime_data.get("events", []):
            fields = [EventField(**f) for f in ev.get("fields", [])]
            raw_doc = ev.get("docstring")
            node = DomainEventNode(
                id=ev["id"],
                name=ev["name"],
                summary=ev.get("summary") or clean_summary(raw_doc),
                docstring=raw_doc,
                fields=fields,
                json_schema=ev.get("json_schema", {}),
                domain=ev.get("domain"),
            )
            event_map[node.name] = node

        # 4. Services (AST + publish callers)
        for s_def in ast_data.services:
            s_id = f"service.{s_def.name}"
            s_node = ServiceNode(
                id=s_id,
                name=s_def.name,
                domain=s_def.domain,
                summary=s_def.summary,
                docstring=s_def.docstring,
                methods=s_def.methods,
                repositories=s_def.repositories,
                published_events=s_def.published_events,
                location=s_def.location,
            )
            service_map[s_def.name] = s_node

        # Process publish calls from AST
        for pub in ast_data.publish_calls:
            caller_name = pub.caller_class or (Path(pub.location.file_path).stem if pub.location else "UnknownService")
            s_node = service_map.get(caller_name)
            if not s_node:
                s_node = ServiceNode(
                    id=f"service.{caller_name}",
                    name=caller_name,
                    domain=self._infer_domain_from_name(caller_name),
                    summary=clean_summary(pub.docstring),
                    docstring=pub.docstring,
                    location=pub.location,
                    methods=[pub.caller_method],
                )
                service_map[caller_name] = s_node
            else:
                if pub.caller_method not in s_node.methods:
                    s_node.methods.append(pub.caller_method)

            for ev_name in pub.event_class_names:
                if ev_name not in s_node.published_events:
                    s_node.published_events.append(ev_name)

                ev_node = event_map.get(ev_name)
                if not ev_node:
                    ev_node = DomainEventNode(
                        id=f"event.{ev_name}",
                        name=ev_name,
                        summary="Discovered from event publisher call.",
                        docstring="Discovered from event publisher call.",
                        domain=self._infer_domain_from_name(ev_name),
                    )
                    event_map[ev_name] = ev_node

                # Deduplicated Edge: Service -> Event
                existing = next(
                    (e for e in graph.edges if e.source_id == s_node.id and e.target_id == ev_node.id and e.edge_type == EdgeType.PUBLISHES),
                    None,
                )
                if existing:
                    methods = existing.metadata.setdefault("methods", [])
                    if pub.caller_method not in methods:
                        methods.append(pub.caller_method)
                else:
                    graph.edges.append(
                        ArchitectureEdge(
                            source_id=s_node.id,
                            target_id=ev_node.id,
                            edge_type=EdgeType.PUBLISHES,
                            label="publish",
                            metadata={"methods": [pub.caller_method]},
                        )
                    )

        # 5. Use Cases (AST)
        for auc in ast_data.use_cases:
            uc_id = f"use_case.{auc.domain}.{auc.name}"
            uc_node = UseCaseNode(
                id=uc_id,
                name=auc.name,
                domain=auc.domain,
                summary=auc.summary,
                docstring=auc.docstring,
                orchestrated_services=auc.orchestrated_services,
                repositories=auc.repositories,
                published_events=auc.published_events,
                location=auc.location,
            )
            use_case_map[uc_node.name] = uc_node
            use_case_map[uc_id] = uc_node

            # Link Use Case -> Service
            for s_call in auc.orchestrated_services:
                matched_service = self._match_service(s_call, list(service_map.values()))
                if not matched_service:
                    s_name = s_call.split(".")[-1]
                    if "service" in s_name.lower():
                        matched_service = ServiceNode(
                            id=f"service.{s_name}",
                            name=s_name,
                            domain=auc.domain,
                            summary=f"Domain service for {s_name} operations.",
                        )
                        service_map[s_name] = matched_service

                if matched_service:
                    if matched_service.domain in ("general", "services", ""):
                        matched_service.domain = auc.domain

                    edge = ArchitectureEdge(
                        source_id=uc_node.id,
                        target_id=matched_service.id,
                        edge_type=EdgeType.ORCHESTRATES,
                        label="orchestrates",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

            # Link Use Case -> Storage (via repositories)
            for repo in auc.repositories:
                st = self._resolve_repo_to_table(repo, list(storage_map.values()))
                if st:
                    edge = ArchitectureEdge(
                        source_id=uc_node.id,
                        target_id=st.id,
                        edge_type=EdgeType.WRITES_TO,
                        label="persists via UoW",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

            # Link Use Case -> DomainEvent
            for ev_name in auc.published_events:
                ev_node = event_map.get(ev_name)
                if ev_node:
                    edge = ArchitectureEdge(
                        source_id=uc_node.id,
                        target_id=ev_node.id,
                        edge_type=EdgeType.PUBLISHES,
                        label="publishes",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

        # 6. Service -> Storage persistence links
        for s in service_map.values():
            for repo in s.repositories:
                st = self._resolve_repo_to_table(repo, list(storage_map.values()))
                if st:
                    edge = ArchitectureEdge(
                        source_id=s.id,
                        target_id=st.id,
                        edge_type=EdgeType.WRITES_TO,
                        label="persists via UoW",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

        # 7. Entrypoints (API Routes & Tasks)
        for ep in ast_data.entrypoints:
            # Format route name: "POST /bookings" or "POST /bookings/search"
            domain_plural = f"{ep.domain}s" if not ep.domain.endswith("s") else ep.domain
            if ep.domain in ("auth", "dashboard", "storage", "import", "user"):
                domain_prefix = f"/{ep.domain}"
            else:
                domain_prefix = f"/{domain_plural}"

            clean_path = ep.path.strip("/") if ep.path else ""
            full_path = f"{domain_prefix}/{clean_path}" if clean_path else domain_prefix
            full_path = full_path.rstrip("/") if full_path != "/" else "/"

            ep_name = f"{ep.http_method or 'ANY'} {full_path}"
            ep_id = f"entrypoint.api.{ep.domain}.{ep.func_name}"

            ep_node = EntrypointNode(
                id=ep_id,
                name=ep_name,
                entrypoint_type=EntrypointType.HTTP_ROUTE,
                http_method=ep.http_method,
                path=full_path,
                summary=ep.summary,
                docstring=ep.docstring,
                target_use_case_ids=[],
                target_service_ids=[],
                location=ep.location,
                domain=ep.domain,
            )

            # Match called use cases
            for uc_name in ep.called_use_cases:
                matched_uc = use_case_map.get(uc_name)
                if not matched_uc:
                    # Look up by name
                    for u in use_case_map.values():
                        if u.name == uc_name:
                            matched_uc = u
                            break
                if matched_uc:
                    ep_node.target_use_case_ids.append(matched_uc.id)
                    edge = ArchitectureEdge(
                        source_id=ep_node.id,
                        target_id=matched_uc.id,
                        edge_type=EdgeType.TRIGGERS,
                        label="invokes",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

            # Match called services
            for s_call in ep.called_services:
                matched_s = self._match_service(s_call, list(service_map.values()))
                if matched_s:
                    ep_node.target_service_ids.append(matched_s.id)
                    edge = ArchitectureEdge(
                        source_id=ep_node.id,
                        target_id=matched_s.id,
                        edge_type=EdgeType.TRIGGERS,
                        label="calls",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

            entrypoint_map[ep_id] = ep_node

        # Add Taskiq tasks as entrypoints
        for task in ast_data.tasks:
            t_id = f"entrypoint.task.{task.task_name}"
            t_node = EntrypointNode(
                id=t_id,
                name=f"Taskiq: {task.task_name}",
                entrypoint_type=EntrypointType.BACKGROUND_TASK,
                summary=task.summary or clean_summary(task.docstring),
                docstring=task.docstring,
                location=task.location,
                domain="background",
            )
            entrypoint_map[t_id] = t_node

            # Link Taskiq queue -> Task
            graph.edges.append(
                ArchitectureEdge(
                    source_id=taskiq_channel.id,
                    target_id=t_node.id,
                    edge_type=EdgeType.DELIVERED_TO,
                    label="runs",
                )
            )

            # Link Task -> Storage if repos used
            for repo in task.repositories:
                st = self._resolve_repo_to_table(repo, list(storage_map.values()))
                if st:
                    graph.edges.append(
                        ArchitectureEdge(
                            source_id=t_node.id,
                            target_id=st.id,
                            edge_type=EdgeType.WRITES_TO,
                            label="persists via UoW",
                        )
                    )

        # 8. Handlers (Runtime Registry + AST)
        for rh in runtime_data.get("registry_handlers", []):
            h_name = rh["handler_name"]
            is_batch = rh.get("is_batch", False)
            batch_cfg = rh.get("batch_config")
            raw_doc = rh.get("docstring")

            h_node = HandlerNode(
                id=rh["handler_id"],
                name=h_name,
                summary=rh.get("summary") or clean_summary(raw_doc),
                docstring=raw_doc,
                is_batch=is_batch,
                batch_config=batch_cfg,
                domain=self._infer_domain_from_name(h_name),
            )
            handler_map[h_name] = h_node

        for ah in ast_data.handlers:
            h_node = handler_map.get(ah.handler_name)
            if not h_node:
                h_node = HandlerNode(
                    id=f"handler.{ah.handler_name}",
                    name=ah.handler_name,
                    summary=ah.summary or clean_summary(ah.docstring),
                    docstring=ah.docstring,
                    is_batch=ah.is_batch,
                    batch_config=ah.batch_kwargs if ah.is_batch else None,
                    location=ah.location,
                    domain=self._infer_domain_from_name(ah.handler_name),
                )
                handler_map[ah.handler_name] = h_node
            else:
                if not h_node.location and ah.location:
                    h_node.location = ah.location
                if not h_node.docstring and ah.docstring:
                    h_node.docstring = ah.docstring
                if not h_node.summary and ah.summary:
                    h_node.summary = ah.summary

            for ev_name in ah.handled_event_names:
                if ev_name not in h_node.handled_event_ids:
                    h_node.handled_event_ids.append(ev_name)

            for repo in ah.repositories:
                st = self._resolve_repo_to_table(repo, list(storage_map.values()))
                if st and st.id not in h_node.persisted_storage_ids:
                    h_node.persisted_storage_ids.append(st.id)
                    graph.edges.append(
                        ArchitectureEdge(
                            source_id=h_node.id,
                            target_id=st.id,
                            edge_type=EdgeType.WRITES_TO,
                            label="persists",
                        )
                    )

        # Connect Events -> Channels -> Handlers
        for rh in runtime_data.get("registry_handlers", []):
            ev_name = rh["event_name"]
            h_name = rh["handler_name"]
            is_batch = rh.get("is_batch", False)
            batch_cfg = rh.get("batch_config") or {}

            ev_node = event_map.get(ev_name)
            if not ev_node:
                ev_node = DomainEventNode(
                    id=f"event.{ev_name}",
                    name=ev_name,
                    summary="Discovered from event handler registration.",
                    docstring="Discovered from event handler registration.",
                    domain=self._infer_domain_from_name(ev_name),
                )
                event_map[ev_name] = ev_node

            h_node = handler_map.get(h_name)
            if not h_node:
                continue

            if ev_node.id not in h_node.handled_event_ids:
                h_node.handled_event_ids.append(ev_node.id)

            if is_batch:
                chan_id = f"channel.redis_batch.{h_name}"
                w_sec = batch_cfg.get("window_seconds", 30)
                max_sz = batch_cfg.get("max_batch_size", 25)
                batch_chan = ChannelNode(
                    id=chan_id,
                    name=f"Redis Batch Buffer ({w_sec}s / {max_sz} items)",
                    channel_type=ChannelType.REDIS_BATCH,
                    configuration=batch_cfg,
                )
                channel_map[chan_id] = batch_chan

                graph.edges.append(
                    ArchitectureEdge(
                        source_id=ev_node.id,
                        target_id=batch_chan.id,
                        edge_type=EdgeType.ROUTED_THROUGH,
                        label="buffer",
                    )
                )
                graph.edges.append(
                    ArchitectureEdge(
                        source_id=batch_chan.id,
                        target_id=h_node.id,
                        edge_type=EdgeType.DELIVERED_TO,
                        label="flush batch",
                        metadata={"event_id": ev_node.id},
                    )
                )
                # Link batch buffer to redis storage
                graph.edges.append(
                    ArchitectureEdge(
                        source_id=batch_chan.id,
                        target_id=redis_storage.id,
                        edge_type=EdgeType.WRITES_TO,
                        label="buffered in Redis",
                    )
                )
            else:
                if not any(e.source_id == ev_node.id and e.target_id == bus_channel.id for e in graph.edges):
                    graph.edges.append(
                        ArchitectureEdge(
                            source_id=ev_node.id,
                            target_id=bus_channel.id,
                            edge_type=EdgeType.ROUTED_THROUGH,
                            label="publish",
                        )
                    )
                graph.edges.append(
                    ArchitectureEdge(
                        source_id=ev_node.id,
                        target_id=h_node.id,
                        edge_type=EdgeType.DELIVERED_TO,
                        label="dispatch",
                        metadata={"event_id": ev_node.id},
                    )
                )

        # 9. Additional handler storage links by naming convention
        for h in handler_map.values():
            h_lower = h.name.lower()
            for t_name, t_node in storage_map.items():
                t_clean = t_name.replace("_", "").lower()
                if t_clean in h_lower and len(t_clean) > 3:
                    edge = ArchitectureEdge(
                        source_id=h.id,
                        target_id=t_node.id,
                        edge_type=EdgeType.WRITES_TO,
                        label="persists",
                    )
                    if not any(e.source_id == edge.source_id and e.target_id == edge.target_id for e in graph.edges):
                        graph.edges.append(edge)

        # 10. Process Flows
        flows = self._build_process_flows(list(event_map.values()), list(service_map.values()), graph.edges)
        graph.flows = flows

        # Normalize domains for all nodes
        for s in service_map.values():
            s.domain = normalize_domain_name(s.domain)
        for e in event_map.values():
            e.domain = normalize_domain_name(e.domain)
        for h in handler_map.values():
            h.domain = normalize_domain_name(h.domain)

        # Populate final graph (deduplicate use_cases by id)
        graph.entrypoints = sorted(entrypoint_map.values(), key=lambda x: x.name)
        unique_ucs = {uc.id: uc for uc in use_case_map.values()}
        graph.use_cases = sorted(unique_ucs.values(), key=lambda x: x.name)
        graph.services = sorted(service_map.values(), key=lambda x: x.name)
        graph.events = sorted(event_map.values(), key=lambda x: x.name)
        graph.channels = sorted(channel_map.values(), key=lambda x: x.name)
        graph.handlers = sorted(handler_map.values(), key=lambda x: x.name)
        graph.storage_entities = sorted(storage_map.values(), key=lambda x: x.name)

        return graph

    def _resolve_repo_to_table(self, repo_name: str, tables: list[StorageEntityNode]) -> StorageEntityNode | None:
        """Map repository identifier to corresponding storage table."""
        clean = (
            repo_name.replace("SqlAlchemy", "")
            .replace("Repository", "")
            .replace("Repo", "")
            .replace("_", "")
            .lower()
        )
        if not clean:
            return None

        # Direct canonical entity aliases
        if clean in ("user", "users"):
            for t in tables:
                if t.name == "users":
                    return t
        if clean in ("usersession", "usersessions"):
            for t in tables:
                if t.name == "user_sessions":
                    return t
        if clean in ("tokencache", "token", "tokens"):
            for t in tables:
                if "redis" in t.name or "session" in t.name:
                    return t

        # 1. Exact or standard plural match
        for t in tables:
            t_clean = t.name.replace("_", "").lower()
            if clean == t_clean or f"{clean}s" == t_clean or f"{clean}es" == t_clean:
                return t

        # 2. Singular stem match
        clean_stem = clean.rstrip("s")
        for t in tables:
            t_stem = t.name.replace("_", "").lower().rstrip("s")
            if clean_stem == t_stem:
                return t

        # 3. Substring match fallback
        for t in tables:
            t_clean = t.name.replace("_", "").lower()
            if clean in t_clean or t_clean in clean:
                return t
        return None

    def _match_service(self, call_expr: str, services: list[ServiceNode]) -> ServiceNode | None:
        """Match invocation expression like booking_service.create to ServiceNode."""
        call_clean = call_expr.split(".")[-1].lower()
        # 1. Exact match on service name
        for s in services:
            if s.name.lower() == call_clean:
                return s

        # 2. Substring core match
        call_lower = call_expr.lower()
        for s in services:
            s_core = s.name.lower().replace("service", "")
            if s_core and (s_core in call_clean or s_core in call_lower):
                return s
        return None

    def _infer_domain_from_name(self, name: str) -> str:
        """Infer domain name from PascalCase or snake_case symbol."""
        clean = name
        for suffix in ("Event", "Handler", "Service", "Repository", "UseCase", "Task"):
            if clean.endswith(suffix) and len(clean) > len(suffix):
                clean = clean[: -len(suffix)]
                break
        return clean.lower()

    def _build_process_flows(
        self,
        events: list[DomainEventNode],
        services: list[ServiceNode],
        edges: list[ArchitectureEdge],
    ) -> list[ProcessFlow]:
        """Automatically group events sharing common business prefixes into flows."""
        flows: list[ProcessFlow] = []
        domain_groups: dict[str, list[DomainEventNode]] = {}

        for ev in events:
            prefix = ev.name
            for suffix in ("CreatedEvent", "UpdatedEvent", "DeletedEvent", "StatusUpdatedEvent", "FailedEvent", "Event"):
                if prefix.endswith(suffix) and len(prefix) > len(suffix):
                    prefix = prefix[: -len(suffix)]
                    break
            domain_groups.setdefault(prefix, []).append(ev)

        for domain, domain_events in domain_groups.items():
            if len(domain_events) >= 1:
                flow_id = f"flow.{domain.lower()}_lifecycle"
                flow_name = f"{domain} Lifecycle Flow"
                ev_ids = [e.id for e in domain_events]
                flows.append(
                    ProcessFlow(
                        id=flow_id,
                        name=flow_name,
                        description=f"End-to-end lifecycle flow for {domain} operations, events, and persistence.",
                        event_ids=ev_ids,
                    )
                )

        return flows
