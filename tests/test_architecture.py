"""
tests.test_architecture
=======================
The client library under src/iraqdata/ never
imports from the pipeline/ layer.
"""

import ast

import pytest

from conftest import REPO_ROOT

CLIENT_MODULES = sorted((REPO_ROOT / "src" / "iraqdata").rglob("*.py"))


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_client_modules_found():
    assert CLIENT_MODULES


@pytest.mark.parametrize("path", CLIENT_MODULES, ids=lambda p: p.name)
def test_client_never_imports_pipeline(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offending = [m for m in _imported_modules(tree) if m == "pipeline" or m.startswith("pipeline.")]
    assert offending == []
