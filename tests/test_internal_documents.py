"""
tests.test_internal_documents
=============================
Five documents are the maintainer's own (runbooks, the source inventory, the record contract). They are
listed in .gitignore, so a repository that does not track them still passes every test, and nothing
that is published points to them.
"""

import re
import subprocess

from conftest import REPO_ROOT

INTERNAL = ["docs/maintaining.md", "docs/publishing.md", "docs/collecting_data_doc.md",
            "docs/source_inventory.md", "docs/transcription_records.md"]
PUBLISHED_TEXT = (".md", ".cff", ".toml", ".yml")


def _tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    return [p for p in out.stdout.split("\0") if p]


def test_gitignore_lists_exactly_the_internal_documents():
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line in {f"/{path}" for path in INTERNAL}] == [f"/{path}" for path in INTERNAL]


def test_git_ignores_them():
    for path in INTERNAL:
        proc = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=REPO_ROOT)
        assert proc.returncode == 0, path


def test_nothing_published_points_to_an_internal_document():
    """README, the other documents, the licences and the metadata never name an internal document."""
    names = [path.split("/")[-1] for path in INTERNAL]
    offending = []
    for path in _tracked():
        if path in INTERNAL or not (path.endswith(PUBLISHED_TEXT) or path in ("LICENSE", "LICENSE-DATA")):
            continue
        if path.startswith(("pipeline/raw/", "release/", "tests/")):
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        for name in names:
            if re.search(rf"docs/{re.escape(name)}|\]\([^)]*{re.escape(name)}", text):
                offending.append(f"{path}: {name}")
    assert offending == []
