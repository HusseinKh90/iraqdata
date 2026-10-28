"""
Aid series and BIS net position definitions.

Each published aid series is labelled with the World Bank WDI indicator it is read from, the
parser refuses a file carrying a different indicator, no doc mislabels the grants, and the BIS
net position states its sign and scope.
"""

import json
import re

import pytest
import yaml

import export_release
import flags
import parse_oecd_dac
from conftest import REPO_ROOT

CATALOG = REPO_ROOT / "src" / "iraqdata" / "series_catalog.yaml"
RAW_OECD = REPO_ROOT / "pipeline" / "raw" / "oecd"
KEY_PHRASE = {
    "DT.ODA.ALLD.CD": "net official development assistance and official aid received",
    "BX.GRT.EXTA.CD.WD": "excluding technical cooperation",
}
FILE_OF = {"oecd.dac.oda_total_net": "wb_oda_net.json", "oecd.dac.grants_excl_tc": "wb_oda_grants.json"}
DOCS = [d for d in ("README.md", "docs/series.md", "docs/source_inventory.md", "docs/collecting_data_doc.md")
        if (REPO_ROOT / d).is_file()]      # the last two are internal documents, not always present


def _entries():
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["series"]


def _withdrawn(entry):
    return entry.get("status") == "withdrawn"


def _write_catalog(tmp_path, entries):
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump({"series": entries}, allow_unicode=True), encoding="utf-8")
    return path


# --- Catalog field checks -------------------------------------------------------------

@pytest.mark.parametrize("change, message", [
    ({"replaced_by": "no.such.series"}, "unknown series"),
    ({"replaced_by": "oecd.dac.oda_total_net", "unit": "BILLION_USD"}, "unit"),
    ({"source_indicator": "  "}, "non-empty"),
])
def test_bad_catalog_fields_are_rejected(tmp_path, change, message):
    entries = [dict(e) for e in _entries()]
    target = next(e for e in entries if e["series_id"] == "oecd.dac.grants_excl_tc")
    target.update(change)
    with pytest.raises(ValueError, match=message) as exc:
        flags.load_catalog(_write_catalog(tmp_path, entries))
    assert "oecd.dac.grants_excl_tc" in str(exc.value)


# --- labels match the indicator in each raw file --------------------------------

def test_published_aid_series_are_exactly_two():
    published = sorted(e["series_id"] for e in _entries() if e["category"] == "oecd" and not _withdrawn(e))
    assert published == ["oecd.dac.grants_excl_tc", "oecd.dac.oda_total_net"]


@pytest.mark.parametrize("sid", sorted(FILE_OF))
def test_catalog_matches_the_indicator_in_its_raw_file(sid):
    entry = flags.load_catalog()[sid]
    raw = json.loads((REPO_ROOT / entry["source_file"]).read_text(encoding="utf-8"))
    assert entry["source_file"] == f"pipeline/raw/oecd/{FILE_OF[sid]}"
    assert {row["indicator"]["id"] for row in raw[1]} == {entry["source_indicator"]}
    text = f"{entry['name_en']} {entry['description']}".lower()
    assert KEY_PHRASE[entry["source_indicator"]] in text
    assert "OECD DAC" in entry["primary_source"] and "IMF" not in entry["primary_source"]


def test_no_aid_series_is_withdrawn_or_renamed():
    """The only aid series are the two read from the WDI files; no gross, concessional-loan or total-grants series exists."""
    ids = {e["series_id"] for e in _entries() if e["category"] == "oecd"}
    assert ids == {"oecd.dac.oda_total_net", "oecd.dac.grants_excl_tc"}
    assert not any(_withdrawn(e) or "replaced_by" in e for e in _entries() if e["category"] == "oecd")


# --- no doc mislabels the series -----------------------------------------

def test_no_doc_says_the_grants_include_technical_cooperation():
    grants = re.compile(r"grants_excl_tc|BX\.GRT\.EXTA", re.I)
    for name in DOCS + ["src/iraqdata/series_catalog.yaml"]:
        for n, line in enumerate((REPO_ROOT / name).read_text(encoding="utf-8").splitlines(), start=1):
            low = line.lower()
            if grants.search(line) and "technical cooperation" in low:
                assert "excluding" in low or "excludes" in low, f"{name}:{n}: {line.strip()}"


def test_published_aid_series_are_not_called_loans_or_gross():
    """Net ODA's definition may mention gross disbursements; no series may be named for them."""
    for e in _entries():
        if e["category"] == "oecd" and not _withdrawn(e):
            assert "gross disbursements" not in e["name_en"].lower(), e["series_id"]
            assert "concessional loan" not in f"{e['name_en']} {e['description']}".lower(), e["series_id"]
    rows = [line for line in (REPO_ROOT / "docs" / "series.md").read_text(encoding="utf-8").splitlines()
            if line.startswith(("| `oecd.dac.oda_total_net` | Annual", "| `oecd.dac.grants_excl_tc` | Annual"))]
    assert len(rows) == 2
    for line in rows:
        assert "concessional loan" not in line.lower(), line


# --- parser guard and output ----------------------------------------------

def _copy_raw(tmp_path):
    for name in ("wb_oda_net.json", "wb_oda_grants.json"):
        (tmp_path / name).write_bytes((RAW_OECD / name).read_bytes())


def test_parser_rejects_a_file_with_another_indicator(tmp_path):
    _copy_raw(tmp_path)
    path = tmp_path / "wb_oda_grants.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[1][3]["indicator"]["id"] = "BX.GRT.TECH.CD.WD"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        parse_oecd_dac.parse_oecd_dac(tmp_path)
    msg = str(exc.value)
    assert "wb_oda_grants.json" in msg and "BX.GRT.EXTA.CD.WD" in msg and "BX.GRT.TECH.CD.WD" in msg


def test_parser_output_equals_the_raw_files(tmp_path):
    _copy_raw(tmp_path)
    df = parse_oecd_dac.parse_oecd_dac(tmp_path)
    assert sorted(df["series_id"].unique()) == sorted(FILE_OF)
    for sid, name in FILE_OF.items():
        raw = json.loads((RAW_OECD / name).read_text(encoding="utf-8"))
        expected = {row["date"]: round(float(row["value"]) / 1_000_000.0, 3)
                    for row in raw[1] if row["value"] is not None and int(row["date"]) >= 2004}
        sub = df[df["series_id"] == sid]
        assert len(sub) == 20
        assert dict(zip(sub["date"], sub["value"])) == expected
        assert set(sub["source_hash"]) == {parse_oecd_dac.compute_file_hash(RAW_OECD / name)}


# --- BIS net position -----------------------------------------------------------

BIS_PHRASES = ["minus their claims", "net creditor", "bis reporting banks", "not the international investment position"]


def test_bis_net_position_states_sign_and_scope():
    entry = flags.load_catalog()["bis.lbs.net_position"]
    desc = " ".join(entry["description"].split()).lower()
    for phrase in BIS_PHRASES:
        assert phrase in desc, phrase
    assert "BIS Reporting Banks" in entry["name_en"] and "External Asset Position" not in entry["name_en"]
    exported = export_release.series_catalog_entry(entry)
    assert exported["description"] == entry["description"]


def test_series_doc_states_bis_sign_and_scope():
    row = next(line for line in (REPO_ROOT / "docs" / "series.md").read_text(encoding="utf-8").splitlines()
               if line.startswith("| `bis.lbs.net_position`"))
    low = row.lower()
    for phrase in ["minus", "net creditor", "bis reporting banks", "international investment position"]:
        assert phrase in low, phrase
