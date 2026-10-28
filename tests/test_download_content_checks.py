"""
Content and no-shrink checks for downloads. The archived raw files are
the valid samples; each check must reject an HTML page, a wrong header, an empty table and so on.
"""

import io
import json
import zipfile

import pytest

import download_checks as dc
import downloads
import fetchers
from conftest import REPO_ROOT

RAW = REPO_ROOT / "pipeline" / "raw"
FRED = downloads.latest_version(RAW / "fred" / "DCOILBRENTEU.csv")
BIS = downloads.latest_version(RAW / "bis" / "bis_lbs_claims_total.csv")
WB = downloads.latest_version(RAW / "oecd" / "wb_oda_net.json")
FX = downloads.latest_version(RAW / "github" / "daily_fx.csv")
HTML = b"<!DOCTYPE html><html><body>Service unavailable</body></html>"


def test_archived_files_pass():
    dc.check_fred_csv(FRED.read_bytes(), "u")
    dc.check_bis_csv(BIS.read_bytes(), "u", fetchers.BIS_KEY_COLUMNS)
    dc.check_wb_json(WB.read_bytes(), "u", "DT.ODA.ALLD.CD")


@pytest.mark.parametrize("content, match", [
    (HTML, "HTML page"),
    (b"date,value\n2020-01-01,1\n", "header"),
    (b"observation_date,DCOILBRENTEU\n", "no data rows"),
    (b"", "empty"),
])
def test_fred_rejects(content, match):
    with pytest.raises(ValueError, match=match):
        dc.check_fred_csv(content, "https://fred.example/x")


def test_bis_rejects_missing_columns_and_empty_tables():
    header = BIS.read_text(encoding="utf-8").splitlines()[0]
    with pytest.raises(ValueError, match="no data rows"):
        dc.check_bis_csv((header + "\n").encode(), "u", fetchers.BIS_KEY_COLUMNS)
    with pytest.raises(ValueError, match="OBS_VALUE"):
        dc.check_bis_csv(header.replace("OBS_VALUE", "X").encode() + b"\n1\n", "u", fetchers.BIS_KEY_COLUMNS)
    with pytest.raises(ValueError, match="HTML"):
        dc.check_bis_csv(HTML, "u", fetchers.BIS_KEY_COLUMNS)


def test_wb_rejects_wrong_indicator_and_bad_payloads():
    with pytest.raises(ValueError, match="not DT.ODA.ALLD.CD"):
        dc.check_wb_json(downloads.latest_version(RAW / "oecd" / "wb_oda_grants.json").read_bytes(), "u",
                         "DT.ODA.ALLD.CD")
    with pytest.raises(ValueError, match="payload"):
        dc.check_wb_json(json.dumps([{"message": "error"}]).encode(), "u", "DT.ODA.ALLD.CD")
    with pytest.raises(ValueError, match="JSON"):
        dc.check_wb_json(HTML, "u", "DT.ODA.ALLD.CD")


def _zip(**members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name.replace("_", "."), data)
    return buf.getvalue()


def test_eia_zip():
    dc.check_eia_zip(_zip(INTL_txt="rows"), "u")
    with pytest.raises(ValueError, match="no INTL.txt"):
        dc.check_eia_zip(_zip(OTHER_txt="x"), "u")
    with pytest.raises(ValueError, match="not a zip"):
        dc.check_eia_zip(HTML, "u")


def test_not_shrunk_accepts_growth_and_rejects_loss(tmp_path):
    rows = FRED.read_text(encoding="utf-8").splitlines()
    grown = "\n".join(rows + ["2099-01-01,1.0"]).encode()
    dc.check_not_shrunk(grown, FRED, "csv", "u", period_column="observation_date")
    with pytest.raises(ValueError, match="shrank"):
        dc.check_not_shrunk("\n".join(rows[:-10]).encode(), FRED, "csv", "u", period_column="observation_date")
    earlier = "\n".join(rows[:-1] + ["1900-01-01,1.0"]).encode()
    with pytest.raises(ValueError, match="earlier than the archived"):
        dc.check_not_shrunk(earlier, FRED, "csv", "u", period_column="observation_date")
    dc.check_not_shrunk(b"anything", tmp_path / "none.csv", "csv", "u", period_column="date")  # nothing archived


def test_not_shrunk_world_bank_counts_non_null_years():
    payload = json.loads(WB.read_text(encoding="utf-8"))
    dc.check_not_shrunk(WB.read_bytes(), WB, "wb_json", "u")
    payload[1] = [r for r in payload[1] if r["date"] != "2023"]
    with pytest.raises(ValueError):
        dc.check_not_shrunk(json.dumps(payload).encode(), WB, "wb_json", "u")


def test_github_fx_period_column():
    dc.check_not_shrunk(FX.read_bytes(), FX, "csv", "u", period_column="date")
