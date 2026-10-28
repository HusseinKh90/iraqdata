"""
tests.test_readme_examples
==========================
Every Python example in README.md runs as written,
offline, against the local production datasets.
"""

import re

import pytest

import iraqdata.storage as storage
from conftest import REPO_ROOT

PYTHON_BLOCK = re.compile(r"(<!-- not run:[^>]*-->\s*\n)?^```python\s*\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _readme_blocks() -> list[str]:
    """The README's Python examples, except those marked `<!-- not run: reason -->` just above them."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    return [code for marker, code in PYTHON_BLOCK.findall(text) if not marker]


def test_readme_has_python_examples():
    assert len(_readme_blocks()) >= 5


def test_readme_python_examples_run(monkeypatch, fresh_memory_cache):
    def _blocked(*args, **kwargs):
        raise storage.requests.exceptions.ConnectionError("network blocked in README test")

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(storage.requests, "get", _blocked)
    monkeypatch.setattr(storage, "_code_pin", None)  # the README pins a release; undone after the test
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.delenv("IRAQDATA_LOCAL_DIR", raising=False)

    namespace: dict = {}
    for i, src in enumerate(_readme_blocks(), start=1):
        try:
            exec(compile(src, f"README python block {i}", "exec"), namespace)
        except Exception as exc:  # pragma: no cover - failure path reports the block
            pytest.fail(f"README python block {i} failed: {exc!r}\n---\n{src}")
