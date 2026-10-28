"""
Provenance corrections register.

A correction replaces a published source_hash without changing any value. Nothing has needed
correcting since the first release, so the register is empty; these tests check that it is, and
that the mechanism works on a made-up correction.
"""

import pytest

import raw_audit

CORRECTIONS = raw_audit.load_corrections()


@pytest.fixture(scope="module")
def manifest():
    m = raw_audit.load_manifest()
    return m.get("files", []), {g["id"]: g for g in m.get("input_groups", [])}


def _made_up(manifest):
    """A correction from a hash that names no file to the hash of an archived file."""
    files, _ = manifest
    return {"id": "PC1", "table": "oil_monthly", "series": ["oil_price_basrah"], "from": "2004-01", "to": "2026-10",
            "published_hash": "0123456789abcdef", "corrected_hash": files[0]["sha256"][:16],
            "releases": ["data-2026-10"], "applied": "in_place"}


def test_the_register_is_empty_until_a_published_hash_is_corrected():
    assert CORRECTIONS == []


def test_a_hash_that_names_no_file_resolves_through_its_correction(manifest):
    files, groups = manifest
    correction = _made_up(manifest)
    assert raw_audit.classify_hash(correction["published_hash"], files, groups)[0] == "unresolved"
    case, target = raw_audit.classify_hash(correction["published_hash"], files, groups, [correction])
    assert (case, target) == ("corrected", files[0]["path"])


def test_a_hash_that_names_a_real_file_stays_that_file(manifest):
    files, groups = manifest
    correction = dict(_made_up(manifest), published_hash=files[1]["sha256"][:16])
    case, target = raw_audit.classify_hash(correction["published_hash"], files, groups, [correction])
    assert (case, target) == ("file", files[1]["path"])
