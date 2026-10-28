"""The raw-layer audit report runs cleanly and changes nothing."""

import os
import subprocess
import sys

from conftest import REPO_ROOT, diff_trees, hash_tree


def test_report_runs_clean():
    before = hash_tree(REPO_ROOT / "pipeline")
    proc = subprocess.run(
        [sys.executable, "pipeline/raw_audit.py", "report"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr
    # "confirmed": the hand-check section (all 36 values with a source were confirmed on 2026-10-25,
    # so the word "pending" no longer appears)
    for text in ("known-findings register: 0", "confirmed", "unknown", "Raw-layer audit: OK"):
        assert text in proc.stdout, text
    changed = [p for p in diff_trees(before, hash_tree(REPO_ROOT / "pipeline")) if "__pycache__" not in p]
    assert changed == []
