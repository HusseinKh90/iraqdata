"""
tests.test_repository_slug
==========================
The repository the data is downloaded from is named once, in `iraqdata.storage.DEFAULT_REPO`.
Everything that links to the repository agrees with it, so moving the project means changing that
constant and the files listed in docs/publishing.md, and this test says which one was missed.
"""

import re

import yaml

import iraqdata.storage as storage
from conftest import REPO_ROOT

SLUG = storage.DEFAULT_REPO
GITHUB_LINK = re.compile(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?(?=[/`)\s\"'}]|$)")
OTHERS = {"HusseinKh90/Iraq-parallel-exchange-rate"}   # a data source, not this repository


def _links(path):
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    return {m.group(1) for m in GITHUB_LINK.finditer(text)} - OTHERS


def test_the_default_repository_is_owner_slash_name():
    assert re.fullmatch(r"[\w.-]+/[\w.-]+", SLUG)


def test_readme_citation_and_package_metadata_link_to_it():
    for path in ("README.md", "CITATION.cff", "pyproject.toml"):
        links = _links(path)
        assert links, path
        assert {link.lower() for link in links} == {SLUG.lower()}, (path, links)


def test_the_citation_names_it():
    citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["url"].lower().endswith(SLUG.lower()) and citation["repository-code"].lower().endswith(SLUG.lower())


def test_the_release_descriptor_names_it():
    import json
    descriptor = json.loads((REPO_ROOT / "pipeline" / "data" / "datapackage.json").read_text(encoding="utf-8"))
    assert descriptor["homepage"] == f"https://github.com/{SLUG}"


def test_the_user_agent_links_to_it():
    import downloads
    assert SLUG.lower() in downloads.PROJECT_URL.lower()
