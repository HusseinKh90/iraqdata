"""
pipeline.parsers.parse_cosit_gdp
================================
Parser for Family 7 (Output / National Accounts - GDP) from the
Central Organization for Statistics and Information Technology (COSIT)
and Central Bank of Iraq (CBI) Economic Indicators.

Builds 6 quarterly series across continuous quarters (2015-Q1 to 2026-Q1 in the current record) from
the archived transcription record pipeline/raw/transcribed/cosit_gdp_quarterly_<date>.csv (values typed
in from COSIT publications; status flag U). Most rows from 2020-Q1 cite an archived workbook
cell or PDF page, which pipeline/check_cosit_record.py reads back; GDP is the line COSIT labels GDP
(after the imputed bank service charge):
1. `gdp.nominal`: Headline GDP at Current Basic Prices (MILLION_IQD)
2. `gdp.nominal_oil`: Crude Oil GDP at Current Basic Prices (MILLION_IQD)
3. `gdp.nominal_nonoil`: Non-Oil GDP at Current Basic Prices (MILLION_IQD)
4. `gdp.real`: Headline Real GDP at Constant 2007 Basic Prices (MILLION_IQD)
5. `gdp.real_oil`: Real Crude Oil GDP at Constant 2007 Basic Prices (MILLION_IQD)
6. `gdp.real_nonoil`: Real Non-Oil GDP at Constant 2007 Basic Prices (MILLION_IQD)

Quality & Accounting Guarantees:
- Enforces Single-Frequency Rule: output contains purely quarterly observations (YYYY-Qn).
- The non-oil series are derived here as total minus oil, so "total == oil + non-oil" holds by
  construction (within rounding to 0.1); the check below guards that derivation, it is not evidence
  about the source. The gatekeeper reports the identity as definitional for the same reason.
- Conforms to standard 7-column Canonical Observation Schema.
- Generates derived seed snapshot `pipeline/seeds/cosit_gdp_quarterly_seed.parquet` (regenerated on every run; see pipeline/run_parsers.py).
- Generates garden dataset: `pipeline/data/garden/gdp_quarterly.parquet`.
"""

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

UNIT = "MILLION_IQD"
REALTIME_START = "2026-10-28"

# The quarterly totals and oil components were typed in from COSIT national accounts; they live in
# the archived transcription record pipeline/raw/transcribed/cosit_gdp_quarterly_<date>.csv, not
# in this file. The non-oil series are derived here as total minus oil. Where the
# source prints non-oil GDP (the early-warning reports), the record's oil value is total minus that.
GDP_RECORD = "cosit_gdp_quarterly_*.csv"
RECORD_SERIES = ("gdp.real", "gdp.real_oil", "gdp.nominal", "gdp.nominal_oil")


def parse_cosit_gdp(
    raw_dir: Optional[Path] = None,
    seed_parquet_path: Optional[Path] = None,
    output_parquet_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Builds the 6 canonical GDP quarterly series, enforces accounting identities,
    and writes both seed and garden Parquet datasets.
    """
    if raw_dir is None:
        raw_dir = repo_root / "pipeline" / "raw" / "transcribed"

    if seed_parquet_path is None:
        seed_parquet_path = repo_root / "pipeline" / "seeds" / "cosit_gdp_quarterly_seed.parquet"

    if output_parquet_path is None:
        output_parquet_path = repo_root / "pipeline" / "data" / "garden" / "gdp_quarterly.parquet"

    if not raw_dir.exists():
        raise FileNotFoundError(f"COSIT transcription folder not found: {raw_dir}")
    units = {sid: UNIT for sid in RECORD_SERIES}
    record_path = source_io.require_file(transcription.newest(raw_dir, GDP_RECORD, "gdp.nominal"))
    record = transcription.read_transcription(record_path, units)
    source_hash = record["source_hash"].iloc[0]
    wide = record.pivot(index="period", columns="series_id", values="value")
    missing = wide[wide.isna().any(axis=1)].index.tolist()
    if missing or set(wide.columns) != set(RECORD_SERIES):
        raise ValueError(f"GDP record must give {RECORD_SERIES} for every quarter; incomplete: {missing}")
    observations: List[Dict] = []

    for quarter, (real_tot, real_oil, nom_tot, nom_oil) in sorted(
            (q, tuple(r[s] for s in RECORD_SERIES)) for q, r in wide.iterrows()):
        # Round components to 1 decimal place
        real_tot = round(float(real_tot), 1)
        real_oil = round(float(real_oil), 1)
        real_nonoil = round(real_tot - real_oil, 1)

        nom_tot = round(float(nom_tot), 1)
        nom_oil = round(float(nom_oil), 1)
        nom_nonoil = round(nom_tot - nom_oil, 1)

        flag = "A"

        records = [
            ("gdp.nominal", nom_tot),
            ("gdp.nominal_oil", nom_oil),
            ("gdp.nominal_nonoil", nom_nonoil),
            ("gdp.real", real_tot),
            ("gdp.real_oil", real_oil),
            ("gdp.real_nonoil", real_nonoil),
        ]

        for sid, val in records:
            observations.append({
                "date": quarter,
                "series_id": sid,
                "value": val,
                "unit": UNIT,
                "status_flag": flag,
                "realtime_start": REALTIME_START,
                "source_hash": source_hash,
            })

    df_out = pd.DataFrame(observations, columns=CANONICAL_COLUMNS)
    df_out = df_out.sort_values(by=["series_id", "date"]).reset_index(drop=True)

    # 1. Tier-1 Validation
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_out = flags.assign_flags(df_out, "gdp_quarterly")
    source_io.check_schema(df_out, record_path, "gdp_quarterly")

    # 2. Arithmetic of the derivation: oil + non-oil = total (non-oil is total minus oil, so this holds
    #    by construction), checked in every interpreter mode (not with asserts, which
    #    python -O removes)
    piv = df_out.pivot(index="date", columns="series_id", values="value")
    for kind in ("real", "nominal"):
        diff = (piv[f"gdp.{kind}_oil"] + piv[f"gdp.{kind}_nonoil"]) - piv[f"gdp.{kind}"]
        bad = diff[diff.abs() >= 0.1]
        if len(bad):
            raise source_io.ParseError(record_path, f"gdp.{kind} = oil + non-oil (within 0.1)",
                                       ", ".join(f"a difference of {d:.1f}" for d in bad), period=", ".join(bad.index))

    # Save to seed archive and garden layer
    source_io.write_table(df_out, seed_parquet_path)
    print(f"Successfully saved immutable seed {seed_parquet_path} ({len(df_out):,} observations).")

    source_io.write_table(df_out, output_parquet_path)
    print(f"Successfully saved garden dataset {output_parquet_path} ({len(df_out):,} observations across {df_out['series_id'].nunique()} series).")
    print(f"Time span: {df_out['date'].min()} to {df_out['date'].max()} ({df_out['date'].nunique()} quarters).")

    return df_out


if __name__ == "__main__":
    parse_cosit_gdp()
