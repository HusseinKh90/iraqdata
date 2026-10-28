"""
pipeline.run_parsers
====================
Single entry point that runs all 11 parsers in a fixed, documented order.

    python pipeline/run_parsers.py [--output-dir DIR | --apply-to DIR] [--only NAME ...]
                                   [--raw-root DIR] [--seeds-root DIR] [--history-dir DIR]
                                   [--vintage YYYY-MM-DD] [--report PATH]
    python pipeline/run_parsers.py --recover [--apply-to DIR]

With --output-dir, garden tables are written to DIR/ and derived seed snapshots to DIR/seeds/,
and nothing else is touched (the sandbox used by the tests). Otherwise the runner builds in a
temporary folder and merges the result into DIR (default: production, pipeline/data/garden/): new periods are added, a revised value replaces the published one and the earlier
value is appended to the vintage history (pipeline/data/history/), and a table that did not
change is not rewritten. Vintage dates come from dated input names (`<stem>_YYYY-MM-DD.<ext>`),
else 2026-10-28 (the first release), unless --vintage is given.

Run order
---------
 1. bis_lbs
 2. cbi_bop
 3. cbi_cpi
 4. cbi_exchange_rates
 5. fiscal_seed          - overwrites fiscal_annual with the historical seed ...
 6. cbi_fiscal_bulletin  - ... then upserts the 2024-2025 outturns into it, so it must run after 5.
 7. cbi_money_banking
 8. cosit_gdp
 9. oecd_dac
10. oil_daily            - FRED daily Brent
11. oil_monthly          - EIA, JODI and the transcribed OPEC records; it does not read oil_daily
                           (the Basrah months are not modelled from Brent)

The four seed parquet files (bis_lbs_quarterly_seed, cosit_gdp_quarterly_seed,
oecd_dac_annual_seed, opec_momr_historical) are derived seed snapshots: they are regenerated
on every run and are not raw inputs.

The registry also records which archived files each parser reads (`inputs`, feeding the raw-file
manifest) and, per series and date, which file each published value was read from
(`series_inputs`, feeding the provenance attribution check in raw_audit.py).
"""

import argparse
import functools
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline" / "parsers"))
sys.path.insert(0, str(repo_root / "pipeline"))

import downloads  # noqa: E402  (latest_version, vintage_of)

DEFAULT_RAW_ROOT = repo_root / "pipeline" / "raw"
DEFAULT_SEEDS_ROOT = repo_root / "pipeline" / "seeds"
DEFAULT_OUT_DIR = repo_root / "pipeline" / "data" / "garden"

# series_inputs sentinel: the parser does not write this (series, date) row
NOT_WRITTEN = "not-written"

SeriesSource = Callable[[str], Union[List[str], str, None]]
RunFn = Callable[[Path, Path, Path, Path], None]


@dataclass(frozen=True)
class ParserSpec:
    name: str
    module: str
    run: RunFn
    inputs: Tuple[str, ...]
    outputs: Tuple[str, ...]
    seed_outputs: Tuple[str, ...] = ()
    after: Tuple[str, ...] = ()
    uses: Dict[str, str] = field(default_factory=dict)
    series_inputs: Dict[str, SeriesSource] = field(default_factory=dict)

    def use_of(self, glob: str) -> str:
        return self.uses.get(glob, "parsed")


def _const(path: Union[str, None]) -> SeriesSource:
    return lambda date: path


def _require(path: Optional[Path], what: str, expected: Path) -> Path:
    """Stop with a clear error instead of downloading when an archived input is missing."""
    if path is None or not path.exists():
        raise FileNotFoundError(
            f"{what} not found: expected {expected} or a dated download next to it. "
            "The runner never downloads; archive the file first."
        )
    return path


# =====================================================================
# CBI workbook selection (shared with the parsers' own defaults)
# =====================================================================

def _bulletin_input(raw_root: Path) -> Optional[Path]:
    import parse_cbi_fiscal_bulletin
    return parse_cbi_fiscal_bulletin.resolve_bulletin_input(raw_root / "cbi")


def _indicators_input(raw_root: Path) -> Optional[Path]:
    import parse_cbi_money_banking
    return parse_cbi_money_banking.resolve_indicators_input(raw_root / "cbi")


def _repo_rel(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    return unicodedata.normalize("NFC", path.resolve().relative_to(repo_root).as_posix())


@functools.lru_cache(maxsize=None)
def _cbi_choice(kind: str) -> Optional[str]:
    """Repository path of the CBI workbook the parsers would read now (cached; see clear_caches)."""
    chooser = _indicators_input if kind == "indicators" else _bulletin_input
    return _repo_rel(chooser(DEFAULT_RAW_ROOT))


def clear_caches() -> None:
    """Forget cached CBI workbook choices (call before an audit run)."""
    _cbi_choice.cache_clear()
    versions_of.cache_clear()


def _indicators_source(date: str) -> Optional[List[str]]:
    path = _cbi_choice("indicators")
    return [path] if path else None


def _bulletin_source(date: str) -> Union[List[str], str, None]:
    import parse_cbi_fiscal_bulletin
    if date < str(parse_cbi_fiscal_bulletin.FIRST_BULLETIN_YEAR):
        return NOT_WRITTEN
    path = _cbi_choice("bulletin")
    return [path] if path else None


# =====================================================================
# Run functions: (raw_root, seeds_root, out_dir, seeds_out_dir) -> None
# =====================================================================

def _run_bis_lbs(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_bis_lbs
    parse_bis_lbs.main(output_dir=out_dir, seeds_dir=seeds_out_dir, raw_dir=raw_root / "bis")


def _run_cbi_bop(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_cbi_bop
    parse_cbi_bop.parse_cbi_bop(
        bop_dir=raw_root / "cbi" / "bop",
        output_parquet_path=out_dir / "bop_trade_quarterly.parquet",
    )


def _run_cbi_cpi(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_cbi_cpi
    parse_cbi_cpi.parse_cbi_cpi(
        workbook_path=_require(_indicators_input(raw_root), "CBI Key Financial Indicators workbook",
                               raw_root / "cbi" / "key_financial_indicators.xlsx"),
        output_parquet_path=out_dir / "prices_monthly.parquet",
    )


def _run_cbi_exchange_rates(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_cbi_exchange_rates
    parse_cbi_exchange_rates.parse_cbi_exchange_rates(
        seed_path=seeds_root / "cbi_exchange_rate_historical.xlsx",
        cbi_workbook_path=downloads.latest_version(raw_root / "cbi" / "fx" / "cbi_fx_usd.xlsx"),
        daily_fx_path=downloads.latest_version(raw_root / "github" / "daily_fx.csv"),
        output_parquet_path=out_dir / "exchange_rates_daily.parquet",
    )


def _run_fiscal_seed(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_fiscal_seed
    parse_fiscal_seed.parse_fiscal_seed(
        seed_path=seeds_root / "iraq_fiscal_historical.xlsx",
        output_path=out_dir / "fiscal_annual.parquet",
    )


def _run_cbi_fiscal_bulletin(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_cbi_fiscal_bulletin
    parse_cbi_fiscal_bulletin.parse_cbi_fiscal_bulletin(
        bulletin_path=_require(_bulletin_input(raw_root), "CBI Monthly Statistical Bulletin",
                               raw_root / "cbi" / "bulletin_latest.xlsx"),
        garden_parquet_path=out_dir / "fiscal_annual.parquet",
    )


def _run_cbi_money_banking(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_cbi_money_banking
    parse_cbi_money_banking.parse_cbi_money_banking(
        workbook_path=_require(_indicators_input(raw_root), "CBI Key Financial Indicators workbook",
                               raw_root / "cbi" / "key_financial_indicators.xlsx"),
        output_parquet_path=out_dir / "money_banking_monthly.parquet",
    )


def _run_cosit_gdp(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_cosit_gdp
    parse_cosit_gdp.parse_cosit_gdp(
        raw_dir=raw_root / "transcribed",
        seed_parquet_path=seeds_out_dir / "cosit_gdp_quarterly_seed.parquet",
        output_parquet_path=out_dir / "gdp_quarterly.parquet",
    )


def _run_oecd_dac(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_oecd_dac
    parse_oecd_dac.main(output_dir=out_dir, seeds_dir=seeds_out_dir, raw_dir=raw_root / "oecd")


def _run_oil_daily(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_oil_daily
    parse_oil_daily.parse_oil_daily(
        raw_csv_path=downloads.latest_version(raw_root / "fred" / "DCOILBRENTEU.csv"),
        output_parquet_path=out_dir / "oil_daily.parquet",
    )


def _run_oil_monthly(raw_root, seeds_root, out_dir, seeds_out_dir):
    import parse_oil_monthly
    parse_oil_monthly.parse_oil_monthly(
        eia_zip_path=downloads.latest_version(raw_root / "eia" / "INTL.zip"),
        jodi_dir_path=raw_root / "jodi",
        transcribed_dir=raw_root / "transcribed",
        seed_parquet_path=seeds_out_dir / "opec_momr_historical.parquet",
        output_parquet_path=out_dir / "oil_monthly.parquet",
    )


# =====================================================================
# Per-series sources (where each published value was actually read from)
# =====================================================================

BIS = "pipeline/raw/bis"
OECD = "pipeline/raw/oecd"


def _bop_source(date: str) -> List[str]:
    year = date[:4]
    if "2013" <= year <= "2016":
        return ["pipeline/raw/cbi/bop/bop_2013_2016.xlsx"]
    return [f"pipeline/raw/cbi/bop/bop_{year}.xlsx"]


FX_SEED = "pipeline/seeds/cbi_exchange_rate_historical.xlsx"
CBI_FX_WORKBOOK = "pipeline/raw/cbi/fx/cbi_fx_usd.xlsx"
DAILY_FX = "pipeline/raw/github/daily_fx.csv"


def _parallel_rate_source(date: str) -> List[str]:
    return [FX_SEED] if date < "2023-01-01" else [DAILY_FX]


# Transcription records; the undated name stands for every dated version of it
GDP_RECORD = "pipeline/raw/transcribed/cosit_gdp_quarterly.csv"
CRUDE_DIRECT_RECORD = "pipeline/raw/transcribed/opec_momr_crude_direct.csv"
BASRAH_RECORD = "pipeline/raw/transcribed/opec_momr_basrah_anchors.csv"


def _jodi_source(date: str) -> Optional[List[str]]:
    # JODI covers 2007-01..2024-03; later months come from the OPEC MOMR transcription record
    if date <= "2024-03":
        return [f"pipeline/raw/jodi/jodi_iraq_{date[:4]}.csv"]
    return [CRUDE_DIRECT_RECORD]


KFI_GLOBS = (
    "pipeline/raw/cbi/key_financial_indicators.xlsx",
    "pipeline/raw/cbi/cbi_key_financial_indicators_*.xlsx",
)
BULLETIN_GLOBS = (
    "pipeline/raw/cbi/bulletin_latest.xlsx",
    "pipeline/raw/cbi/cbi_bulletin_*.xlsx",
)

REGISTRY: List[ParserSpec] = [
    ParserSpec(
        name="bis_lbs", module="parse_bis_lbs", run=_run_bis_lbs,
        inputs=(f"{BIS}/bis_lbs_*.csv",),
        outputs=("bis_lbs_quarterly.parquet",),
        seed_outputs=("bis_lbs_quarterly_seed.parquet",),
        series_inputs={
            "bis.lbs.claims_total": _const([f"{BIS}/bis_lbs_claims_total.csv"]),
            "bis.lbs.liabilities_total": _const([f"{BIS}/bis_lbs_liabilities_total.csv"]),
            "bis.lbs.liabilities_banks": _const([f"{BIS}/bis_lbs_liabilities_banks.csv"]),
            "bis.lbs.liabilities_nonbank": _const([f"{BIS}/bis_lbs_liabilities_nonbank.csv"]),
            "bis.lbs.claims_nonbank": _const([f"{BIS}/bis_lbs_claims_nonbank.csv"]),
            "bis.lbs.net_position": _const("bis_lbs_all"),
        },
    ),
    ParserSpec(
        name="cbi_bop", module="parse_cbi_bop", run=_run_cbi_bop,
        inputs=("pipeline/raw/cbi/bop/bop_*.xlsx",),
        outputs=("bop_trade_quarterly.parquet",),
        series_inputs={"*": _bop_source},
    ),
    ParserSpec(
        name="cbi_cpi", module="parse_cbi_cpi", run=_run_cbi_cpi,
        inputs=KFI_GLOBS,
        outputs=("prices_monthly.parquet",),
        series_inputs={"*": _indicators_source},
    ),
    ParserSpec(
        name="cbi_exchange_rates", module="parse_cbi_exchange_rates", run=_run_cbi_exchange_rates,
        inputs=(FX_SEED, "pipeline/raw/cbi/fx/cbi_fx_usd*.xlsx", "pipeline/raw/github/daily_fx*.csv"),
        outputs=("exchange_rates_daily.parquet",),
        series_inputs={
            # The seed to 2022, then the Baghdad close of daily_fx.csv
            "parallel_rate_iraq": _parallel_rate_source,
            # Either the CBI workbook, or the seed: rows to 2023-12-13 keep the seed hash they were
            # first published with (a tuple lists alternatives; raw_audit provenance)
            "fx.official": _const(([CBI_FX_WORKBOOK], [FX_SEED])),
        },
    ),
    ParserSpec(
        name="fiscal_seed", module="parse_fiscal_seed", run=_run_fiscal_seed,
        inputs=("pipeline/seeds/iraq_fiscal_historical.xlsx",),
        outputs=("fiscal_annual.parquet",),
        series_inputs={"*": _const(["pipeline/seeds/iraq_fiscal_historical.xlsx"])},
    ),
    ParserSpec(
        name="cbi_fiscal_bulletin", module="parse_cbi_fiscal_bulletin", run=_run_cbi_fiscal_bulletin,
        inputs=BULLETIN_GLOBS,
        outputs=("fiscal_annual.parquet",),
        after=("fiscal_seed",),
        series_inputs={"*": _bulletin_source},
    ),
    ParserSpec(
        name="cbi_money_banking", module="parse_cbi_money_banking", run=_run_cbi_money_banking,
        inputs=KFI_GLOBS,
        outputs=("money_banking_monthly.parquet",),
        series_inputs={"*": _indicators_source},
    ),
    ParserSpec(
        name="cosit_gdp", module="parse_cosit_gdp", run=_run_cosit_gdp,
        inputs=("pipeline/raw/transcribed/cosit_gdp_quarterly*.csv",),
        outputs=("gdp_quarterly.parquet",),
        seed_outputs=("cosit_gdp_quarterly_seed.parquet",),
        # Read from the transcription record; any dated version of it counts
        series_inputs={"*": _const([GDP_RECORD])},
    ),
    ParserSpec(
        name="oecd_dac", module="parse_oecd_dac", run=_run_oecd_dac,
        inputs=(f"{OECD}/wb_oda_*.json",),
        outputs=("oecd_dac_annual.parquet",),
        seed_outputs=("oecd_dac_annual_seed.parquet",),
        series_inputs={
            "oecd.dac.oda_total_net": _const([f"{OECD}/wb_oda_net.json"]),
            "oecd.dac.grants_excl_tc": _const([f"{OECD}/wb_oda_grants.json"]),
        },
    ),
    ParserSpec(
        name="oil_daily", module="parse_oil_daily", run=_run_oil_daily,
        inputs=("pipeline/raw/fred/DCOILBRENTEU*.csv",),
        outputs=("oil_daily.parquet",),
        series_inputs={"*": _const(["pipeline/raw/fred/DCOILBRENTEU.csv"])},
    ),
    ParserSpec(
        name="oil_monthly", module="parse_oil_monthly", run=_run_oil_monthly,
        inputs=("pipeline/raw/eia/INTL*.zip", "pipeline/raw/jodi/jodi_iraq_*.csv",
                "pipeline/raw/transcribed/opec_momr_*.csv"),
        outputs=("oil_monthly.parquet",),
        seed_outputs=("opec_momr_historical.parquet",),
        series_inputs={
            "crude_production_secondary": _const(["pipeline/raw/eia/INTL.zip"]),
            "crude_production_direct": _jodi_source,
            # Transcribed OPEC MOMR anchor months only; the modelled months were withdrawn
            "oil_price_basrah": _const([BASRAH_RECORD]),
        },
    ),
]

BY_NAME: Dict[str, ParserSpec] = {spec.name: spec for spec in REGISTRY}

# Seed snapshot -> garden table it mirrors
SNAPSHOT_TABLE = {
    "bis_lbs_quarterly_seed": "bis_lbs_quarterly",
    "cosit_gdp_quarterly_seed": "gdp_quarterly",
    "oecd_dac_annual_seed": "oecd_dac_annual",
    "opec_momr_historical": "oil_monthly",
}


# =====================================================================
# Queries used by raw_audit.py
# =====================================================================

def consumer_map() -> Dict[str, List[Tuple[str, str]]]:
    """Map each archived file (NFC, repository-relative) to the parsers that read it."""
    consumers: Dict[str, List[Tuple[str, str]]] = {}
    for spec in REGISTRY:
        for glob in spec.inputs:
            for path in sorted(repo_root.glob(glob)):
                if not path.is_file():
                    continue
                key = _repo_rel(path)
                entry = (spec.name, spec.use_of(glob))
                if entry not in consumers.setdefault(key, []):
                    consumers[key].append(entry)
    return consumers


@functools.lru_cache(maxsize=None)
def versions_of(path: str) -> frozenset:
    """
    Every archived version of an expected input: the file itself plus its
    dated re-downloads. After an update, unchanged rows keep the fingerprint of the older version,
    so provenance accepts any member of the family. The CBI workbooks form one family each,
    whatever their (legacy or dated) names.
    """
    for globs in (KFI_GLOBS, BULLETIN_GLOBS):
        if any(PurePosixPath(path).match(g) for g in globs):
            return frozenset({path} | {_repo_rel(p) for g in globs for p in repo_root.glob(g) if p.is_file()})
    base = repo_root / path
    siblings = {_repo_rel(p) for p in base.parent.glob(f"{base.stem}_*{base.suffix}")
                if p.is_file() and downloads.vintage_of(p) and p.stem.rsplit("_", 1)[0] == base.stem}
    return frozenset({path} | siblings)


def writers_of(table: str) -> List[ParserSpec]:
    """Parsers that write `<table>.parquet`, in run order."""
    return [spec for spec in REGISTRY if f"{table}.parquet" in spec.outputs]


def expected_inputs(table: str, series_id: str, date: str) -> Union[List[str], str, None]:
    """
    The file(s) or input group a published (table, series, date) value was read from, or None
    when it was not read from any archived file. The last writer in run order wins, matching
    the fiscal upsert. Raises KeyError if no parser declares the series.
    """
    found = False
    expected: Union[List[str], str, None] = None
    for spec in writers_of(table):
        source = spec.series_inputs.get(series_id, spec.series_inputs.get("*"))
        if source is None:
            continue
        value = source(date)
        if value == NOT_WRITTEN:
            continue
        found = True
        expected = value
    if not found:
        raise KeyError(f"No parser declares series {series_id!r} ({date}) in table {table!r}")
    return expected


# =====================================================================
# Runner
# =====================================================================

def run_all(
    out_dir: Optional[Path] = None,
    only: Optional[Sequence[str]] = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    seeds_root: Path = DEFAULT_SEEDS_ROOT,
    apply_to: Optional[Path] = None,
    history_dir: Optional[Path] = None,
    vintage: Optional[str] = None,
    _fresh_hook: Optional[Callable] = None,
    withdraw: Optional[Dict[str, str]] = None,
    keep: Optional[Sequence[Tuple[str, str]]] = None,
    allow_missing: Optional[bool] = None,
):
    """
    Run the selected parsers in registry order.

    - With `out_dir`: a fresh build written to `out_dir` (seed snapshots to `out_dir/seeds`), no
      merge (the sandbox the tests use). Returns {parser name: [written paths]}.
    - Otherwise: build into a temporary folder and merge each table into `apply_to`
      (default: production) with vintages.merge_vintages, appending superseded rows to the
      vintage history. Returns the merge report (see merge_into).
    """
    if out_dir is not None and apply_to is not None:
        raise ValueError("--output-dir and --apply-to are mutually exclusive")
    if out_dir is None:
        return merge_into(apply_to if apply_to is not None else DEFAULT_OUT_DIR, only=only,
                          raw_root=raw_root, seeds_root=seeds_root, history_dir=history_dir,
                          vintage=vintage, _fresh_hook=_fresh_hook, withdraw=withdraw, keep=keep,
                          allow_missing=allow_missing)
    if withdraw or keep or allow_missing:
        raise ValueError("--withdraw-missing, --keep-missing and --allow-missing apply to a merge, not to --output-dir")
    out_dir = Path(out_dir)
    return build(out_dir, out_dir / "seeds", only, raw_root, seeds_root)


def build(
    out_dir: Path,
    seeds_out_dir: Path,
    only: Optional[Sequence[str]] = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    seeds_root: Path = DEFAULT_SEEDS_ROOT,
) -> Dict[str, List[Path]]:
    """Fresh build of the selected parsers into `out_dir`. Returns {parser name: [written paths]}."""
    out_dir, seeds_out_dir = Path(out_dir), Path(seeds_out_dir)
    raw_root, seeds_root = Path(raw_root), Path(seeds_root)

    if only is not None:
        unknown = sorted(set(only) - set(BY_NAME))
        if unknown:
            raise ValueError(f"Unknown parser name(s): {unknown}. Known: {list(BY_NAME)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    seeds_out_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, List[Path]] = {}
    for spec in REGISTRY:
        if only is not None and spec.name not in only:
            continue
        if only is not None:
            for dep in spec.after:
                if dep in only:
                    continue
                for name in BY_NAME[dep].outputs:
                    if not (out_dir / name).exists():
                        raise RuntimeError(
                            f"{spec.name} needs {out_dir / name} from {dep}; "
                            f"run {dep} first or add it to --only."
                        )
        print(f"--- [{spec.name}] ---")
        try:
            spec.run(raw_root, seeds_root, out_dir, seeds_out_dir)
        except Exception as exc:
            exc.parser = spec.name  # lets the update check name the parser that failed
            raise
        written[spec.name] = [out_dir / n for n in spec.outputs] + [seeds_out_dir / n for n in spec.seed_outputs]
    return written


# =====================================================================
# Merging a build into published tables
# =====================================================================

BASELINE_VINTAGE = "2026-10-28"  # every file archived before the first release carries this vintage
DEFAULT_HISTORY_DIR = repo_root / "pipeline" / "data" / "history"
KEPT_MISSING_PATH = repo_root / "pipeline" / "metadata" / "kept_missing.yaml"


def load_kept_missing(path: Optional[Path] = None) -> List[dict]:
    """
    Published rows deliberately kept although a new release lacks them:
    table, series_id, date, reason, reviewer, date_decided. Raises ValueError naming a bad entry.
    """
    import yaml
    path = KEPT_MISSING_PATH if path is None else path
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = data.get("kept") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"Invalid {Path(path).name}: 'kept' must be a list")
    for i, e in enumerate(entries):
        where = f"kept-missing entry #{i}"
        if not isinstance(e, dict):
            raise ValueError(f"Invalid {where}: must be a dictionary")
        for req in ("table", "series_id", "date", "reason", "reviewer", "date_decided"):
            if req not in e or e[req] in (None, ""):
                raise ValueError(f"Invalid {where} ({e.get('series_id')} {e.get('date')}): missing or empty {req!r}")
        if downloads.vintage_of(Path(f"x_{e['date_decided']}.x")) is None:
            raise ValueError(f"Invalid {where}: date_decided {e['date_decided']!r} must be YYYY-MM-DD")
    return entries


def expand_only(only: Optional[Sequence[str]]) -> List[str]:
    """
    The selected parsers plus every parser writing the same tables and every `after` dependency,
    repeated until nothing is added, in registry order. A temporary build then never holds a
    partial table (e.g. oil_monthly brings oil_daily; cbi_fiscal_bulletin brings fiscal_seed).
    """
    if only is None:
        return [spec.name for spec in REGISTRY]
    unknown = sorted(set(only) - set(BY_NAME))
    if unknown:
        raise ValueError(f"Unknown parser name(s): {unknown}. Known: {list(BY_NAME)}")
    names = set(only)
    while True:
        more = set(names)
        for name in names:
            spec = BY_NAME[name]
            more.update(spec.after)
            for output in spec.outputs:
                more.update(w.name for w in writers_of(output[: -len(".parquet")]))
        if more == names:
            break
        names = more
    return [spec.name for spec in REGISTRY if spec.name in names]


def _local(glob: str, raw_root: Path, seeds_root: Path) -> Tuple[Path, str]:
    for prefix, root in (("pipeline/raw/", raw_root), ("pipeline/seeds/", seeds_root)):
        if glob.startswith(prefix):
            return Path(root), glob[len(prefix):]
    return repo_root, glob


def input_vintage(names: Sequence[str], raw_root: Path = DEFAULT_RAW_ROOT,
                  seeds_root: Path = DEFAULT_SEEDS_ROOT) -> str:
    """
    Newest acquisition date among the files matching the parsers' input globs (a dated name
    `<stem>_YYYY-MM-DD.<ext>`); the newest dated file is always the one a parser reads.
    Undated files give the baseline 2026-10-28. Backfilling a file older than one already
    archived needs an explicit --vintage.
    """
    dates = [BASELINE_VINTAGE]
    for name in names:
        for glob in BY_NAME[name].inputs:
            root, pattern = _local(glob, Path(raw_root), Path(seeds_root))
            dates += [d for p in root.glob(pattern) if (d := downloads.vintage_of(p))]
    return max(dates)


class MissingRowsError(ValueError):
    """Published rows are missing from the new release and were neither withdrawn nor kept."""


def _check_missing(results: dict, keep: Sequence[Tuple[str, str]], refuse: bool) -> List[List[str]]:
    """
    The kept rows ([table, series_id, date]) of a merge. Raises MissingRowsError, before anything
    is written, when `refuse` and a missing row is not kept, or when a kept row has no
    kept_missing.yaml entry.
    """
    keep = {(str(s), str(d)) for s, d in keep}
    listed = {(e["table"], e["series_id"], str(e["date"])) for e in load_kept_missing()} if keep else set()
    kept, uncovered = [], {}
    for table, res in results.items():
        for sid, date in res.missing:
            if (sid, date) in keep:
                if (table, sid, date) not in listed:
                    raise MissingRowsError(
                        f"--keep-missing {sid}:{date}: list it in pipeline/metadata/kept_missing.yaml "
                        f"(table {table}) with a reason first")
                kept.append([table, sid, date])
            else:
                uncovered.setdefault(table, []).append(f"{sid} {date}")
    unused = keep - {(s, d) for _, s, d in kept}
    if unused:
        raise MissingRowsError(f"--keep-missing names rows that are not missing: {sorted(unused)}")
    if refuse and uncovered:
        lines = []
        for table, keys in uncovered.items():
            shown = ", ".join(keys[:10]) + (f", and {len(keys) - 10} more" if len(keys) > 10 else "")
            lines.append(f"{len(keys)} row(s) are missing from the new release of {table}:\n  {shown}")
        raise MissingRowsError("\n".join(lines) + "\nwithdraw them (--withdraw-missing) or keep them "
                               "(--keep-missing, with a reason in kept_missing.yaml)")
    return kept


def merge_into(
    apply_to: Path,
    only: Optional[Sequence[str]] = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    seeds_root: Path = DEFAULT_SEEDS_ROOT,
    history_dir: Optional[Path] = None,
    vintage: Optional[str] = None,
    _fresh_hook: Optional[Callable] = None,
    withdraw: Optional[Dict[str, str]] = None,
    keep: Optional[Sequence[Tuple[str, str]]] = None,
    allow_missing: Optional[bool] = None,
) -> dict:
    """
    Build the selected parsers (expanded by expand_only) in a temporary folder, then merge each
    output table into `apply_to`:

    - a table is rewritten only when a period was added, a value revised or a status flag
      updated in place; on today's archive nothing is written;
    - superseded rows are appended to `<history_dir>/<table>.parquet` (a flag-only update
      supersedes nothing);
    - each derived seed snapshot is rewritten as a copy of its table when that table changed.

    Every merge and every history is computed and checked before anything is written, so a
    refused merge (a revision whose vintage is not later than the published one, or a repeated
    history key) leaves all files untouched. The files are then written as one merge_txn
    transaction, histories first: an error rolls it back, and a crash leaves a journal
    that `--recover` resolves; a merge refuses to start while that journal exists.
    `_fresh_hook(table, df) -> df` lets tests edit a fresh table before the merge.
    `withdraw` ({series_id: first_date}) withdraws published rows of those series from
    that date that the build no longer produces; they go to the history. One-time, explicit use only.
    Any other published row the build no longer produces must be kept
    explicitly (`keep`, [(series_id, date)], each listed in kept_missing.yaml with a reason) when
    missing rows are refused: in production by default, or when `allow_missing` is False. A
    scratch merge reports them; `allow_missing=True` is refused for production.
    """
    import tempfile

    import pandas as pd
    import merge_txn
    import vintages

    apply_to = Path(apply_to)
    if (apply_to / merge_txn.JOURNAL).exists():
        raise merge_txn.MergeInterrupted(
            f"An interrupted merge left {apply_to / merge_txn.JOURNAL}; "
            "run `python pipeline/run_parsers.py --recover` first.")
    production = apply_to.resolve() == DEFAULT_OUT_DIR.resolve()
    seeds_dir = DEFAULT_SEEDS_ROOT if production else apply_to.parent / "seeds"
    if history_dir is None:
        history_dir = DEFAULT_HISTORY_DIR if production else apply_to.parent / "history"
    history_dir = Path(history_dir)
    if production and allow_missing:
        raise MissingRowsError("--allow-missing is for scratch merges; a production merge must withdraw "
                               "(--withdraw-missing) or keep (--keep-missing) every missing row")
    names = expand_only(only)
    vintage = vintage or input_vintage(names, raw_root, seeds_root)
    if production:
        print(f"Merging into production data in {apply_to} (vintage {vintage}).")

    tables = list(dict.fromkeys(o[: -len(".parquet")] for n in names for o in BY_NAME[n].outputs))
    snapshots = list(dict.fromkeys(s[: -len(".parquet")] for n in names for s in BY_NAME[n].seed_outputs))

    import raw_audit  # deferred: raw_audit imports this module

    # Provenance corrections authorise hash-only revisions
    corrections = raw_audit.load_corrections()
    results = {}
    with tempfile.TemporaryDirectory(prefix="iraqdata_build_") as tmp:
        build(Path(tmp) / "garden", Path(tmp) / "seeds", names, raw_root, seeds_root)
        for table in tables:
            fresh = pd.read_parquet(Path(tmp) / "garden" / f"{table}.parquet")
            if _fresh_hook is not None:
                fresh = _fresh_hook(table, fresh)
            target = apply_to / f"{table}.parquet"
            previous = pd.read_parquet(target) if target.exists() else None
            results[table] = vintages.merge_vintages(previous, fresh, vintage, table, complete_from=withdraw,
                                                       corrections=corrections)

    # Published rows missing from the new release must be withdrawn or kept
    # explicitly in a production merge; a scratch merge (the update check) only reports them
    kept_rows = _check_missing(results, keep or [], production if allow_missing is None else not allow_missing)

    # Every history is built and checked before anything is written, then all files
    # are written as one transaction, histories first
    txn = merge_txn.Transaction(apply_to, vintage)
    for table, res in results.items():
        if not res.changed:
            continue
        history = vintages.prepare_history(history_dir / f"{table}.parquet", res.superseded)
        if history is not None:
            txn.add("history", history_dir / f"{table}.parquet", history)
        txn.add("table", apply_to / f"{table}.parquet", res.table)
        for snap in snapshots:
            if SNAPSHOT_TABLE.get(snap) == table:
                txn.add("snapshot", seeds_dir / f"{snap}.parquet", res.table)
    files = txn.commit()

    return {
        "vintage": vintage,
        "transaction": {"files": files},
        "kept_missing": kept_rows,
        "parsers": names,
        "tables": {
            table: {
                "changed": res.changed,
                "added": [list(k) for k in res.added],
                "revised": res.revised,
                "missing": [list(k) for k in res.missing],
                "withdrawn": [list(k) for k in res.withdrawn],
                "flag_updated": res.flag_updated,
            }
            for table, res in results.items()
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run all iraqdata parsers in the documented order.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output-dir", type=Path, default=None,
                      help="Fresh build: write garden tables here and seed snapshots to <dir>/seeds/ (no merge).")
    mode.add_argument("--apply-to", type=Path, default=None,
                      help="Merge the build into the tables in this folder (default: production garden).")
    parser.add_argument("--only", nargs="+", choices=list(BY_NAME), default=None,
                        help="Run only these parsers (registry order; a merge also runs the parsers that "
                             "share their tables and those they depend on).")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT, help="Folder of raw inputs.")
    parser.add_argument("--seeds-root", type=Path, default=DEFAULT_SEEDS_ROOT, help="Folder of seed inputs.")
    parser.add_argument("--history-dir", type=Path, default=None,
                        help="Vintage history folder (default: pipeline/data/history, or <apply-to>/../history).")
    parser.add_argument("--vintage", default=None, metavar="YYYY-MM-DD",
                        help="Vintage of this update. Needed for seed or typed-in sources, and when "
                             "backfilling a file older than the newest dated file already archived.")
    parser.add_argument("--report", type=Path, default=None, help="Write the merge report as JSON here.")
    parser.add_argument("--withdraw-missing", action="append", default=[], metavar="SERIES:YYYY-MM-DD",
                        help="One-time use: withdraw published rows of SERIES from this date that "
                             "the build no longer produces; they move to the vintage history.")
    parser.add_argument("--keep-missing", action="append", default=[], metavar="SERIES:DATE",
                        help="Keep a published row the new release no longer contains; it must be "
                             "listed with a reason in pipeline/metadata/kept_missing.yaml. DATE as published.")
    parser.add_argument("--allow-missing", action="store_true",
                        help="Report missing rows instead of refusing (scratch merges only; refused for production).")
    parser.add_argument("--recover", action="store_true",
                        help="Finish or undo a merge into --apply-to (default: production) that was interrupted, "
                             "then exit.")
    args = parser.parse_args(argv)
    import merge_txn
    if args.recover:
        if args.output_dir is not None:
            parser.error("--recover applies to a merge (--apply-to), not to --output-dir")
        try:
            outcome = merge_txn.recover(args.apply_to if args.apply_to is not None else DEFAULT_OUT_DIR)
        except merge_txn.RecoveryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3
        print(f"Recovery: {outcome}.")
        return 0
    withdraw = {}
    for item in args.withdraw_missing:
        series, _, first = item.partition(":")
        if not series or downloads.vintage_of(Path(f"x_{first}.x")) is None:
            parser.error(f"--withdraw-missing takes SERIES:YYYY-MM-DD, not {item!r}")
        withdraw[series] = first
    keep = []
    for item in args.keep_missing:
        series, _, date = item.partition(":")
        if not series or not date:
            parser.error(f"--keep-missing takes SERIES:DATE, not {item!r}")
        keep.append((series, date))
    if args.vintage is not None and downloads.vintage_of(Path(f"x_{args.vintage}.x")) is None:
        parser.error(f"--vintage must be a real date in YYYY-MM-DD form, not {args.vintage!r}")

    try:
        result = run_all(out_dir=args.output_dir, only=args.only, raw_root=args.raw_root,
                         seeds_root=args.seeds_root, apply_to=args.apply_to,
                         history_dir=args.history_dir, vintage=args.vintage, withdraw=withdraw or None,
                         keep=keep or None, allow_missing=True if args.allow_missing else None)
    except (merge_txn.MergeInterrupted, MissingRowsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.output_dir is not None:
        print(f"Done: {len(result)} parser(s) run.")
        return 0
    for table, info in result["tables"].items():
        note = "" if info["changed"] else " (unchanged, not rewritten)"
        print(f"[MERGE] {table}: {len(info['added'])} added, {len(info['revised'])} revised, "
              f"{len(info['flag_updated'])} flag update(s), {len(info['withdrawn'])} withdrawn, "
              f"{len(info['missing'])} missing{note}")
    if args.report is not None:
        import json
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Done: {len(result['parsers'])} parser(s) run, vintage {result['vintage']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
