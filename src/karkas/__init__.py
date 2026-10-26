"""Karkas: Live Architecture Skeleton & Contract Validator."""

__version__ = "0.1.1"

from karkas.cli import app
from karkas.core.ir import (
    ArchitectureGraph,
    DomainEventNode,
    HandlerNode,
    ServiceNode,
)

__all__ = ["ArchitectureGraph", "DomainEventNode", "HandlerNode", "ServiceNode", "__version__", "app"]
