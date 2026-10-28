"""
pipeline.cpi_linking
====================
Links the official CPI bases into the continuous `cpi_headline` and `cpi_core` series (docs/linked_inflation_method.md).

Each older base is used through December of its overlap year (the last calendar year in which it
and the next base both have all 12 months) and the series switches to the next base the following
January. The step factor is next(December) / old(December), a one-month overlap at December, and
the chain factor is the product of step factors down to the newest base, which is not rescaled.
So month-on-month and year-on-year rates in every overlap year are the old base's official rates,
and the month-on-month rate at each switch month is the new base's.

Pure functions: no files, no clock. The parser, the doc generator (pipeline/docs_cpi.py) and the
tests share them, so the published series and the method doc cannot disagree.
"""

from typing import Dict, List, NamedTuple, Sequence

import pandas as pd

BASES = ("1993", "2007", "2012", "2022")
TOLERANCE_PP = 0.5  # stated tolerance for post-splice YoY gaps


class Sensitivity(NamedTuple):
    """How the choice of link month moves the levels before a splice (the ratios are new base / old base)."""
    kind: str
    old_base: str
    new_base: str
    overlap_year: str
    january: float          # the ratio in January of the overlap year
    december: float         # the ratio the method uses
    mean: float             # the mean of the 12 monthly ratios
    lowest: float
    highest: float

    def move(self, ratio: float) -> float:
        """Percent by which every level before the splice would differ if `ratio` were the step factor instead."""
        return (ratio / self.december - 1) * 100


class Splice(NamedTuple):
    kind: str
    old_base: str
    new_base: str
    overlap_year: str
    step_factor: float
    chain_factor: float     # puts old_base on the newest base's scale
    last_old_month: str     # December of the overlap year
    splice_month: str       # first month on new_base


def _sid(kind: str, base: str) -> str:
    return f"cpi.{kind}_{base}"


def _shift(date: str, months: int) -> str:
    y, m = map(int, date.split("-"))
    t = y * 12 + (m - 1) + months
    return f"{t // 12}-{t % 12 + 1:02d}"


def _full_years(series: pd.Series) -> set:
    years: Dict[str, int] = {}
    for d in series.dropna().index:
        years[d[:4]] = years.get(d[:4], 0) + 1
    return {y for y, n in years.items() if n == 12}


def splices(natives: Dict[str, pd.Series], kind: str, bases: Sequence[str] = BASES) -> List[Splice]:
    """One Splice per consecutive pair of bases, oldest first."""
    pairs = list(zip(bases, bases[1:]))
    steps = []
    for old, new in pairs:
        s_old, s_new = natives[_sid(kind, old)], natives[_sid(kind, new)]
        common = _full_years(s_old) & _full_years(s_new)
        if not common:
            raise ValueError(f"no full overlap year between {_sid(kind, old)} and {_sid(kind, new)}")
        year = max(common)
        dec = f"{year}-12"
        steps.append((old, new, year, float(s_new[dec]) / float(s_old[dec])))
    chain = 1.0
    out: List[Splice] = []
    for old, new, year, step in reversed(steps):
        chain *= step
        out.append(Splice(kind, old, new, year, step, chain, f"{year}-12", f"{int(year) + 1}-01"))
    return out[::-1]


def link_sensitivity(natives: Dict[str, pd.Series], kind: str, bases: Sequence[str] = BASES) -> List[Sensitivity]:
    """
    One Sensitivity per splice: the new/old ratio in each month of the overlap year. The base series are
    different baskets, so the ratio drifts through the year; linking in another month would move every
    level before the splice by the ratio's difference from December's. Effects multiply down the chain.
    """
    out = []
    for s in splices(natives, kind, bases):
        old, new = natives[_sid(kind, s.old_base)], natives[_sid(kind, s.new_base)]
        ratios = [float(new[f"{s.overlap_year}-{m:02d}"]) / float(old[f"{s.overlap_year}-{m:02d}"]) for m in range(1, 13)]
        out.append(Sensitivity(kind, s.old_base, s.new_base, s.overlap_year, ratios[0], ratios[-1],
                               sum(ratios) / 12, min(ratios), max(ratios)))
    return out


def link(natives: Dict[str, pd.Series], kind: str, bases: Sequence[str] = BASES) -> pd.Series:
    """The linked series (unrounded), indexed by YYYY-MM, from the first base's first month."""
    sp = splices(natives, kind, bases)
    chain = {s.old_base: s.chain_factor for s in sp}
    chain[bases[-1]] = 1.0
    values: Dict[str, float] = {}
    start = "0000-00"
    for i, base in enumerate(bases):
        end = sp[i].last_old_month if i < len(sp) else "9999-99"
        for date, value in natives[_sid(kind, base)].dropna().items():
            if start <= date <= end:
                values[date] = float(value) * chain[base]
        if i < len(sp):
            start = sp[i].splice_month
    return pd.Series(values, dtype="float64").sort_index()


def splice_months(natives: Dict[str, pd.Series], kind: str, bases: Sequence[str] = BASES) -> List[str]:
    """The months where the linked series switches base (status flag B)."""
    return [s.splice_month for s in splices(natives, kind, bases)]


def post_splice_gaps(natives: Dict[str, pd.Series], kind: str, bases: Sequence[str] = BASES) -> pd.DataFrame:
    """
    For the 12 months from each splice month: linked YoY, the new base's official YoY and the gap
    between them in percentage points; `exception` marks gaps above TOLERANCE_PP.
    """
    linked = link(natives, kind, bases)
    rows = []
    for s in splices(natives, kind, bases):
        new = natives[_sid(kind, s.new_base)]
        for k in range(12):
            t = _shift(s.splice_month, k)
            u = _shift(t, -12)
            if t not in linked.index or u not in linked.index or t not in new.index or u not in new.index:
                continue
            ly = (linked[t] / linked[u] - 1) * 100
            oy = (float(new[t]) / float(new[u]) - 1) * 100
            rows.append({"splice_month": s.splice_month, "date": t, "linked_yoy": ly, "official_yoy": oy,
                         "gap_pp": abs(ly - oy)})
    df = pd.DataFrame(rows, columns=["splice_month", "date", "linked_yoy", "official_yoy", "gap_pp"])
    df["exception"] = df["gap_pp"] > TOLERANCE_PP
    return df


def reference_average(natives: Dict[str, pd.Series], kind: str, year: str = "2022",
                      bases: Sequence[str] = BASES) -> float:
    """Mean of the linked series over the 12 months of `year` (not rescaled to 100)."""
    linked = link(natives, kind, bases)
    return float(linked[[f"{year}-{m:02d}" for m in range(1, 13)]].mean())
