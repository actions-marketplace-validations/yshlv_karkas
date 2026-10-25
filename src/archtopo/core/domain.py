"""Domain and Bounded Context normalization rules for ArchTopo."""

from pathlib import Path

# Canonical Domain Bounded Context aliases and coalescing map
CANONICAL_DOMAIN_MAPPING: dict[str, str] = {
    # Identity & Access Management
    "auth": "auth",
    "user": "auth",
    "users": "auth",
    "user_session": "auth",
    "user_sessions": "auth",
    "passlib_provider": "auth",
    # Booking & Inventory Purchases
    "booking": "booking",
    "bookings": "booking",
    "inventory_import": "booking",
    # Ticket Inventory
    "ticket": "ticket",
    "tickets": "ticket",
    # Order Management & Sales
    "order": "order",
    "orders": "order",
    # Listing & Marketplaces
    "listing": "listing",
    "listings": "listing",
    "external_marketplace": "listing",
    "marketplace": "listing",
    # Event & Venue Catalog
    "event": "event",
    "events": "event",
    "event_group": "event",
    "event_groups": "event",
    # Notification Center
    "notification": "notification",
    "notifications": "notification",
    "notification_counter": "notification",
    "notification_read": "notification",
    # Storage & Media Assets
    "storage": "storage",
    "storage_content": "storage",
    "storage_contents": "storage",
    # Analytics & Dashboard
    "dashboard": "dashboard",
    "export_report": "dashboard",
    "report": "dashboard",
    "reports": "dashboard",
}

# Domain display titles for diagrams and documentation
DOMAIN_DISPLAY_TITLES: dict[str, str] = {
    "auth": "Auth & Identity",
    "booking": "Booking & Inventory Purchases",
    "ticket": "Ticket Inventory",
    "order": "Order Management & Fulfillment",
    "listing": "Listing & Marketplace Distribution",
    "event": "Event & Venue Catalog",
    "notification": "Notification Center & Alerts",
    "storage": "Storage & Media Assets",
    "dashboard": "Analytics & Dashboard",
}

# Directories and files ignored during architecture scanning
IGNORED_PARTS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "tests",
    "test",
    "scripts",
    "migrations",
    "alembic",
    "seed",
}

IGNORED_FILE_STEMS = {
    "test_",
    "conftest",
    "csv_parser",
    "spreadsheet",
    "idempotency",
    "cookies",
    "exception_handlers",
    "middleware",
}


# Generic path segments that should not be treated as domain names
GENERIC_PATH_PARTS = {
    "__init__",
    "base",
    "core",
    "app",
    "src",
    "cream",
    "modules",
    "module",
    "infrastructure",
    "adapters",
    "adapter",
    "ports",
    "port",
    "services",
    "service",
    "handlers",
    "handler",
    "use_cases",
    "use_case",
    "routes",
    "router",
    "views",
    "view",
    "v1",
    "v2",
    "api",
    "models",
    "model",
    "schemas",
    "schema",
    "repositories",
    "repository",
    "repo",
    "interfaces",
    "interface",
    "utils",
    "util",
    "helpers",
    "helper",
    "main",
    "general",
}


def normalize_domain_name(raw_name: str | None) -> str:
    """Normalize a domain identifier to its canonical Bounded Context name."""
    if not raw_name:
        return "general"

    clean = raw_name.lower().strip()
    clean = clean.replace("-", "_")

    if clean in CANONICAL_DOMAIN_MAPPING:
        return CANONICAL_DOMAIN_MAPPING[clean]

    # Handle common pluralization
    if clean.endswith("ies"):
        singular = clean[:-3] + "y"
        if singular in CANONICAL_DOMAIN_MAPPING:
            return CANONICAL_DOMAIN_MAPPING[singular]
    elif clean.endswith("s") and len(clean) > 3 and not clean.endswith("ss"):
        singular = clean[:-1]
        if singular in CANONICAL_DOMAIN_MAPPING:
            return CANONICAL_DOMAIN_MAPPING[singular]

    return clean


def infer_domain_from_path(file_path: Path | str) -> str:
    """Infer canonical domain name from file path, scanning right-to-left."""
    p = Path(file_path)

    # 1. Primary pass: look for a known canonical domain from right to left
    for part in reversed(p.parts):
        clean = Path(part).stem.lower().replace("-", "_")
        if clean in GENERIC_PATH_PARTS:
            continue
        norm = normalize_domain_name(clean)
        if norm in DOMAIN_DISPLAY_TITLES:
            return norm
        if clean in CANONICAL_DOMAIN_MAPPING:
            return CANONICAL_DOMAIN_MAPPING[clean]

    # 2. Secondary pass: first non-generic segment from right
    for part in reversed(p.parts):
        clean = Path(part).stem.lower().replace("-", "_")
        if clean not in GENERIC_PATH_PARTS and len(clean) > 2:
            return normalize_domain_name(clean)

    return "general"


def is_ignored_path(file_path: Path) -> bool:
    """Check if file should be excluded from domain scanning."""
    parts_lower = [p.lower() for p in file_path.parts]
    if any(ig in parts_lower for ig in IGNORED_PARTS):
        return True

    stem_lower = file_path.stem.lower()
    if any(stem_lower.startswith(pref) for pref in ("test_", "conftest")):
        return True
    return stem_lower in IGNORED_FILE_STEMS

