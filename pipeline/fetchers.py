"""
pipeline.fetchers
=================
One fetcher per automatically fetchable source. Used only by
`pipeline/update_check.py`; parsers and `run_parsers.py` never import this module, so building
data never touches the network.

Every fetcher has the signature

    fetch(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]

It downloads the source's current release through `downloads.polite_get` (robots.txt, pacing,
project User-Agent, verified TLS) and saves it under `raw_root` with a dated name
(`<stem>_<today>.<ext>`, or the CBI downloaders' own names) only when the bytes differ from the
newest version already there. It returns the new files, or None when nothing changed. Errors
propagate; the caller reports them per source.

`manifest_path` is the raw-file manifest the CBI downloaders append to; the update check passes
a throwaway copy, never the committed manifest.

Every download is retried on transient failures and capped in size
(downloads.polite_get), and checked before it is saved (pipeline/download_checks.py): its format,
and for CSV and JSON sources that it does not shrink the archived history. A failed check saves
nothing and is reported as fetch_failed. Each fetcher was run against its live site by
pipeline/verify_fetchers.py; the dated results are in pipeline/metadata/fetcher_verification.yaml.
"""

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import download_checks
import downloads

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
# EIA bulk download of the International Energy Statistics (see https://www.eia.gov/opendata/bulkfiles.php)
EIA_URL = "https://api.eia.gov/bulk/INTL.zip"
WB_URL = "https://api.worldbank.org/v2/country/IRQ/indicator/{indicator}?format=json&per_page=100"
# BIS SDMX REST API; the series key is rebuilt from the dimension columns of the archived CSV
BIS_URL = "https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/{key}?format=csv"
BIS_KEY_COLUMNS = ["FREQ", "L_MEASURE", "L_POSITION", "L_INSTR", "L_DENOM", "L_CURR_TYPE", "L_PARENT_CTY",
                   "L_REP_BANK_TYPE", "L_REP_CTY", "L_CP_SECTOR", "L_CP_COUNTRY", "L_POS_TYPE"]
BIS_FILES = ["bis_lbs_claims_total.csv", "bis_lbs_liabilities_total.csv", "bis_lbs_liabilities_banks.csv",
             "bis_lbs_liabilities_nonbank.csv", "bis_lbs_claims_nonbank.csv"]
WB_FILES = ["wb_oda_net.json", "wb_oda_grants.json"]
# The catalog series each World Bank file feeds; its source_indicator is the indicator fetched
WB_SERIES = {"wb_oda_net.json": "oecd.dac.oda_total_net", "wb_oda_grants.json": "oecd.dac.grants_excl_tc"}
# The largest response each download may be, about 5-20x today's archived size
MAX_BYTES = {"fred_brent": 5_000_000, "bis_lbs": 2_000_000, "wb_oda": 2_000_000, "github_fx": 10_000_000,
             "eia_intl": 200_000_000}
CBI_BOP_PAGE = "https://cbi.iq/page/145"
# The two exchange-rate sources
GITHUB_FX_URL = "https://raw.githubusercontent.com/HusseinKh90/Iraq-parallel-exchange-rate/master/data/daily_fx.csv"
CBI_FX_PAGE = "https://cbi.iq/page/144"

# The hosts each fetcher may contact. update_check restricts a fetch, and every redirect it meets,
# to its source's hosts (downloads.restrict_hosts); a new host here needs the source checked first.
HOSTS: Dict[str, List[str]] = {
    "bis_lbs": ["https://stats.bis.org/"],
    "cbi_bop": ["https://cbi.iq/"],
    "cbi_kfi": ["https://cbi.iq/"],
    "cbi_bulletin": ["https://cbi.iq/"],
    "wb_oda": ["https://api.worldbank.org/"],
    "fred_brent": ["https://fred.stlouisfed.org/"],
    "eia_intl": ["https://api.eia.gov/", "https://www.eia.gov/"],  # api.eia.gov/bulk/INTL.zip redirects to www.eia.gov
    "cbi_fx": ["https://cbi.iq/"],
    "github_fx": ["https://raw.githubusercontent.com/"],
}

Fetcher = Callable[[Path, date, Path], Optional[List[Path]]]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dated(base: Path, today: date) -> Path:
    return base.with_name(f"{base.stem}_{today.isoformat()}{base.suffix}")


def _save_if_new(base: Path, content: bytes, today: date) -> Optional[Path]:
    """Save `content` as `<base stem>_<today>` unless it equals the newest archived version."""
    newest = downloads.latest_version(base)
    if newest.exists() and _sha(newest.read_bytes()) == _sha(content):
        return None
    return downloads.save_new_file(_dated(base, today), content)


def _get(url: str, timeout: float = 60, max_bytes: int = downloads.WORKBOOK_MAX_BYTES) -> bytes:
    resp = downloads.polite_get(url, timeout=timeout, max_bytes=max_bytes)
    resp.raise_for_status()
    return resp.content


def _collect(paths: List[Optional[Path]]) -> Optional[List[Path]]:
    saved = [p for p in paths if p is not None]
    return saved or None


# ===================================================================== API and file sources


def fetch_fred_brent(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    base = raw_root / "fred" / "DCOILBRENTEU.csv"
    content = _get(FRED_URL, max_bytes=MAX_BYTES["fred_brent"])
    download_checks.check_fred_csv(content, FRED_URL)
    download_checks.check_not_shrunk(content, downloads.latest_version(base), "csv", FRED_URL,
                                     period_column="observation_date")
    return _collect([_save_if_new(base, content, today)])


def fetch_eia_intl(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    content = _get(EIA_URL, timeout=300, max_bytes=MAX_BYTES["eia_intl"])
    download_checks.check_eia_zip(content, EIA_URL)
    return _collect([_save_if_new(raw_root / "eia" / "INTL.zip", content, today)])


def fetch_wb_oda(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    import flags  # the catalog states each file's indicator (source_indicator)

    catalog = flags.load_catalog()
    contents = {}
    for name in WB_FILES:
        indicator = catalog[WB_SERIES[name]]["source_indicator"]
        url = WB_URL.format(indicator=indicator)
        content = _get(url, max_bytes=MAX_BYTES["wb_oda"])
        download_checks.check_wb_json(content, url, indicator)
        download_checks.check_not_shrunk(content, downloads.latest_version(raw_root / "oecd" / name), "wb_json", url)
        contents[name] = content  # check both files before saving either
    return _collect([_save_if_new(raw_root / "oecd" / name, content, today) for name, content in contents.items()])


def _bis_key(csv_path: Path) -> str:
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    header, first = lines[0].split(","), lines[1].split(",")
    row = dict(zip(header, first))
    return ".".join(row[c] for c in BIS_KEY_COLUMNS)


def fetch_bis_lbs(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    contents = {}
    for name in BIS_FILES:
        archived = downloads.latest_version(raw_root / "bis" / name)
        url = BIS_URL.format(key=_bis_key(archived))
        content = _get(url, max_bytes=MAX_BYTES["bis_lbs"])
        download_checks.check_bis_csv(content, url, BIS_KEY_COLUMNS)
        download_checks.check_not_shrunk(content, archived, "csv", url, period_column="TIME_PERIOD")
        contents[name] = content  # check all five files before saving any
    return _collect([_save_if_new(raw_root / "bis" / name, content, today) for name, content in contents.items()])


# ===================================================================== CBI pages


_LINK = re.compile(r"<a\b[^>]*href=['\"]([^'\"]+\.xlsx)['\"][^>]*>(.*?)</a>", re.I | re.S)


def fetch_cbi_bop(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    """The current-year and previous-year BOP workbooks, identified by the year in the link text."""
    page = downloads.polite_get(CBI_BOP_PAGE, timeout=20, max_bytes=downloads.PAGE_MAX_BYTES)
    page.raise_for_status()
    links = {}
    for href, text in _LINK.findall(page.text):
        label = re.sub(r"<[^>]+>", " ", text)
        for year in (today.year, today.year - 1):
            if str(year) in label and year not in links:
                links[year] = downloads.page_link(CBI_BOP_PAGE, href)
    if not links:
        raise ValueError(f"cbi_bop: no workbook link labelled {today.year} or {today.year - 1} on {CBI_BOP_PAGE}")
    contents = {year: _get(links[year]) for year in sorted(links)}
    for year, content in contents.items():
        downloads.check_workbook(content, links[year], sheet_pattern=r"Q[1-4]")  # check all before saving any
    saved = [_save_if_new(raw_root / "cbi" / "bop" / f"bop_{year}.xlsx", content, today)
             for year, content in contents.items()]
    return _collect(saved)


def _cbi_wrapped(resolve: Callable[[Path], Optional[Path]], download: Callable) -> Fetcher:
    """Run an existing CBI downloader, then drop its file if it equals the newest archived one."""

    def fetch(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
        cbi = raw_root / "cbi"
        before = resolve(cbi)
        target = download(cbi, today=today, manifest_path=manifest_path, manifest_root=raw_root.parent)
        if before is not None and _sha(before.read_bytes()) == _sha(target.read_bytes()):
            target.unlink()
            return None
        return [target]

    return fetch


def fetch_cbi_kfi(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    import parse_cbi_money_banking as p

    return _cbi_wrapped(p.resolve_indicators_input, p.download_latest_indicators)(raw_root, today, manifest_path)


def fetch_cbi_bulletin(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    import parse_cbi_fiscal_bulletin as p

    return _cbi_wrapped(p.resolve_bulletin_input, p.download_latest_bulletin)(raw_root, today, manifest_path)


# ===================================================================== exchange rates

_AR_FORMS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ـ": None})
_AR_MARKS = re.compile("[ً-ْٰ]")  # harakat and the superscript alef
CBI_FX_WORDS = ["الدينار", "الدولار", "يومي"]  # the link text names the dinar, the dollar and "daily"
_BLOCKED = "You have been blocked"  # the cbi.iq firewall's block page


def _normalise_ar(text: str) -> str:
    """Arabic forms that vary between pages (hamza, ta marbuta, alef maqsura, tatweel, diacritics)."""
    return _AR_MARKS.sub("", text).translate(_AR_FORMS)


def _not_blocked(text: str, url: str) -> None:
    if _BLOCKED in text:
        raise ValueError(f"cbi_fx: {url} was blocked by the CBI website firewall; download the file by hand "
                         "(docs/collecting_data_doc.md, section 5, 'Maintenance Runbook')")


def fetch_github_fx(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    """daily_fx.csv of the Iraq-parallel-exchange-rate repo: the parallel rate from 2023."""
    content = _get(GITHUB_FX_URL, max_bytes=MAX_BYTES["github_fx"])
    if not content.startswith(b"date,"):
        raise ValueError(f"github_fx: {GITHUB_FX_URL} did not return the daily_fx.csv table (starts with {content[:40]!r})")
    base = raw_root / "github" / "daily_fx.csv"
    download_checks.check_not_shrunk(content, downloads.latest_version(base), "csv", GITHUB_FX_URL, period_column="date")
    return _collect([_save_if_new(base, content, today)])


def fetch_cbi_fx(raw_root: Path, today: date, manifest_path: Path) -> Optional[List[Path]]:
    """
    CBI's dinar-per-dollar workbook (daily, monthly, annual) from page 144, found by its link text
    because its file name changes with every upload.
    """
    page = downloads.polite_get(CBI_FX_PAGE, timeout=20, max_bytes=downloads.PAGE_MAX_BYTES)
    page.raise_for_status()
    _not_blocked(page.text, CBI_FX_PAGE)
    links = []
    for href, text in _LINK.findall(page.text):
        label = _normalise_ar(re.sub(r"<[^>]+>", " ", text))
        if all(_normalise_ar(w) in label for w in CBI_FX_WORDS):
            links.append(downloads.page_link(CBI_FX_PAGE, href))
    if len(links) != 1:
        raise ValueError(f"cbi_fx: expected one workbook link on {CBI_FX_PAGE} whose text contains "
                         f"{' + '.join(CBI_FX_WORDS)}; found {len(links)}")
    content = _get(links[0])
    _not_blocked(content[:4000].decode("utf-8", "replace"), links[0])
    downloads.check_workbook(content, links[0], sheets=("Daily Price basis",))
    return _collect([_save_if_new(raw_root / "cbi" / "fx" / "cbi_fx_usd.xlsx", content, today)])


FETCHERS: Dict[str, Fetcher] = {
    "bis_lbs": fetch_bis_lbs,
    "cbi_bop": fetch_cbi_bop,
    "cbi_kfi": fetch_cbi_kfi,
    "cbi_bulletin": fetch_cbi_bulletin,
    "wb_oda": fetch_wb_oda,
    "fred_brent": fetch_fred_brent,
    "eia_intl": fetch_eia_intl,
    "cbi_fx": fetch_cbi_fx,
    "github_fx": fetch_github_fx,
}
