"""
Git storage of data files.

Data files are stored byte-exact (no line-ending conversion); release metadata is always LF;
code and docs keep text=auto.
"""

import shutil
import subprocess

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
                                reason="needs git and a git checkout")


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def _attrs(paths, *names):
    """{path: {attribute: value}}; NUL-separated so non-ASCII (Arabic) file names are not quoted."""
    fields = _git("check-attr", "-z", *names, "--", *paths).split("\0")
    out = {}
    for path, name, value in zip(fields[0::3], fields[1::3], fields[2::3]):
        out.setdefault(path, {})[name] = value
    return out


def _tracked(*patterns):
    return [p for p in _git("ls-files", "-z", "--", *patterns).split("\0") if p]


def test_data_files_are_not_text():
    paths = _tracked("*.csv", "pipeline/raw", "pipeline/seeds", "pipeline/archive",
                     "*.parquet", "*.xlsx", "*.xls", "*.pdf", "*.zip")
    assert len(paths) > 50
    wrong = {p: a["text"] for p, a in _attrs(paths, "text").items() if a["text"] != "unset"}
    assert wrong == {}


def test_release_metadata_is_lf():
    paths = ["release/data-2026-10/checksums.sha256", "release/data-2026-10/datapackage.json",
             "pipeline/data/datapackage.json"]
    for path, a in _attrs(paths, "text", "eol").items():
        assert (a["text"], a["eol"]) == ("set", "lf"), path


def test_code_and_docs_keep_text_auto():
    for path, a in _attrs(["pipeline/export_release.py", "README.md", "pipeline/metadata/raw_manifest.yaml"],
                          "text").items():
        assert a["text"] == "auto", path


@pytest.mark.parametrize("path", [
    "release/data-2026-10/bis_lbs_quarterly.csv",
    "pipeline/raw/jodi/jodi_iraq_2010.csv",
    "pipeline/seeds/iraq_fiscal_historical.csv",
])
def test_fingerprinted_crlf_files_are_stored_as_crlf(path):
    """These files were fingerprinted with CRLF line endings; git must store exactly those bytes."""
    assert _git("ls-files", "--eol", "--", path).split()[0] == "i/crlf"
