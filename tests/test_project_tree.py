"""Unit tests for Karkas project file and directory tree extractor."""

from pathlib import Path

from karkas.extractors.project_tree import build_project_tree


def test_build_project_tree_annotates_directories(tmp_path: Path) -> None:
    # Setup sample directory structure
    api_dir = tmp_path / "src" / "application" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "routes.py").write_text("# routes", encoding="utf-8")

    domain_dir = tmp_path / "src" / "core" / "domain"
    domain_dir.mkdir(parents=True)
    (domain_dir / "models.py").write_text("# models", encoding="utf-8")

    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")

    tree = build_project_tree(tmp_path, max_depth=4)

    assert "📁 src/" in tree
    assert "📁 application/" in tree
    assert "📁 api/" in tree
    assert "REST API routers" in tree  # Annotation present
    assert "📁 core/" in tree
    assert "📁 domain/" in tree
    assert "Enterprise business rules" in tree  # Annotation present
    assert "📄 pyproject.toml" in tree
    assert "Project packaging" in tree
