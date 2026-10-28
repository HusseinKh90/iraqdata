"""
Origin segments in the series catalog.

Every series states, period by period, whether its values are observed, derived, modelled,
transcribed or of unknown origin, and the user-facing text never calls non-official data official.
"""

import re

import pandas as pd
import pytest
import yaml

import flags
from conftest import GARDEN_DIR, REPO_ROOT

PACKAGE_CATALOG = REPO_ROOT / "src" / "iraqdata" / "series_catalog.yaml"  # the only catalog
MANIFEST = REPO_ROOT / "pipeline" / "metadata" / "raw_manifest.yaml"
SEGMENT_FIELDS = {"from", "to", "class", "official", "method", "source"}
PERIOD = re.compile(r"^\d{4}(-\d{2}(-\d{2})?|-Q[1-4])?$")


@pytest.fixture(scope="module")
def catalog():
    return yaml.safe_load(PACKAGE_CATALOG.read_text(encoding="utf-8"))["series"]


@pytest.fixture(scope="module")
def published():
    """{series_id: sorted published dates} across the production tables."""
    dates = {}
    for path in sorted(GARDEN_DIR.glob("*.parquet")):
        df = pd.read_parquet(path, columns=["series_id", "date"])
        for sid, d in df.groupby("series_id")["date"]:
            dates[sid] = sorted(d.astype(str))
    return dates


def _p(v):
    return flags.period(v)


def test_every_series_has_well_formed_segments(catalog):
    for entry in catalog:
        segs = entry.get("origin")
        assert segs, entry["series_id"]
        for seg in segs:
            assert SEGMENT_FIELDS <= set(seg), (entry["series_id"], seg)
            assert seg["class"] in flags.ORIGIN_CLASSES, (entry["series_id"], seg["class"])
            assert isinstance(seg["official"], bool), entry["series_id"]
            assert str(seg["method"]).strip() and str(seg["source"]).strip(), entry["series_id"]
            assert PERIOD.match(_p(seg["from"])), (entry["series_id"], seg["from"])
            assert _p(seg["to"]) == flags.OPEN or PERIOD.match(_p(seg["to"])), (entry["series_id"], seg["to"])
            if seg["class"] == "derived":
                assert seg.get("inputs"), (entry["series_id"], "derived segments name their inputs")


def test_segments_do_not_overlap(catalog):
    for entry in catalog:
        segs = sorted(entry["origin"], key=lambda s: _p(s["from"]))
        for a, b in zip(segs, segs[1:]):
            assert _p(a["to"]) != flags.OPEN and _p(a["to"]) < _p(b["from"]), entry["series_id"]


def test_segments_cover_every_published_period(catalog, published):
    """No published observation is unclassified."""
    for entry in catalog:
        for d in published.get(entry["series_id"], []):
            flags.segment_for(entry, d)  # raises if uncovered


def test_records_exist_in_the_manifest(catalog):
    listed = {e["path"] for e in yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["files"]}
    for entry in catalog:
        for seg in entry["origin"]:
            if seg["class"] == "transcribed" or seg.get("record"):
                assert seg.get("record") in listed, (entry["series_id"], seg.get("record"))


def test_no_modelled_series_is_published(catalog, published):
    """Modelled (in-house estimated) values are not published."""
    for entry in catalog:
        for d in published.get(entry["series_id"], []):
            assert flags.segment_for(entry, d)["class"] != "modelled", (entry["series_id"], d)


def test_non_official_series_are_not_called_official(catalog):
    """A series with a non-official or unknown segment is not described as official."""
    for entry in catalog:
        if all(s["class"] in ("observed", "derived") and s["official"] for s in entry["origin"]):
            continue
        text = f"{entry.get('name_en', '')} {entry.get('description', '')}"
        text = re.sub(r"official development assistance", "", text, flags=re.I)  # the name of ODA
        assert not re.search(r"\bofficial(ly)?\b", text, re.I), entry["series_id"]


def test_linked_cpi_is_not_official(catalog):
    """The linked CPI is built by iraqdata from official bases but is not itself an official series."""
    from iraqdata.catalog import is_official

    by_id = {e["series_id"]: e for e in catalog}
    for sid in ("cpi_headline", "cpi_core"):
        assert not is_official(by_id[sid]["origin"]), sid
    for sid in ("cpi.headline_2022", "cpi.core_2022", "cpi.headline_1993"):  # the native bases stay official
        assert is_official(by_id[sid]["origin"]), sid


def test_docs_in_sync():
    """docs/series.md's origin block and README.md's measured share match the catalog and data."""
    import docs_origin
    stale = [p.name for p, current, wanted in docs_origin.updated_files() if current != wanted]
    assert stale == [], f"run python pipeline/docs_origin.py ({stale})"
    assert "Official price" not in (REPO_ROOT / "docs" / "series.md").read_text(encoding="utf-8")


# --- The series tables of docs/series.md come from the catalog ----------

def _generated_rows():
    """{series_id: [cells]} from the generated series:<key> blocks, and how often each id appears."""
    text = (REPO_ROOT / "docs" / "series.md").read_text(encoding="utf-8")
    rows, seen = {}, []
    for block in re.findall(r"<!-- series:[a-z_]+:begin -->(.*?)<!-- series:[a-z_]+:end -->", text, re.S):
        for line in block.splitlines():
            m = re.match(r"^\| `([^`]+)` \| (.*) \|$", line)
            if m:
                seen.append(m.group(1))
                rows[m.group(1)] = [c.strip() for c in re.split(r"(?<!\\)\|", m.group(2))]
    return rows, seen


def test_series_tables_cover_catalog(catalog):
    import docs_origin
    rows, seen = _generated_rows()
    assert sorted(seen) == sorted(e["series_id"] for e in catalog)
    assert len(seen) == len(set(seen)), "a series appears in more than one table"
    for e in catalog:
        freq, unit, starts, _ = rows[e["series_id"]]
        assert freq == e["frequency"].title(), e["series_id"]
        assert unit == docs_origin.UNIT_LABELS[e["unit"]], e["series_id"]
        assert starts == _p(e["start_date"]), e["series_id"]


def test_summary_rules(catalog):
    """`summary` is required, with "No line breaks and no `|`"."""
    for e in catalog:
        s = e.get("summary")
        assert isinstance(s, str) and s.strip(), e["series_id"]
        assert "\n" not in s and "|" not in s, e["series_id"]
