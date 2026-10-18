"""ArchDoc: Live Architecture Documentation Generator & Contract Validator."""

from archdoc.cli import app
from archdoc.core.ir import ArchitectureGraph, DomainEventNode, HandlerNode, ServiceNode

__all__ = ["ArchitectureGraph", "DomainEventNode", "HandlerNode", "ServiceNode", "app"]
