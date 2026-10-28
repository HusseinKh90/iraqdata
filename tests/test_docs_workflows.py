"""
tests.test_docs_workflows
=========================
The data-collection document describes only workflows
that exist, and marks everything else as planned.
"""

import functools
import os
import re
import subprocess
import sys

import pytest
import yaml

from conftest import REPO_ROOT

DOC = REPO_ROOT / "docs" / "collecting_data_doc.md"
needs_doc = pytest.mark.skipif(not DOC.is_file(), reason="docs/collecting_data_doc.md is an internal document, not in the published repository")
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def lines():
    return DOC.read_text(encoding="utf-8").splitlines()


@needs_doc
def test_every_named_workflow_exists_or_is_planned():
    offending = []
    for n, line in enumerate(lines(), 1):
        for name in re.findall(r"[\w-]+\.yml\b", line):
            if not (WORKFLOWS / name).exists() and "Planned" not in line:
                offending.append(f"{n}: {name}")
    assert offending == []


@needs_doc
def test_every_schedule_claim_is_real_or_planned():
    offending = [f"{n}: {line.strip()[:80]}" for n, line in enumerate(lines(), 1)
                 if re.search(r"\bcron\b", line, re.I) and "update_check.yml" not in line
                 and "Planned" not in line]
    assert offending == []


@needs_doc
def test_document_describes_the_real_update_check():
    text = DOC.read_text(encoding="utf-8")
    assert "update_check.yml" in text
    section = text[text.index("## 3."):]
    assert "report" in section.lower()
    assert "never commits" in section


# =====================================================================
# Status labels, commands and versions agree with the repository
# =====================================================================

def _published_docs():
    """The tracked docs and the README (the milestone logs are not published, so not checked)."""
    tracked = subprocess.run(["git", "ls-files", "docs/*.md"], cwd=REPO_ROOT, capture_output=True,
                             text=True, encoding="utf-8").stdout.split()
    return [REPO_ROOT / p for p in tracked] + [REPO_ROOT / "README.md"]


COMMAND = re.compile(r"python pipeline/(\w+)\.py((?:[ \t]+[^\s`|]+)*)")


@functools.lru_cache(maxsize=None)
def _help(script: str, sub: str = "") -> str:
    args = [sys.executable, f"pipeline/{script}.py"] + ([sub] if sub else []) + ["--help"]
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0, f"{script} {sub} --help failed: {proc.stderr[-500:]}"
    return proc.stdout


def test_documented_commands_exist():
    """Every `python pipeline/<script>.py ...` in the docs names a script and flags it accepts."""
    offending = []
    for doc in _published_docs():
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for script, rest in COMMAND.findall(line):
                if not (REPO_ROOT / "pipeline" / f"{script}.py").is_file():
                    offending.append(f"{doc.name}:{n}: no script pipeline/{script}.py")
                    continue
                words = rest.split()
                sub = words[0] if script == "raw_audit" and words and not words[0].startswith("-") else ""
                text = _help(script, sub)
                for flag in re.findall(r"(?<![\w-])--[a-z][\w-]*", rest):
                    if flag not in text:
                        offending.append(f"{doc.name}:{n}: {script}.py has no {flag}")
    assert offending == []


def test_ci_versions_match_workflow():
    workflow = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    versions = workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    want = f"{versions[0]}–{versions[-1]}"
    found = []
    for doc in _published_docs():
        found += re.findall(r"Python (3\.\d+[–-]3\.\d+)", doc.read_text(encoding="utf-8"))
    assert found and all(v.replace("-", "–") == want for v in found), (found, want)


@needs_doc
def test_implemented_sources_label_planned_parts_explicitly():
    """
    In a source section whose status block says it is implemented, a heading may mark a planned
    part only as "(Planned — not implemented)"; a heading must not call the whole
    implemented live stream "Planned, not implemented".
    """
    text = DOC.read_text(encoding="utf-8")
    offending = []
    for section in re.split(r"\n(?=### Source )", text)[1:]:
        title = section.splitlines()[0]
        status = [l for l in section.splitlines() if l.startswith("**Status")]
        if not any("implemented" in l and "not implemented" not in l for l in status):
            continue
        for line in section.splitlines()[1:]:
            if line.startswith("#") and "not implemented" in line.lower() \
                    and not line.rstrip().endswith("(Planned — not implemented)"):
                offending.append(f"{title}: {line.strip()}")
    assert offending == []


@pytest.mark.parametrize("name", ["establishing_monorepo_skeleton.md", "implement_client_library_interface.md"])
def test_historical_logs_have_banner(name):
    """The milestone logs are kept on the maintainer's computer only; when present they say so."""
    path = REPO_ROOT / "docs" / name
    if not path.exists():
        pytest.skip(f"{name} is not published (kept locally)")
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
    assert "Historical record" in head and "series.md" in head and "../README.md" in head
