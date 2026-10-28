"""
pipeline.parsers.parse_oil_monthly
==================================
Parser for Family 3 (Oil) - Monthly Crude Oil Production & Basrah Crude Price.

Extracts 3 monthly series (2004-01 to present):
1. `crude_production_secondary`:
   - Monthly crude oil production based on secondary sources (TB_PER_D).
   - Sourced from U.S. EIA International Energy Database (`INTL.57-1-IRQ-TBPD.M`).
2. `crude_production_direct`:
   - Monthly crude oil production based on direct communication (TB_PER_D).
   - Sourced from JODI-Oil Database (`INDPROD` in KBD, 2007-01 to 2024-03) and
     OPEC MOMR Chapter 5 (Direct Communication, 2024-04+).
3. `oil_price_basrah`:
   - Basrah crude price (USD_PER_BBL): transcribed OPEC MOMR anchor months only. The
     other months are not modelled as Brent minus a fixed discount.

Quality & Schema Guarantees:
- Enforces Single-Frequency Rule: output contains purely monthly observations (YYYY-MM).
- Conforms to standard 7-column Canonical Observation Schema.
- Generates derived seed snapshot `pipeline/seeds/opec_momr_historical.parquet` (regenerated on every run; see pipeline/run_parsers.py).
- Generates garden dataset: `pipeline/data/garden/oil_monthly.parquet`.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import source_io  # noqa: E402
import transcription  # noqa: E402

REALTIME_START = "2026-10-28"
EIA_MEMBER = "INTL.txt"
EIA_MAX_LINE = 1_000_000  # bytes; the longest line of INTL.txt is about 40 KB
EIA_NO_VALUE = {"--", "NA"}  # EIA's "no value" texts (a JSON null is no value too)
JODI_NO_VALUE = {"-", ".."}  # JODI's "not available"; blank cells are no value too

# Typed-in values live in archived transcription records, not in this file:
# pipeline/raw/transcribed/opec_momr_crude_direct_<date>.csv  (direct communication, 2024-04 on)
# pipeline/raw/transcribed/opec_momr_basrah_anchors_<date>.csv (Basrah anchor months)
CRUDE_DIRECT_RECORD = "opec_momr_crude_direct_*.csv"
BASRAH_RECORD = "opec_momr_basrah_anchors_*.csv"


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def parse_oil_monthly(
    eia_zip_path: Optional[Path] = None,
    jodi_dir_path: Optional[Path] = None,
    transcribed_dir: Optional[Path] = None,
    seed_parquet_path: Optional[Path] = None,
    output_parquet_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Parses EIA secondary production, JODI direct production, and Basrah crude price,
    generating both pipeline/seeds/opec_momr_historical.parquet and
    pipeline/data/garden/oil_monthly.parquet.
    """
    if eia_zip_path is None:
        eia_zip_path = repo_root / "pipeline" / "raw" / "eia" / "INTL.zip"

    if jodi_dir_path is None:
        jodi_dir_path = repo_root / "pipeline" / "raw" / "jodi"

    if transcribed_dir is None:
        transcribed_dir = repo_root / "pipeline" / "raw" / "transcribed"

    if seed_parquet_path is None:
        seed_parquet_path = repo_root / "pipeline" / "seeds" / "opec_momr_historical.parquet"

    if output_parquet_path is None:
        output_parquet_path = repo_root / "pipeline" / "data" / "garden" / "oil_monthly.parquet"

    eia_hash = None
    observations: List[Dict] = []
    where: List[str] = []  # the file (and line) of each observation, for duplicate messages
    report = source_io.Report("oil_monthly")

    # 1. Ingest Crude Oil Production - Secondary Sources (EIA INTL.57-1-IRQ-TBPD.M); every value of the
    #    series must be a number or EIA's "no value"
    found = False
    with source_io.open_zip(eia_zip_path, EIA_MEMBER) as z:
        eia_hash = compute_file_hash(eia_zip_path)
        with z.open(EIA_MEMBER) as f:
            for n, line in enumerate(iter(lambda: f.readline(EIA_MAX_LINE + 1), b""), start=1):
                if len(line) > EIA_MAX_LINE:
                    raise source_io.ParseError(eia_zip_path, f"lines of at most {EIA_MAX_LINE} bytes",
                                               "a longer line", location=f"{EIA_MEMBER} line {n}")
                if b"INTL.57-1-IRQ-TBPD.M" in line:
                    found = True
                    try:
                        obj = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise source_io.ParseError(eia_zip_path, "a JSON line for INTL.57-1-IRQ-TBPD.M",
                                                   f"{type(exc).__name__}", location=f"{EIA_MEMBER} line {n}") from None
                    for dt_str, val in obj.get("data", []):
                        if len(dt_str) == 6 and dt_str >= "200401":
                            period = f"{dt_str[:4]}-{dt_str[4:]}"
                            value = source_io.read_value(val, report, eia_zip_path, markers=EIA_NO_VALUE,
                                                         location=f"{EIA_MEMBER} line {n}", period=period,
                                                         series_id="crude_production_secondary")
                            if value is None:
                                continue
                            observations.append({
                                "date": period,
                                "series_id": "crude_production_secondary",
                                "value": round(value, 1),
                                "unit": "TB_PER_D",
                                "status_flag": "A",
                                "realtime_start": REALTIME_START,
                                "source_hash": eia_hash,
                            })
                            where.append(f"{eia_zip_path.name} {EIA_MEMBER} line {n}")
                    break
    if not found:
        raise source_io.ParseError(eia_zip_path, "the series INTL.57-1-IRQ-TBPD.M", "no such line", location=EIA_MEMBER)

    # 2. Ingest Crude Oil Production - Direct Communication (JODI-Oil 2007-01..2024-03 + OPEC recent)
    jodi_files = sorted(jodi_dir_path.glob("jodi_iraq_*.csv"))
    if not jodi_files:
        raise FileNotFoundError(f"No JODI Iraq files found in: {jodi_dir_path}")

    jodi_rows = []
    for p in jodi_files:
        df_j = source_io.read_csv(p)
        for column in ("FLOW_BREAKDOWN", "UNIT_MEASURE", "ENERGY_PRODUCT", "TIME_PERIOD", "OBS_VALUE"):
            if column not in df_j.columns:
                raise source_io.ParseError(p, f"a {column} column", f"columns {list(df_j.columns)}")
        h = compute_file_hash(p)  # each row cites the file it was read from
        mask = (
            (df_j["FLOW_BREAKDOWN"] == "INDPROD") &
            (df_j["UNIT_MEASURE"] == "KBD") &
            (df_j["ENERGY_PRODUCT"] == "CRUDEOIL")
        )
        # A JODI value is a number, "-" or ".." (not available), or blank; anything else stops the run
        for i, r in df_j[mask].iterrows():
            period = str(r["TIME_PERIOD"]).strip()
            value = source_io.read_value(r["OBS_VALUE"], report, p, markers=JODI_NO_VALUE, location=f"row {i + 2}",
                                         period=period, series_id="crude_production_direct")
            if value is not None:
                jodi_rows.append((period, value, h, f"{p.name}, row {i + 2}"))

    for period, value, h, place in sorted(jodi_rows, key=lambda t: t[0]):
        v_num = round(value, 1)
        where.append(place)
        observations.append({
            "date": period,
            "series_id": "crude_production_direct",
            "value": v_num,
            "unit": "TB_PER_D",
            "status_flag": "A",
            "realtime_start": REALTIME_START,
            "source_hash": h,
        })

    # Direct communication after JODI (2024-04 on) and 3. the Basrah crude price, both transcribed
    # from OPEC MOMR. Basrah has only its anchor months: the other months are not modelled as the
    # Brent monthly mean minus a fixed discount
    units = {sid: flags.load_catalog()[sid]["unit"] for sid in ("crude_production_direct", "oil_price_basrah")}
    for pattern, sid in ((CRUDE_DIRECT_RECORD, "crude_production_direct"), (BASRAH_RECORD, "oil_price_basrah")):
        record_path = transcription.newest(transcribed_dir, pattern, sid)
        record = transcription.read_transcription(record_path, units, [sid])
        for r in record.itertuples(index=False):
            observations.append({
                "date": r.period,
                "series_id": r.series_id,
                "value": r.value,
                "unit": r.unit,
                "status_flag": "A",
                "realtime_start": REALTIME_START,
                "source_hash": r.source_hash,
            })
            where.append(record_path.name)

    df_out = pd.DataFrame(observations, columns=CANONICAL_COLUMNS)
    # JODI and the transcription record both give crude_production_direct: a month in both is
    # collapsed only when identical, and reported
    df_out = source_io.collapse_duplicates(df_out, jodi_dir_path, report, where=where)
    df_out = df_out.sort_values(by=["series_id", "date"]).reset_index(drop=True)

    # Tier-1 Validation
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_out = flags.assign_flags(df_out, "oil_monthly")
    source_io.check_schema(df_out, eia_zip_path, "oil_monthly")
    report.finish()

    # Save to immutable seed archive and garden layer
    source_io.write_table(df_out, seed_parquet_path)
    print(f"Successfully saved immutable seed {seed_parquet_path} ({len(df_out):,} observations).")

    source_io.write_table(df_out, output_parquet_path)
    print(f"Successfully saved garden dataset {output_parquet_path} ({len(df_out):,} observations across {df_out['series_id'].nunique()} series).")
    print(f"Time span: {df_out['date'].min()} to {df_out['date'].max()} ({df_out['date'].nunique()} months).")

    return df_out


if __name__ == "__main__":
    parse_oil_monthly()
