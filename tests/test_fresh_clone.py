"""
A fresh clone verifies its own checksums and raw manifest.

The clone reads committed objects, so this checks what users get, not the working tree.
"""

import shutil
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
                       reason="needs git and a git checkout"),
]


@pytest.mark.parametrize("autocrlf, eol", [("false", "lf"), ("true", "crlf")], ids=["linux-like", "windows-like"])
def test_fresh_clone_verifies(tmp_path, autocrlf, eol):
    """Both line-ending conventions; clone -c writes the setting before checkout."""
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", "-c", f"core.autocrlf={autocrlf}",
                    "-c", f"core.eol={eol}", str(REPO_ROOT), str(clone)], check=True)
    # The clone really uses this convention for ordinary text files
    assert (b"\r\n" in (clone / "pyproject.toml").read_bytes()) == (eol == "crlf")
    script = clone / "pipeline" / "verify_integrity.py"
    if not script.exists():  # not committed yet: use the working copy's checker on the clone's data
        shutil.copy2(REPO_ROOT / "pipeline" / "verify_integrity.py", script)
    proc = subprocess.run([sys.executable, str(script)], cwd=clone, capture_output=True, text=True,
                          encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (clone / "release" / "data-2026-10" / "bis_lbs_quarterly.csv").stat().st_size == 70175
