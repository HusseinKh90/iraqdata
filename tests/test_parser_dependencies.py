"""
Parser dependencies are declared.

Every third-party module imported by a parser or by the pipeline tooling must be listed in
pyproject.toml, in the runtime dependencies or the `pipeline` extra, and every parser module
must import cleanly with those dependencies installed.
"""

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

PIPELINE = REPO_ROOT / "pipeline"
PARSER_FILES = sorted((PIPELINE / "parsers").glob("parse_*.py"))
TOOL_FILES = [PIPELINE / "run_parsers.py", PIPELINE / "raw_audit.py", PIPELINE / "downloads.py",
              PIPELINE / "check_cosit_record.py", PIPELINE / "check_fiscal_seed.py"]
LOCAL_MODULES = ({p.stem for p in PIPELINE.glob("*.py")} | {p.stem for p in (PIPELINE / "parsers").glob("*.py")}
                 | {"iraqdata"})
DISTRIBUTION_OF = {"yaml": "pyyaml"}


def _normalise(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def declared_distributions() -> set:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        runtime = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M).group(1)
        extra = re.search(r"^pipeline\s*=\s*\[(.*?)\]", text, re.S | re.M).group(1)
        return {_normalise(r) for r in re.findall(r'"([^"]+)"', runtime + extra)}
    data = tomllib.loads(text)
    reqs = data["project"]["dependencies"] + data["project"]["optional-dependencies"]["pipeline"]
    return {_normalise(r) for r in reqs}


def imported_top_level(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_parser_imports_are_declared():
    declared = declared_distributions()
    undeclared = {}
    for path in PARSER_FILES + TOOL_FILES:
        third_party = imported_top_level(path) - set(sys.stdlib_module_names) - LOCAL_MODULES
        missing = sorted(m for m in third_party if DISTRIBUTION_OF.get(m, m).lower() not in declared)
        if missing:
            undeclared[path.name] = missing
    assert undeclared == {}, f"imported but not declared in pyproject.toml: {undeclared}"


@pytest.mark.parametrize("module", [p.stem for p in PARSER_FILES])
def test_every_parser_imports(module):
    importlib.import_module(module)


def test_document_readers_are_declared():
    """pipeline/check_cosit_record.py reads the archived COSIT PDFs (pdfplumber) and legacy .xls workbook (xlrd)."""
    assert {"pdfplumber", "xlrd", "openpyxl"} <= declared_distributions()
