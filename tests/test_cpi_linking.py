"""
Linked CPI.

The linked series `cpi_headline` and `cpi_core` use each older base through December of its
overlap year and switch to the newer base the following January, linking at that December. The
expected values here are recomputed inline from the published native series, not with
`cpi_linking`, which is the code under test. Tests whose name contains "production" read the published linked rows.
"""

import pandas as pd
import pytest

import cpi_linking
from conftest import GARDEN_DIR

KINDS = ("headline", "core")
BASES = ("1993", "2007", "2012", "2022")
OVERLAP = {"1993": "2009", "2007": "2015", "2012": "2023"}
SPLICE_MONTHS = ["2010-01", "2016-01", "2024-01"]


def _table():
    return pd.read_parquet(GARDEN_DIR / "prices_monthly.parquet")


def _natives(kind, table=None):
    df = _table() if table is None else table
    return {f"cpi.{kind}_{b}": df[df["series_id"] == f"cpi.{kind}_{b}"].set_index("date")["value"].sort_index()
            for b in BASES}


def _shift(date, months):
    y, m = map(int, date.split("-"))
    t = y * 12 + (m - 1) + months
    return f"{t // 12}-{t % 12 + 1:02d}"


def _expected(kind, natives=None):
    """Inline recomputation: step factors at the overlap Decembers, chained down to 2022."""
    n = natives or _natives(kind)
    step = {old: n[f"cpi.{kind}_{new}"][f"{OVERLAP[old]}-12"] / n[f"cpi.{kind}_{old}"][f"{OVERLAP[old]}-12"]
            for old, new in zip(BASES, BASES[1:])}
    chain = {"2022": 1.0}
    for old, new in reversed(list(zip(BASES, BASES[1:]))):
        chain[old] = step[old] * chain[new]
    linked = {}
    for b in BASES:
        s = n[f"cpi.{kind}_{b}"]
        start = "0000-00" if b == "1993" else f"{int(OVERLAP[BASES[BASES.index(b) - 1]]) + 1}-01"
        end = f"{OVERLAP[b]}-12" if b in OVERLAP else "9999-99"
        for t, v in s.items():
            if start <= t <= end:
                linked[t] = v * chain[b]
    return step, chain, pd.Series(linked).sort_index()


def _rel(a, b):
    return abs(a / b - 1)


# --- Factors and splice months ---------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_factors_match_the_december_overlap(kind):
    step, chain, _ = _expected(kind)
    got = cpi_linking.splices(_natives(kind), kind)
    assert [(s.old_base, s.new_base, s.overlap_year) for s in got] == [
        ("1993", "2007", "2009"), ("2007", "2012", "2015"), ("2012", "2022", "2023")]
    for s in got:
        assert _rel(s.step_factor, step[s.old_base]) <= 1e-12, s
        assert _rel(s.chain_factor, chain[s.old_base]) <= 1e-12, s
        assert s.last_old_month == f"{s.overlap_year}-12"


@pytest.mark.parametrize("kind", KINDS)
def test_splice_months(kind):
    assert cpi_linking.splice_months(_natives(kind), kind) == SPLICE_MONTHS


# --- Contract guarantees ---------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_linked_series_equals_the_inline_recomputation(kind):
    _, _, expected = _expected(kind)
    got = cpi_linking.link(_natives(kind), kind)
    assert list(got.index) == list(expected.index)
    assert ((got / expected - 1).abs() <= 1e-12).all()


@pytest.mark.parametrize("kind", KINDS)
def test_splice_month_mom_is_the_new_base(kind):
    n = _natives(kind)
    linked = cpi_linking.link(n, kind)
    for old, new in zip(BASES, BASES[1:]):
        t = f"{int(OVERLAP[old]) + 1}-01"
        s = n[f"cpi.{kind}_{new}"]
        assert abs((linked[t] / linked[_shift(t, -1)]) - (s[t] / s[_shift(t, -1)])) * 100 <= 0.01, t


@pytest.mark.parametrize("kind", KINDS)
def test_overlap_year_rates_are_the_old_base(kind):
    n = _natives(kind)
    linked = cpi_linking.link(n, kind)
    for old in OVERLAP:
        s = n[f"cpi.{kind}_{old}"]
        for m in range(1, 13):
            t = f"{OVERLAP[old]}-{m:02d}"
            for lag in (1, 12):
                u = _shift(t, -lag)
                assert abs(linked[t] / linked[u] - s[t] / s[u]) * 100 <= 0.01, (t, lag)


@pytest.mark.parametrize("kind", KINDS)
def test_no_rescale_from_the_2022_base(kind):
    """From the switch to the 2022 base the official 2022-base values are kept."""
    n = _natives(kind)
    linked = cpi_linking.link(n, kind)
    new = n[f"cpi.{kind}_2022"]
    for t in new.index:
        if t >= "2024-01":
            assert linked[t] == new[t], t


@pytest.mark.parametrize("kind", KINDS)
def test_post_splice_gaps(kind):
    n = _natives(kind)
    gaps = cpi_linking.post_splice_gaps(n, kind)
    linked = cpi_linking.link(n, kind)
    assert len(gaps) == 36
    assert (gaps["exception"] == (gaps["gap_pp"] > cpi_linking.TOLERANCE_PP)).all()
    for row in gaps.itertuples():
        new = n[f"cpi.{kind}_{dict(zip(BASES[:-1], BASES[1:]))[[b for b in OVERLAP if f'{int(OVERLAP[b]) + 1}-01' == row.splice_month][0]]}"]
        u = _shift(row.date, -12)
        assert abs(row.gap_pp - abs((linked[row.date] / linked[u] - new[row.date] / new[u]) * 100)) < 1e-9


def test_reference_average_is_the_2022_mean():
    for kind in KINDS:
        n = _natives(kind)
        linked = cpi_linking.link(n, kind)
        assert cpi_linking.reference_average(n, kind) == pytest.approx(
            linked[[f"2022-{m:02d}" for m in range(1, 13)]].mean(), rel=1e-15)


def _synthetic(bases, months_per_base=36, overlap=12):
    """Bases of a steady 1% monthly index, each new base overlapping the previous by `overlap`."""
    out, start = {}, 2000 * 12
    for i, b in enumerate(bases):
        dates = [f"{(start + k) // 12}-{(start + k) % 12 + 1:02d}" for k in range(months_per_base)]
        out[f"cpi.headline_{b}"] = pd.Series([100 * (1.01 ** k) * (i + 1) for k in range(months_per_base)], index=dates)
        start += months_per_base - overlap
    return out


def test_any_number_of_bases_links_without_code_change():
    bases = ("2000", "2003", "2006", "2009", "2012")
    natives = _synthetic(bases)
    got = cpi_linking.splices(natives, "headline", bases=bases)
    assert len(got) == 4
    linked = cpi_linking.link(natives, "headline", bases=bases)
    mom = (linked / linked.shift(1) - 1).dropna()
    assert ((mom - 0.01).abs() < 1e-12).all()  # a steady index stays steady across every splice


def test_missing_overlap_december_raises():
    natives = _natives("headline")
    natives["cpi.headline_2007"] = natives["cpi.headline_2007"].drop("2015-12")
    with pytest.raises(ValueError, match=r"cpi\.headline_2007.*cpi\.headline_2012"):
        cpi_linking.splices(natives, "headline")


# --- Scratch build of the parser --------------------------------------------------

@pytest.fixture(scope="module")
def scratch_build(tmp_path_factory):
    import parse_cbi_cpi
    out = tmp_path_factory.mktemp("cpi") / "prices_monthly.parquet"
    return parse_cbi_cpi.parse_cbi_cpi(output_parquet_path=out)


def test_scratch_build_natives_unchanged_and_linked_rows_follow_the_method(scratch_build):
    prod = _table()
    natives = [f"cpi.{k}_{b}" for k in KINDS for b in BASES]
    a = scratch_build[scratch_build["series_id"].isin(natives)].sort_values(["series_id", "date"]).reset_index(drop=True)
    b = prod[prod["series_id"].isin(natives)].sort_values(["series_id", "date"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a[["date", "series_id", "value", "unit", "status_flag", "source_hash"]],
                                  b[["date", "series_id", "value", "unit", "status_flag", "source_hash"]])
    for kind in KINDS:
        stored = scratch_build[scratch_build["series_id"] == f"cpi_{kind}"].set_index("date")["value"].sort_index()
        expected = cpi_linking.link(_natives(kind, scratch_build), kind).round(4)
        assert list(stored.index) == list(expected.index)
        assert ((stored - expected).abs() < 1e-9).all()


def test_scratch_build_b_flags_are_exactly_the_splice_months(scratch_build):
    b = scratch_build[scratch_build["status_flag"] == "B"]
    assert sorted(zip(b["series_id"], b["date"])) == sorted(
        (f"cpi_{k}", m) for k in KINDS for m in SPLICE_MONTHS)


# --- Mutation tests ------------------------------------------------------------

def _mutated(series_id, date, factor=1.01):
    n = _natives("headline")
    n[series_id] = n[series_id].copy()
    n[series_id][date] *= factor
    return n


def test_mutating_an_overlap_december_moves_its_factor():
    base = cpi_linking.link(_natives("headline"), "headline")
    n = _mutated("cpi.headline_2007", "2015-12")
    steps = {s.overlap_year: s.step_factor for s in cpi_linking.splices(n, "headline")}
    before = {s.overlap_year: s.step_factor for s in cpi_linking.splices(_natives("headline"), "headline")}
    assert steps["2015"] != before["2015"], "2015 splice factor did not move"
    assert steps["2009"] == before["2009"] and steps["2023"] == before["2023"]
    after = cpi_linking.link(n, "headline")
    changed = sorted(after.index[(after / base - 1).abs() > 1e-12])
    expected = [t for t in base.index if t <= "2015-12" and t != "2015-12"]
    assert changed == expected, "the 2015 splice: every 1993/2007 segment month except 2015-12 must move"


def test_mutating_a_used_non_december_month_moves_only_that_value():
    base = cpi_linking.link(_natives("headline"), "headline")
    n = _mutated("cpi.headline_2007", "2015-06")
    assert [s.step_factor for s in cpi_linking.splices(n, "headline")] == \
        [s.step_factor for s in cpi_linking.splices(_natives("headline"), "headline")]
    after = cpi_linking.link(n, "headline")
    assert list(after.index[(after / base - 1).abs() > 1e-12]) == ["2015-06"]


def test_mutating_an_unused_month_changes_nothing():
    base = cpi_linking.link(_natives("headline"), "headline")
    n = _mutated("cpi.headline_2012", "2015-06")  # the 2012 base is used only from 2016-01
    after = cpi_linking.link(n, "headline")
    assert ((after / base - 1).abs() <= 1e-15).all()


# --- Production ----------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_production_linked_rows_follow_the_method(kind):
    df = _table()
    stored = df[df["series_id"] == f"cpi_{kind}"].set_index("date")["value"].sort_index()
    _, _, expected = _expected(kind)
    assert list(stored.index) == list(expected.index)
    assert ((stored - expected.round(4)).abs() < 1e-9).all()


def test_production_b_flags_are_the_splice_months():
    df = _table()
    b = df[df["status_flag"] == "B"]
    assert sorted(zip(b["series_id"], b["date"])) == sorted(
        (f"cpi_{k}", m) for k in KINDS for m in SPLICE_MONTHS)


# --- The method doc -------------------------------------------

import re  # noqa: E402

import docs_cpi  # noqa: E402
import flags  # noqa: E402
from conftest import REPO_ROOT  # noqa: E402

DOC = REPO_ROOT / "docs" / "linked_inflation_method.md"


def _doc_parts():
    text = DOC.read_text(encoding="utf-8")
    head, rest = text.split(docs_cpi.BEGIN)
    block, tail = rest.split(docs_cpi.END)
    return head + tail, block


def test_doc_is_generated_and_current():
    """The committed doc equals its regeneration."""
    assert DOC.read_bytes() == docs_cpi.wanted_bytes()


def test_doc_factors_and_averages_match_the_computation():
    """The step factors, chain factors and reference averages printed in the doc are the computed ones."""
    _, block = _doc_parts()
    for kind in KINDS:
        n = _natives(kind)
        for s in cpi_linking.splices(n, kind):
            row = f"| `cpi_{kind}` | {s.old_base} | {s.new_base} | {s.overlap_year} | {s.step_factor:.7g} | {s.chain_factor:.7g} |"
            assert row in block, row
        assert f"| `cpi_{kind}` | {cpi_linking.reference_average(n, kind):.3f} |" in block


def test_doc_has_no_hand_typed_computed_numbers():
    """Outside the generated block the only decimals are the 0.5 tolerance and CPI Manual paragraphs."""
    prose, _ = _doc_parts()
    decimals = set(re.findall(r"\d+\.\d+", prose))
    assert decimals <= {"0.5"} | {d for d in decimals if re.fullmatch(r"9\.\d\d", d)}, decimals


def test_doc_cites_the_manual_and_has_limitations():
    prose, _ = _doc_parts()
    assert "Consumer Price Index Manual: Concepts and Methods* (2020)" in prose
    assert "Chapter 9" in prose and "## 11. Limitations" in prose
    assert "not archived" in prose


def test_catalog_describes_the_method_without_numbers():
    """Approximate reference period, method named, pointer to the doc, no decimals."""
    cat = flags.load_catalog()
    for kind in KINDS:
        entry = cat[f"cpi_{kind}"]
        desc = " ".join(entry["description"].split())
        assert "approximate" in desc and "linked_inflation_method.md" in desc
        assert "December one-month overlap" in desc or "same December one-month overlap" in desc
        assert not re.search(r"\d+\.\d+", desc), desc
        assert (REPO_ROOT / entry["source_file"].split(" (")[0]).exists()
    assert "core definition changes" in " ".join(cat["cpi_core"]["description"].split())


def test_doc_check_fails_when_a_factor_is_edited(tmp_path, monkeypatch):
    edited = tmp_path / "doc.md"
    text = DOC.read_text(encoding="utf-8")
    s = cpi_linking.splices(_natives("headline"), "headline")[0]
    edited.write_text(text.replace(f"{s.step_factor:.7g}", "0.1234567", 1), encoding="utf-8")
    monkeypatch.setattr(docs_cpi, "METHOD_DOC", edited)
    assert docs_cpi.main(["--check"]) == 1


# --- Sensitivity to the link month, the core warning and the glossary --------------------------


def _ratios(kind, splice):
    n = _natives(kind)
    old, new = n[f"cpi.{kind}_{splice.old_base}"], n[f"cpi.{kind}_{splice.new_base}"]
    return [float(new[f"{splice.overlap_year}-{m:02d}"]) / float(old[f"{splice.overlap_year}-{m:02d}"]) for m in range(1, 13)]


@pytest.mark.parametrize("kind", KINDS)
def test_sensitivity_is_the_ratio_through_the_overlap_year(kind):
    n = _natives(kind)
    for s, t in zip(cpi_linking.splices(n, kind), cpi_linking.link_sensitivity(n, kind)):
        r = _ratios(kind, s)
        assert (t.old_base, t.new_base, t.overlap_year) == (s.old_base, s.new_base, s.overlap_year)
        assert t.december == pytest.approx(s.step_factor) and t.january == pytest.approx(r[0])
        assert t.lowest == pytest.approx(min(r)) and t.highest == pytest.approx(max(r))
        assert t.mean == pytest.approx(sum(r) / 12)
        assert t.move(t.december) == 0 and t.move(t.january) == pytest.approx((r[0] / r[-1] - 1) * 100)


def test_linking_in_another_month_moves_the_earlier_levels_by_that_percentage():
    """Relink with January's ratio as the first pair's step factor and compare every level of the older base."""
    n = _natives("headline")
    first = cpi_linking.link_sensitivity(n, "headline")[0]
    base = cpi_linking.link(n, "headline")
    altered = {k: v.copy() for k, v in n.items()}
    altered["cpi.headline_2007"].loc["2009-12"] = float(n["cpi.headline_1993"]["2009-12"]) * first.january
    relinked = cpi_linking.link(altered, "headline")
    for date in ("2004-01", "2007-06", "2009-12"):
        assert (relinked[date] / base[date] - 1) * 100 == pytest.approx(first.move(first.january))
    assert relinked["2010-06"] == pytest.approx(base["2010-06"])        # the later bases are untouched


def test_doc_has_the_sensitivity_table_and_it_is_generated():
    _, block = _doc_parts()
    assert "## 9. Sensitivity to the link month" in block
    for kind in KINDS:
        for t in cpi_linking.link_sensitivity(_natives(kind), kind):
            assert f"| `cpi_{kind}` | {t.old_base} → {t.new_base} | {t.overlap_year} | {t.january:.6g} | {t.december:.6g} |" in block


def test_doc_warns_about_the_core_series_and_defines_its_terms():
    prose, _ = _doc_parts()
    assert "Warning: `cpi_core` before 2010 does not measure the same thing" in prose
    assert "`official: false`" in prose
    for term in ("MoM, YoY", "pp", "KFI", "KRSO", "IHSES", "SWIFT survey", "COICOP", "F&L, T&C, LPG", "Overlap year"):
        assert f"| {term} |" in prose or f"| {term}," in prose, term
    assert "have not been checked" in prose  # the Manual's paragraph numbers
    assert "January 2011" in prose and "electricity tariff" in prose
