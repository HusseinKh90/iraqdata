"""
pipeline.parsers.parse_oecd_dac
===============================
Parser for Family 9 (Development Assistance & Reconstruction): two World Bank WDI indicators
compiled from OECD Development Assistance Committee (DAC) data, read from the WDI API files
archived under pipeline/raw/oecd/.

Extracts 2 annual series across 20 continuous years (2004 to 2023), one per indicator:
1. `oecd.dac.oda_total_net`: DT.ODA.ALLD.CD, net ODA and official aid received (MILLION_USD)
2. `oecd.dac.grants_excl_tc`: BX.GRT.EXTA.CD.WD, grants excluding technical cooperation, from
   OECD DAC table DAC2A (MILLION_USD)

No gross ODA series and no "concessional loans" series is produced: the files give net ODA and
grants only, and net minus grants mixes two concepts.

Quality Guarantees:
- Every row of each file must carry the indicator id the catalog states in `source_indicator`
; a different indicator stops the run.
- The two indicators are updated at different times: a year only one of them has is published for
  that series alone and reported as [RAGGED]. A year missing inside a series' own range, a
  response with no value, or a paginated response stops the run.
- Enforces Single-Frequency Rule: output contains purely annual observations (YYYY).
- Conforms to standard 7-column Canonical Observation Schema.
- Generates derived seed snapshot `pipeline/seeds/oecd_dac_annual_seed.parquet` (regenerated on every run; see pipeline/run_parsers.py).
- Generates garden dataset: `pipeline/data/garden/oecd_dac_annual.parquet`.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))
sys.path.append(str(repo_root / "pipeline"))  # downloads.latest_version

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import downloads
import source_io  # noqa: E402

UNIT = "MILLION_USD"
REALTIME_START = "2026-10-28"
START_YEAR = 2004
NET_ID = "oecd.dac.oda_total_net"
GRANTS_ID = "oecd.dac.grants_excl_tc"


def compute_file_hash(filepath: Path) -> str:
    """SHA-256 of a file, all 64 hex characters (this parser's source_hash has always been the full digest)."""
    return source_io.file_hash(filepath, length=None)


def check_indicator(path: Path, raw, series_id: str, catalog: Dict[str, dict]) -> None:
    """Every row of a WDI file must carry the indicator id the catalog states."""
    expected = catalog[series_id]["source_indicator"]
    found = sorted({str((item.get("indicator") or {}).get("id")) for item in raw[1]})
    if found != [expected]:
        raise ValueError(f"{path}: indicator {', '.join(found)} does not match the catalog's "
                         f"{expected} for {series_id}")


def parse_oecd_dac(raw_dir: Optional[Path] = None) -> pd.DataFrame:
    """
    Parses archived raw OECD/World Bank JSON files and produces canonical observations.
    """
    if raw_dir is None:
        raw_dir = repo_root / "pipeline" / "raw" / "oecd"
    # Each missing file is named
    net_file = source_io.require_file(downloads.latest_version(raw_dir / "wb_oda_net.json"))
    grants_file = source_io.require_file(downloads.latest_version(raw_dir / "wb_oda_grants.json"))

    net_hash = compute_file_hash(net_file)
    grants_hash = compute_file_hash(grants_file)

    net_raw = source_io.read_json(net_file)
    grants_raw = source_io.read_json(grants_file)
    for path, raw in ((net_file, net_raw), (grants_file, grants_raw)):
        if not (isinstance(raw, list) and len(raw) > 1 and isinstance(raw[1], list)):
            raise source_io.ParseError(path, "a World Bank API response [metadata, rows]", f"{type(raw).__name__}")
        meta = raw[0] if isinstance(raw[0], dict) else {}
        if int(meta.get("pages") or 1) > 1 or int(meta.get("total") or len(raw[1])) != len(raw[1]):
            raise source_io.ParseError(path, "the whole series in one page of the response",
                                       f"page {meta.get('page')} of {meta.get('pages')} ({len(raw[1])} of "
                                       f"{meta.get('total')} rows)")

    catalog = flags.load_catalog()
    check_indicator(net_file, net_raw, NET_ID, catalog)
    check_indicator(grants_file, grants_raw, GRANTS_ID, catalog)

    # Map year -> value in Million USD
    net_by_year: Dict[str, float] = {}
    grants_by_year: Dict[str, float] = {}
    report = source_io.Report("oecd_dac")

    # A JSON null is the API's "no value" for a year (counted); any other non-number stops the run
    for path, raw, sid, by_year in ((net_file, net_raw, NET_ID, net_by_year),
                                    (grants_file, grants_raw, GRANTS_ID, grants_by_year)):
        for n, item in enumerate(raw[1]):
            yr = str(item.get("date", "")).strip()
            if not (yr.isdigit() and START_YEAR <= int(yr)):
                continue
            val = source_io.read_value(item.get("value"), report, path, location=f"item {n}", period=yr, series_id=sid)
            if val is not None:
                if yr in by_year:
                    raise source_io.ParseError(path, f"one value for {yr}", "two", location=f"item {n}", period=yr)
                by_year[yr] = round(val / 1_000_000.0, 3)

    # Each series is published for the years it has. A year inside its own range may not be missing
    series = ((NET_ID, net_file, net_hash, net_by_year), (GRANTS_ID, grants_file, grants_hash, grants_by_year))
    for sid, path, _, by_year in series:
        if not by_year:
            raise source_io.ParseError(path, f"a value for {sid} from {START_YEAR} on", "no value in the file")
        years = sorted(int(y) for y in by_year)
        gaps = [y for y in range(years[0], years[-1] + 1) if str(y) not in by_year]
        if gaps:
            raise source_io.ParseError(path, f"a value for every year from {years[0]} to {years[-1]}",
                                       f"no value for {', '.join(map(str, gaps))}", period=str(gaps[0]))
    last = {sid: max(by_year) for sid, _, _, by_year in series}
    if len(set(last.values())) > 1:
        report.lines.append("[RAGGED] oecd_dac: " + "; ".join(f"{sid} runs to {year}" for sid, year in last.items()))

    # Gross ODA and net minus grants are not derived here: the first would be an in-house model,
    # the second mixes two indicators of different scope
    records: List[Dict] = []
    for sid, _, file_hash, by_year in series:
        for yr in sorted(by_year):
            records.append({
                "date": yr,
                "series_id": sid,
                "value": by_year[yr],
                "unit": UNIT,
                "status_flag": "A",
                "realtime_start": REALTIME_START,
                "source_hash": file_hash,
            })

    df_out = pd.DataFrame(records)[CANONICAL_COLUMNS]
    df_out = df_out.sort_values(by=["date", "series_id"]).reset_index(drop=True)

    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_out = flags.assign_flags(df_out, "oecd_dac_annual")
    source_io.check_schema(df_out, raw_dir, "oecd_dac_annual")
    report.finish()
    return df_out


def main(
    output_dir: Optional[Path] = None,
    seeds_dir: Optional[Path] = None,
    raw_dir: Optional[Path] = None,
):
    print("=" * 60)
    print("Ingesting Family 9: Development Assistance (OECD DAC)")
    print("=" * 60)

    df = parse_oecd_dac(raw_dir)
    print(f"Parsed {len(df)} canonical observations across {df['series_id'].nunique()} series.")
    print(f"Years covered: {df['date'].min()} to {df['date'].max()} ({df['date'].nunique()} years).")

    garden_dir = output_dir if output_dir is not None else repo_root / "pipeline" / "data" / "garden"
    if seeds_dir is None:
        seeds_dir = repo_root / "pipeline" / "seeds"

    garden_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir.mkdir(parents=True, exist_ok=True)

    garden_parquet = garden_dir / "oecd_dac_annual.parquet"
    seed_parquet = seeds_dir / "oecd_dac_annual_seed.parquet"

    source_io.write_table(df, garden_parquet)
    print(f"Saved Garden dataset -> {garden_parquet}")

    source_io.write_table(df, seed_parquet)
    print(f"Saved Immutable Seed -> {seed_parquet}")

    print("\nSummary by Series:")
    piv = df.pivot(index="date", columns="series_id", values="value")
    for col in piv.columns:
        print(f"  {col}: {piv[col].count()} obs, Latest ({piv.index[-1]}): {piv[col].iloc[-1]:,.2f} {UNIT}")


if __name__ == "__main__":
    main()
