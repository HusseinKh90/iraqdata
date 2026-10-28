"""
Dependency pins for CI and contributors.

Every pyproject dependency has a pin in requirements/ci-constraints.txt that lies inside its
published range, and the CI matrix equals the Python versions the classifiers list.
"""

import re

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from conftest import REPO_ROOT

CONSTRAINTS = REPO_ROOT / "requirements" / "ci-constraints.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _pins():
    pins = []
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            req = Requirement(line)
            assert len(req.specifier) == 1 and next(iter(req.specifier)).operator == "==", line
            pins.append(req)
    return pins


def _project_requirements():
    """[project].dependencies and the pipeline/dev extras, read without tomllib (Python 3.10)."""
    text = PYPROJECT.read_text(encoding="utf-8")
    blocks = re.findall(r'^(?:dependencies|pipeline|dev)\s*=\s*\[(.*?)\]', text, re.M | re.S)
    assert len(blocks) == 3
    return [Requirement(r) for block in blocks for r in re.findall(r'"([^"]+)"', block)]


@pytest.mark.parametrize("req", _project_requirements(), ids=str)
def test_every_dependency_is_pinned_within_its_range(req):
    pins = [p for p in _pins() if canonicalize_name(p.name) == canonicalize_name(req.name)]
    assert pins, f"{req.name} has no pin in {CONSTRAINTS.name}"
    for pin in pins:
        version = next(iter(pin.specifier)).version
        assert req.specifier.contains(version, prereleases=True), (str(req), str(pin))


def test_marker_variants_cover_every_supported_python():
    """A package pinned per Python version has exactly one pin for each supported version."""
    by_name = {}
    for pin in _pins():
        by_name.setdefault(canonicalize_name(pin.name), []).append(pin)
    for name, pins in by_name.items():
        for py in _classifier_versions():
            env = {"python_version": py, "python_full_version": f"{py}.0"}
            active = [p for p in pins if p.marker is None or p.marker.evaluate(env)]
            assert len(active) == 1, (name, py, [str(p) for p in active])


def _classifier_versions():
    return re.findall(r'"Programming Language :: Python :: (3\.\d+)"', PYPROJECT.read_text(encoding="utf-8"))


def test_ci_matrix_equals_classifiers():
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"] == _classifier_versions()
    assert _classifier_versions() == ["3.10", "3.11", "3.12", "3.13"]
