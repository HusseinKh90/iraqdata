"""
pipeline.docs_origin
====================
Keeps the user-facing origin documentation in step with the series catalog.

    python pipeline/docs_origin.py            # rewrite the generated block in docs/series.md and
                                              # the measured share in README.md
    python pipeline/docs_origin.py --check    # exit 1 if either is out of date

The block between `<!-- origin:begin -->` and `<!-- origin:end -->` in docs/series.md lists each
series' origin and every period that is not observed from an archived official file. The tables
between `<!-- series:<key>:begin -->` and `<!-- series:<key>:end -->` list each family's series with
its frequency, unit, start date and catalog `summary`; the block between
`<!-- terms:begin -->` and `<!-- terms:end -->` in docs/source_inventory.md lists each source's terms
of reuse from pipeline/metadata/sources.yaml. The README
states the share of published observations that are, between `<!-- share:begin -->` and
`<!-- share:end -->`. Both are generated, so they cannot drift from the metadata.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

import pandas as pd  # noqa: E402

import flags  # noqa: E402
from iraqdata.catalog import origin_summary  # noqa: E402

SERIES_DOC = repo_root / "docs" / "series.md"
README = repo_root / "README.md"
GARDEN_DIR = repo_root / "pipeline" / "data" / "garden"
BEGIN, END = "<!-- origin:begin -->", "<!-- origin:end -->"
SHARE_BEGIN, SHARE_END = "<!-- share:begin -->", "<!-- share:end -->"


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def render_block(catalog: Optional[dict] = None) -> str:
    catalog = catalog if catalog is not None else flags.load_catalog()
    lines = [BEGIN, "", "### Origin of every series", "",
             "Generated from `src/iraqdata/series_catalog.yaml` by `pipeline/docs_origin.py`; do not edit by hand.",
             "", "| Series | Origin |", "|--------|--------|"]
    lines += [f"| `{sid}` | {_cell(origin_summary(e['origin']))} |" for sid, e in catalog.items()]
    lines += ["", "## Data not observed from an archived official file", "",
              "These periods are derived, modelled, transcribed by hand, of unknown origin, or observed from "
              "a non-official source. Transcribed and unknown-origin values carry status flag `U`, modelled "
              "values `E`; derived values take the flag of their inputs.",
              "", "| Series | Periods | Class | Method | Source |",
              "|--------|---------|-------|--------|--------|"]
    for sid, e in catalog.items():
        for seg in e["origin"]:
            if seg["class"] == "observed" and seg["official"]:
                continue
            cls = seg["class"] + ("" if seg["official"] else " (unofficial)")
            src = seg["source"] + (f"; record `{seg['record']}`" if seg.get("record") else "")
            lines.append(f"| `{sid}` | {flags.period(seg['from'])}..{flags.period(seg['to'])} | {cls} | "
                         f"{_cell(seg['method'])} | {_cell(src)} |")
    lines += ["", END]
    return "\n".join(lines)


# The per-family tables of docs/series.md, one block per section
SERIES_SECTIONS = [
    ("money_banking", ["money_banking"]),
    ("exchange_rates", ["exchange_rates"]),
    ("oil", ["oil"]),
    ("prices", ["prices"]),
    ("fiscal", ["fiscal"]),
    ("gdp", ["gdp"]),
    ("bop_trade", ["bop", "trade"]),
    ("bis", ["bis"]),
    ("oecd", ["oecd"]),
]
UNIT_LABELS = {
    "BILLION_IQD": "Billion IQD", "MILLION_IQD": "Million IQD", "MILLION_USD": "Million USD",
    "IQD_PER_USD": "IQD per USD", "USD_PER_BBL": "USD per Barrel", "TB_PER_D": "Th. Barrels/Day",
    "PERCENT": "Percent", "INDEX": "Index",
}


def series_markers(key: str) -> tuple:
    return f"<!-- series:{key}:begin -->", f"<!-- series:{key}:end -->"


def render_series_table(key: str, categories: Sequence[str], catalog: Optional[dict] = None) -> str:
    """One generated table of docs/series.md: the series of `categories`, in catalog order."""
    catalog = catalog if catalog is not None else flags.load_catalog()
    begin, end = series_markers(key)
    lines = [begin, "", "| Series | Frequency | Unit | Starts | Description |",
             "| :--- | :---: | :---: | :---: | :--- |"]
    for sid, e in catalog.items():
        if e["category"] not in categories:
            continue
        if e["unit"] not in UNIT_LABELS:
            raise ValueError(f"{sid}: no label for unit {e['unit']!r} (docs_origin.UNIT_LABELS)")
        lines.append(f"| `{sid}` | {e['frequency'].title()} | {UNIT_LABELS[e['unit']]} | "
                     f"{flags.period(e['start_date'])} | {_cell(e['summary'])} |")
    lines += ["", end]
    return "\n".join(lines)


INVENTORY_DOC = repo_root / "docs" / "source_inventory.md"
SOURCES_PATH = repo_root / "pipeline" / "metadata" / "sources.yaml"
TERMS_BEGIN, TERMS_END = "<!-- terms:begin -->", "<!-- terms:end -->"
STATUS_LABELS = {"licensed": "Licensed", "no_licence_stated": "No licence stated",
                 "confirmed_by_maintainer": "Confirmed by the maintainer", "unconfirmed": "Not yet confirmed"}


def render_terms_block(path: Path = SOURCES_PATH) -> str:
    """The "Terms of reuse by source" block of docs/source_inventory.md."""
    import yaml

    records = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    lines = [TERMS_BEGIN, "", "## Terms of reuse by source", "",
             "Generated from `pipeline/metadata/sources.yaml` by `pipeline/docs_origin.py`; do not edit by hand. "
             "The compiled and derived data are licensed CC-BY 4.0; each source's own terms still apply to its "
             "data. Cite both the package and the original publisher.", "",
             "| Source | Publisher | Terms | Licence | Status | Redistribution | Checked |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in records:
        url = r["url"] if str(r["url"]).startswith("http") else f"../{r['url']}"  # repository paths, from docs/
        lines.append(f"| `{r['id']}`: [{_cell(r['title'])}]({url}) | {_cell(r['publisher'])} | "
                     f"{_cell(r['terms'])} | {r['licence'] or 'none stated'} | {STATUS_LABELS[r['status']]} | "
                     f"{_cell(r['redistribution'])} | {r['checked']} |")
    open_items = [r for r in records if r["status"] == "unconfirmed"]
    lines += ["", "**Open items:** the terms of these sources have not yet been "
              "confirmed at the publisher: " + (", ".join(f"`{r['id']}`" for r in open_items) or "none") + ".",
              "", TERMS_END]
    return "\n".join(lines)


def official_share(catalog: Optional[dict] = None, garden_dir: Path = GARDEN_DIR) -> int:
    """Whole-number percentage of published observations observed from an archived official file."""
    catalog = catalog if catalog is not None else flags.load_catalog()
    total = official = 0
    for path in sorted(garden_dir.glob("*.parquet")):
        df = pd.read_parquet(path, columns=["series_id", "date"])
        for sid, date in zip(df["series_id"], df["date"].astype(str)):
            total += 1
            try:
                seg = flags.segment_for(catalog[sid], date)
            except ValueError:  # a period no segment covers is not observed from an official file
                continue
            official += seg["class"] == "observed" and seg["official"]
    return int(100 * official // total) if total else 0


def _replace_between(text: str, begin: str, end: str, inner: str, name: str) -> str:
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"{name} must contain {begin} and {end} exactly once")
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    return head + inner + tail


def _read(path: Path) -> tuple:
    """(text with LF line endings, whether the file uses CRLF)."""
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def updated_files() -> List[tuple]:
    """(path, current bytes, wanted bytes) for each generated document; line endings are kept."""
    blocks = {
        SERIES_DOC: [(BEGIN, END, render_block())]
        + [(*series_markers(key), render_series_table(key, cats)) for key, cats in SERIES_SECTIONS],
        README: [(SHARE_BEGIN, SHARE_END, f"{SHARE_BEGIN}{official_share()}%{SHARE_END}")],
        INVENTORY_DOC: [(TERMS_BEGIN, TERMS_END, render_terms_block())],
    }
    out = []
    for path, parts in blocks.items():
        if not path.is_file():      # an internal document kept out of the published repository
            continue
        text, crlf = _read(path)
        wanted = text
        for begin, end, inner in parts:
            wanted = _replace_between(wanted, begin, end, inner, path.name)
        if crlf:
            wanted = wanted.replace("\n", "\r\n")
        out.append((path, path.read_bytes(), wanted.encode("utf-8")))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or check the origin documentation.")
    parser.add_argument("--check", action="store_true", help="exit 1 if a generated document is out of date")
    args = parser.parse_args(argv)
    stale = []
    for path, current, wanted in updated_files():
        if current != wanted:
            stale.append(path)
            if not args.check:
                path.write_bytes(wanted)
    if args.check and stale:
        print("Out of date: " + ", ".join(p.relative_to(repo_root).as_posix() for p in stale)
              + " (run python pipeline/docs_origin.py)")
        return 1
    print("Origin documentation is up to date." if not stale else "Updated: " + ", ".join(p.name for p in stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
