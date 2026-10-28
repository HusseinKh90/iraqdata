"""
tests.test_user_guide
=====================
Every Python example in docs/user_guide.md runs as written, offline, against the local data, and the
guide's lists (tables, subjects, short names, errors, settings) are the library's own.
"""

import re

import pytest

import iraqdata
import iraqdata.errors as errors
import iraqdata.storage as storage
from conftest import REPO_ROOT

GUIDE = REPO_ROOT / "docs" / "user_guide.md"
TEXT = GUIDE.read_text(encoding="utf-8")
BLOCK = re.compile(r"(<!-- not run:[^>]*-->\s*\n)?^```python\s*\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _blocks():
    return [code for marker, code in BLOCK.findall(TEXT) if not marker]


def _backticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def test_the_guide_has_examples_and_marks_those_it_does_not_run():
    assert len(_blocks()) >= 19
    assert len(BLOCK.findall(TEXT)) - len(_blocks()) == 4          # openpyxl, refresh, clear_cache, as_of


def test_every_example_runs(monkeypatch, tmp_path, fresh_memory_cache):
    def _blocked(*args, **kwargs):
        raise storage.requests.exceptions.ConnectionError("network blocked in the user guide test")

    monkeypatch.chdir(tmp_path)                                    # the examples write m2.csv
    monkeypatch.setattr(storage.requests, "get", _blocked)
    monkeypatch.setattr(storage, "_code_pin", None)                # the guide pins a release; undone after the test
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.delenv("IRAQDATA_LOCAL_DIR", raising=False)
    namespace: dict = {}
    for i, src in enumerate(_blocks(), start=1):
        try:
            exec(compile(src, f"user guide python block {i}", "exec"), namespace)
        except Exception as exc:  # pragma: no cover - failure path reports the block
            pytest.fail(f"user guide python block {i} failed: {exc!r}\n---\n{src}")
    assert (tmp_path / "m2.csv").is_file()


def test_the_counts_and_lists_are_the_libraries(fresh_memory_cache):
    assert f"There are {len(iraqdata.list_series())} series in ten subject tables" in TEXT
    assert len(iraqdata.list_tables()) == 10
    for table in iraqdata.list_tables():
        assert f"`{table}`" in TEXT, table
    for category in iraqdata.list_categories():
        assert f"`{category}`" in TEXT, category
    for unit in sorted(set(iraqdata.list_series()["unit"])):
        assert f"`{unit}`" in TEXT, unit


def test_every_short_name_in_the_guide_means_what_it_says(fresh_memory_cache):
    section = TEXT[TEXT.index("### Names of series"):TEXT.index("A name that does not exist")]
    rows = [line.strip("|").split("|") for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) >= 9
    for cells in rows:
        for names_cell, series_cell in ((cells[0], cells[1]), (cells[2], cells[3])):
            ids = [i for i in _backticks(series_cell) if "." in i or "_" in i]
            for name in _backticks(names_cell):
                resolved = iraqdata.resolve_series_id(name)
                assert not ids or resolved in ids, (name, resolved, ids)


def test_every_error_named_in_the_guide_exists():
    section = TEXT[TEXT.index("## 10. Errors and warnings"):TEXT.index("## 11. Quick reference")]
    for name in re.findall(r"`((?:\w+Error)|FlagWarning)\b", section):
        assert hasattr(errors, name) or hasattr(__builtins__, name) or name in dir(__import__("builtins")), name
    for name in ("ChecksumMismatchError", "ReleaseNotFoundError", "RepositoryNotFoundError", "FileNotInReleaseError",
                 "UnverifiableFileError", "NoVintageHistoryError", "FlagWarning"):
        assert name in section and getattr(iraqdata, name) is getattr(errors, name)


def test_every_setting_in_the_guide_is_read_by_the_library():
    source = (REPO_ROOT / "src" / "iraqdata" / "storage.py").read_text(encoding="utf-8")
    for variable in set(re.findall(r"IRAQDATA_[A-Z_]+", TEXT)):
        assert variable in source, variable


def test_every_function_in_the_quick_reference_is_exported():
    section = TEXT[TEXT.index("## 11. Quick reference"):TEXT.index("## 12.")]
    for name in set(re.findall(r"\| `(\w+)\(", section)):
        assert name in iraqdata.__all__, name
