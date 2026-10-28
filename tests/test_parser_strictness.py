"""
tests.test_parser_strictness
============================
Parsers fail with an error naming the place instead of silently dropping or choosing
data. Each case damages a copy of a parser's inputs under tmp_path and runs it offline; unchanged
copies give today's output.
"""

import ast
import subprocess
import sys

import openpyxl
import pandas as pd
import pytest
import yaml

import run_parsers
import source_io
from conftest import REPO_ROOT, block_network
from fixtures import damage
from source_io import ParseError

PARSERS = REPO_ROOT / "pipeline" / "parsers"
KFI = "key_financial_indicators.xlsx"


def _run(parser, raw_root, seeds_root, tmp_path):
    with block_network():
        return damage.run_parser(parser, raw_root, seeds_root, tmp_path / "out")


def _output(parser, tmp_path, edit=None, table=None) -> pd.DataFrame:
    raw_root, seeds_root = damage.copy_inputs(parser, tmp_path)
    if edit is not None:
        edit(raw_root, seeds_root)
    out = _run(parser, raw_root, seeds_root, tmp_path)
    return pd.read_parquet(out / (table or run_parsers.BY_NAME[parser].outputs[0]))


def _fails(parser, tmp_path, edit) -> ParseError:
    raw_root, seeds_root = damage.copy_inputs(parser, tmp_path)
    edit(raw_root, seeds_root)
    with pytest.raises(ParseError) as info:
        _run(parser, raw_root, seeds_root, tmp_path)
    return info.value


def _find(path, sheet, test):
    """The first cell coordinate in `sheet` whose value satisfies `test`."""
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    for row in ws.iter_rows():
        for cell in row:
            if test(cell):
                return cell.coordinate
    raise AssertionError("no such cell")


# =====================================================================
# Damaged or unexpected input stops with the place named
# =====================================================================

@pytest.mark.parametrize("parser", ["cbi_cpi", "cbi_money_banking"])
def test_renamed_sheet_is_named(parser, tmp_path):
    def rename(raw, seeds):
        wb = openpyxl.load_workbook(raw / "cbi" / KFI)
        wb["Sheet1"].title = "Data"
        wb.save(raw / "cbi" / KFI)
    if parser == "cbi_money_banking":  # it reads the newest dated KFI copy when there is one
        raw, seeds = damage.copy_inputs(parser, tmp_path)
        for p in (raw / "cbi").glob("cbi_key_financial_indicators_*.xlsx"):
            p.unlink()
        rename(raw, seeds)
        with pytest.raises(ParseError) as info:
            _run(parser, raw, seeds, tmp_path)
        err = info.value
    else:
        err = _fails(parser, tmp_path, rename)
    assert KFI in str(err) and "sheet 'Sheet1'" in str(err) and "Data" in str(err)


def _cpi_cell(raw):
    """The newest 2022-base headline CPI value (outside the 2023 overlap year the linking needs)."""
    path = raw / "cbi" / KFI
    ws = openpyxl.load_workbook(path, data_only=True)["Sheet1"]
    cells = [c for c in ws[9] if isinstance(c.value, (int, float)) and c.column > 2]
    return path, cells[-1].coordinate


def test_unreadable_cpi_cell_is_named(tmp_path):
    def edit(raw, seeds):
        path, cell = _cpi_cell(raw)
        damage.edit_cell(path, "Sheet1", cell, "n.a.")
        edit.cell = cell
    err = _fails("cbi_cpi", tmp_path, edit)
    assert f"cell {edit.cell}" in str(err) and "'n.a.'" in str(err) and "expected a number" in str(err)


def test_no_value_marker_gives_no_row_and_is_counted(tmp_path, capsys):
    base = _output("cbi_cpi", tmp_path / "base")
    capsys.readouterr()

    def edit(raw, seeds):
        path, cell = _cpi_cell(raw)
        damage.edit_cell(path, "Sheet1", cell, "…")
    out = _output("cbi_cpi", tmp_path / "marked", edit)
    assert len(out[out["series_id"] == "cpi.headline_2022"]) == len(base[base["series_id"] == "cpi.headline_2022"]) - 1
    assert "'…': 1" in capsys.readouterr().out


def _official(raw):
    return next((raw / "cbi" / "fx").glob("cbi_fx_usd_*.xlsx"))


def test_non_positive_rate_is_named(tmp_path):
    def edit(raw, seeds):
        path = _official(raw)
        damage.edit_cell(path, "Daily Price basis", "C76", -5)  # 6 February 2005
    err = _fails("cbi_exchange_rates", tmp_path, edit)
    assert "sheet 'Daily Price basis'" in str(err) and "cell C76" in str(err) and "positive value" in str(err)


def test_value_on_a_missing_calendar_date_must_be_listed(tmp_path):
    def edit(raw, seeds):
        damage.edit_cell(_official(raw), "Daily Price basis", "E101", 1460)  # 2005-04-31 does not exist
    err = _fails("cbi_exchange_rates", tmp_path, edit)
    assert "2005-04-31" in str(err) and "does not exist" in str(err) and "cell E101" in str(err)


def _bop_stacked(raw):
    return raw / "cbi" / "bop" / "bop_2013_2016.xlsx"


def test_bop_blocks_are_found_by_title(tmp_path):
    base = _output("cbi_bop", tmp_path / "base")
    moved = _output("cbi_bop", tmp_path / "moved", lambda raw, seeds: damage.insert_row(_bop_stacked(raw), "qi 2014", 228))
    pd.testing.assert_frame_equal(base.drop(columns="source_hash"), moved.drop(columns="source_hash"))

    def no_title(raw, seeds):
        wb = openpyxl.load_workbook(_bop_stacked(raw), data_only=True)
        for row in (228, 277):
            wb["qi 2014"][f"A{row}"] = "x"
        wb.save(_bop_stacked(raw))
    err = _fails("cbi_bop", tmp_path / "gone", no_title)
    assert "sheet 'qi 2014'" in str(err) and "q3 2014" in str(err)


def test_fiscal_december_label_is_exact(tmp_path):
    base = _output("cbi_fiscal_bulletin", tmp_path / "base")

    def decrease(raw, seeds):
        path = raw / "cbi" / "bulletin_latest.xlsx"
        dec = _find(path, "6-1", lambda c: c.column == 1 and str(c.value).strip() == "Dec.")
        row = int(dec[1:])
        damage.insert_row(path, "6-1", row)
        wb = openpyxl.load_workbook(path, data_only=True)
        wb["6-1"][f"A{row}"] = "Decrease"
        for col in "BCDEFGH":
            wb["6-1"][f"{col}{row}"] = 1.0
        wb.save(path)
    out = _output("cbi_fiscal_bulletin", tmp_path / "decrease", decrease)
    pd.testing.assert_frame_equal(base.drop(columns="source_hash"), out.drop(columns="source_hash"))


@pytest.mark.parametrize("module, parser", [("parse_bis_lbs", "parse_bis_lbs"), ("parse_oecd_dac", "parse_oecd_dac")])
def test_schema_errors_stop_bis_and_oecd(module, parser, monkeypatch):
    mod = __import__(module)
    real = mod.flags.assign_flags
    monkeypatch.setattr(mod.flags, "assign_flags", lambda df, table: real(df, table).assign(status_flag="Z"))
    with pytest.raises(ParseError, match="Tier-1 validation failed"):
        getattr(mod, parser)()


GDP_BROKEN = """
import sys
sys.path[:0] = [{parsers!r}, {pipeline!r}, {src!r}]
import parse_cosit_gdp, source_io
real = parse_cosit_gdp.flags.assign_flags
def broken(df, table):
    df = real(df, table)
    i = df.index[df["series_id"] == "gdp.real_nonoil"][0]
    df.loc[i, "value"] += 5
    return df
parse_cosit_gdp.flags.assign_flags = broken
try:
    parse_cosit_gdp.parse_cosit_gdp(seed_parquet_path={seed!r}, output_parquet_path={out!r})
except source_io.ParseError as exc:
    print("RAISED", exc)
"""


@pytest.mark.parametrize("flags_", [[], ["-O"]], ids=["normal", "optimised"])
def test_gdp_identity_holds_in_every_mode(flags_, tmp_path):
    script = GDP_BROKEN.format(parsers=str(PARSERS), pipeline=str(REPO_ROOT / "pipeline"), src=str(REPO_ROOT / "src"),
                               seed=str(tmp_path / "s.parquet"), out=str(tmp_path / "o.parquet"))
    proc = subprocess.run([sys.executable, *flags_, "-c", script], capture_output=True, text=True, encoding="utf-8")
    assert "RAISED" in proc.stdout and "gdp.real = oil + non-oil" in proc.stdout, proc.stdout + proc.stderr
    assert not (tmp_path / "o.parquet").exists()


def test_no_switch_off_checks_or_guesses():
    """No parser asserts, ignores a schema check, reads the active sheet, de-duplicates or coerces silently."""
    offending = []
    for path in sorted(PARSERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            where = f"{path.name}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Assert):
                offending.append(f"{where} assert")
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                    and getattr(node.value.func, "id", getattr(node.value.func, "attr", "")) == "validate_dataframe":
                offending.append(f"{where} validate_dataframe result ignored")
            if isinstance(node, ast.Attribute) and node.attr == "active":
                offending.append(f"{where} .active")
            if isinstance(node, ast.Attribute) and node.attr == "drop_duplicates" and path.name != "source_io.py":
                offending.append(f"{where} drop_duplicates")
            if isinstance(node, ast.keyword) and node.arg == "errors" and getattr(node.value, "value", None) == "coerce":
                offending.append(f"{where} errors='coerce'")
            if path.name == "parse_cbi_bop.py" and isinstance(node, ast.Subscript) and ast.unparse(node.value).endswith(".iloc") \
                    and isinstance(node.slice, ast.Slice) and isinstance(node.slice.lower, ast.Constant):
                offending.append(f"{where} fixed row slice")
    assert offending == []


# =====================================================================
# Duplicates and precedence
# =====================================================================

def _copy_sheet(path, sheet, new, change=None):
    wb = openpyxl.load_workbook(path, data_only=True)
    copy = wb.copy_worksheet(wb[sheet])
    copy.title = new
    if change:
        cell, value = change
        copy[cell] = value
    wb.save(path)


def _bop_2024(raw):
    return raw / "cbi" / "bop" / "bop_2024.xlsx"


def test_identical_duplicate_is_collapsed_and_reported(tmp_path, capsys):
    base = _output("cbi_bop", tmp_path / "base")
    capsys.readouterr()
    out = _output("cbi_bop", tmp_path / "dup", lambda raw, seeds: _copy_sheet(_bop_2024(raw), "BOP Q2", "BOP Q2 copy"))
    pd.testing.assert_frame_equal(base.drop(columns="source_hash"), out.drop(columns="source_hash"))
    text = capsys.readouterr().out
    assert "[DUPLICATE]" in text and "bop.current_account 2024-Q2 x2" in text


def test_conflicting_duplicate_names_both_values(tmp_path):
    def edit(raw, seeds):
        path = _bop_2024(raw)
        cell = _find(path, "BOP Q2", lambda c: c.column == 1 and "current account" in str(c.value).lower())
        _copy_sheet(path, "BOP Q2", "BOP Q2 copy", (f"B{cell[1:]}", 999999.0))
    err = _fails("cbi_bop", tmp_path, edit)
    msg = str(err)
    assert "bop.current_account 2024-Q2" in msg and "999999.0" in msg and "sheet 'BOP Q2'" in msg and "BOP Q2 copy" in msg


def test_fiscal_precedence_reports_disagreement(tmp_path, capsys):
    def seed_2024(raw, seeds):
        path = seeds / "iraq_fiscal_historical.xlsx"
        wb = openpyxl.load_workbook(path)
        ws = wb.worksheets[0]
        header = [c.value for c in ws[1]]
        ws.append([2024 if h == "year" else 1.0 for h in header])
        wb.save(path)
    out = _output("cbi_fiscal_bulletin", tmp_path, seed_2024, table="fiscal_annual.parquet")
    text = capsys.readouterr().out
    assert "[PRECEDENCE] fiscal_annual: cbi_fiscal_bulletin 2 periods, fiscal_seed 20 periods; 7 disagree" in text
    assert "fiscal.revenue_total 2024: bulletin" in text and "seed 1.0" in text
    assert out[(out["date"] == "2024")]["value"].ne(1.0).all()  # the bulletin wins


# =====================================================================
# Daily coverage
# =====================================================================

def _blank_days(path, sheet, year, month, days):
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    header = next(r for r in range(len(df)) if str(year) in str(df.iloc[r, 0])
                  and any(k in str(df.iloc[r, 0]).lower() for k in ["exchange", "date", "price", "market"]))
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet]
    for off in range(1, 35):
        try:
            day = int(df.iloc[header + off, 0])
        except (ValueError, TypeError):
            continue
        if day in days:
            ws.cell(header + off + 1, month + 1).value = None
    wb.save(path)


def test_long_daily_gap_stops_the_parser(tmp_path):
    def edit(raw, seeds):
        _blank_days(_official(raw), "Daily Price basis", 2019, 6, set(range(1, 22)))
    err = _fails("cbi_exchange_rates", tmp_path, edit)
    assert "fx.official" in str(err) and "2019-05" in str(err) and "days without a value" in str(err)


def test_listed_gaps_pass_and_stale_or_missing_entries_fail(tmp_path, monkeypatch):
    gaps = yaml.safe_load(source_io.DAILY_GAPS_PATH.read_text(encoding="utf-8"))["gaps"]
    path = tmp_path / "gaps.yaml"

    def use(entries):
        path.write_text(yaml.safe_dump({"gaps": entries}), encoding="utf-8")
        source_io._load_list.cache_clear()
        monkeypatch.setattr(source_io, "DAILY_GAPS_PATH", path)

    use(gaps[1:])
    with pytest.raises(ParseError, match="not listed in daily_gaps.yaml"):
        _output("cbi_exchange_rates", tmp_path / "a")
    use(gaps + [{"series": "fx.official", "from": "2010-01-01", "to": "2010-02-01", "reason": "r", "reviewed": "x"}])
    with pytest.raises(ParseError, match="no such gap"):
        _output("cbi_exchange_rates", tmp_path / "b")
    source_io._load_list.cache_clear()
