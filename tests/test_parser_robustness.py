"""
Parser robustness.

Each spreadsheet parser runs on copies of its input with a row inserted, its sheets renamed, a
label rewritten and formula cells stripped of their cached values. Every parser also runs on a
missing, an empty and a corrupt copy of its primary input. Each run is classified:

    correct          output identical to the unmutated sandbox run
    clear_error      an explicit `raise` in parser or runner code whose message names the input
                     file, sheet or label
    unhandled_error  any other exception (raised inside pandas, openpyxl, zipfile, json, open(),
                     an assert, ...), even if its message names the file
    silent_shift     no exception, but the output differs (source_hash excluded: a rewritten
                     input file has new bytes, so its hash is expected to change)

Every outcome that is not `correct` or `clear_error` must be listed in the robustness section
of pipeline/metadata/known_findings.yaml, and every listed entry must still be measured.
This module only measures; the checks themselves live in pipeline/parsers/source_io.py.

Layout mutations load the workbook with data_only=True, so formulas are replaced by their
cached values before saving; otherwise every mutation would look like a silent shift.
"""

import ast
import random
import re
import shutil
import traceback
import warnings
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest
import yaml

import run_parsers
from conftest import METADATA_DIR, REPO_ROOT, block_network

PARSERS_DIR = REPO_ROOT / "pipeline" / "parsers"
RUN_PARSERS = REPO_ROOT / "pipeline" / "run_parsers.py"
RAW = REPO_ROOT / "pipeline" / "raw"
SEEDS = REPO_ROOT / "pipeline" / "seeds"

with open(REPO_ROOT / "tests" / "fixtures" / "parser_mutations.yaml", encoding="utf-8") as _f:
    MUTATIONS = yaml.safe_load(_f)
SPREADSHEET = MUTATIONS["spreadsheet"]
BAD_INPUT = MUTATIONS["bad_input"]
LAYOUT_KINDS = ["row_inserted", "sheet_renamed", "label_changed", "formula_no_cache"]
BAD_KINDS = ["missing", "empty", "corrupt"]
OUTCOMES = {"correct", "clear_error", "unhandled_error", "silent_shift"}
NOT_REGISTERED = {"correct", "clear_error"}


# =====================================================================
# Variants
# =====================================================================

def _load(path, data_only):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, data_only=data_only)


def make_variant(src: Path, kind: str, spec: dict, out: Path) -> None:
    """Write a mutated copy of `src` to `out` (not called for `missing`)."""
    if kind == "empty":
        out.write_bytes(b"")
        return
    if kind == "corrupt":
        out.write_bytes(random.Random(0).randbytes(src.stat().st_size))
        return
    wb = _load(src, data_only=(kind != "formula_no_cache"))
    if kind == "row_inserted":
        for name in spec["sheets"]:
            ws = wb[name]
            ws.insert_rows(ws.min_row)
    elif kind == "sheet_renamed":
        for name in spec["sheets"]:
            wb[name].title = f"{name}_x"
    elif kind == "label_changed":
        wb[spec["label"]["sheet"]][spec["label"]["cell"]] = spec["label"]["new_text"]
    elif kind not in ("formula_no_cache", "resaved"):
        raise ValueError(kind)
    wb.save(out)


def _dest(path: Path, raw_root: Path, seeds_root: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(RAW.resolve()):
        return raw_root / path.relative_to(RAW.resolve())
    return seeds_root / path.relative_to(SEEDS.resolve())


# =====================================================================
# Running and classifying
# =====================================================================

def classify_error(exc: BaseException, names: list) -> str:
    last = traceback.extract_tb(exc.__traceback__)[-1]
    where = Path(last.filename).resolve()
    # a parser, a shared parser helper (e.g. transcription.py) or run_parsers.py
    in_pipeline = where.parent == PARSERS_DIR.resolve() or where == RUN_PARSERS.resolve()
    explicit = (last.line or "").lstrip().startswith("raise")
    message = str(exc).lower()
    if in_pipeline and explicit and any(n.lower() in message for n in names):
        return "clear_error"
    return "unhandled_error"


def _outputs(spec, out: Path):
    return [out / n for n in spec.outputs] + [out / "seeds" / n for n in spec.seed_outputs]


def run_variant(parser: str, input_rel, kind, variant, deps: Path, work: Path):
    """
    Run one parser on a copy of its own inputs, with `input_rel` replaced by `variant` (or
    deleted for `missing`; nothing replaced when `input_rel` is None). Outputs of `after`
    dependencies are copied from `deps`. Returns (exception or None, output folder).
    """
    spec = run_parsers.BY_NAME[parser]
    raw_root, seeds_root, out = work / "raw", work / "seeds_in", work / "out"
    (out / "seeds").mkdir(parents=True)
    for glob in spec.inputs:
        for p in REPO_ROOT.glob(glob):
            dest = _dest(p, raw_root, seeds_root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    for dep in spec.after:
        for name in run_parsers.BY_NAME[dep].outputs:
            shutil.copy2(deps / name, out / name)

    if input_rel is not None:
        target = _dest(REPO_ROOT / input_rel, raw_root, seeds_root)
        if kind == "missing":
            target.unlink()
        elif variant is not None:
            shutil.copy2(variant, target)

    with block_network():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                spec.run(raw_root, seeds_root, out, out / "seeds")
        except Exception as exc:
            return exc, out
    return None, out


def same_content(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """
    Equal outputs, ignoring source_hash (a rewritten input has new bytes, so a new hash is
    expected) and float noise of one unit in the last place (openpyxl re-saves cached values
    with slightly fewer digits). A shifted row moves values by far more than 1e-12 relative.
    """
    a, b = a.drop(columns="source_hash"), b.drop(columns="source_hash")
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        return False
    others = [c for c in a.columns if c != "value"]
    if not a[others].reset_index(drop=True).equals(b[others].reset_index(drop=True)):
        return False
    return bool(np.allclose(a["value"].to_numpy(), b["value"].to_numpy(), rtol=1e-12, atol=0.0, equal_nan=True))


def classify(parser, input_rel, kind, variant, deps, baseline, work) -> tuple:
    """Run one mutation and classify it against the parser's unmutated baseline output."""
    exc, out = run_variant(parser, input_rel, kind, variant, deps, work)
    if exc is not None:
        names = [Path(input_rel).name] + SPREADSHEET.get(parser, {}).get("label_words", [])
        # a dated input found by pattern (transcription records) is named by its undated stem when missing
        undated = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", Path(input_rel).stem)
        if undated != Path(input_rel).stem:
            names.append(undated)
        return classify_error(exc, names), f"{type(exc).__name__}: {exc}"[:200]
    spec = run_parsers.BY_NAME[parser]
    for produced, base in zip(_outputs(spec, out), _outputs(spec, baseline)):
        if not produced.exists() or not same_content(pd.read_parquet(produced), pd.read_parquet(base)):
            return "silent_shift", f"{produced.name} differs from the unmutated run"
    return "correct", ""


@pytest.fixture(scope="session")
def baselines(sandbox_runs, tmp_path_factory):
    """Each parser run alone on unmutated copies of its inputs, the same way as the mutations."""
    out = {}
    for parser in run_parsers.BY_NAME:
        exc, folder = run_variant(parser, None, None, None, sandbox_runs.run1, tmp_path_factory.mktemp(f"base_{parser}"))
        assert exc is None, f"{parser} failed on unmutated inputs: {exc}"
        out[parser] = folder
    return out


@pytest.fixture(scope="session")
def variant_files(tmp_path_factory):
    """Mutated workbooks, built once and shared (the two KFI parsers reuse layout variants)."""
    folder = tmp_path_factory.mktemp("variants")
    cache = {}

    def get(parser: str, input_rel: str, kind: str):
        if kind == "missing":
            return None
        key = (input_rel, kind, parser if kind == "label_changed" else "")
        if key not in cache:
            src = REPO_ROOT / input_rel
            out = folder / f"{len(cache):03d}_{kind}{src.suffix}"
            make_variant(src, kind, SPREADSHEET.get(parser, {}), out)
            cache[key] = out
        return cache[key]

    return get


@pytest.fixture(scope="session")
def measured(sandbox_runs, baselines, variant_files, tmp_path_factory):
    """All 57 robustness runs: 6 spreadsheet parsers x 4 layout mutations + 11 parsers x 3 bad inputs."""
    plan = [(parser, spec["input"], kind) for parser, spec in SPREADSHEET.items() for kind in LAYOUT_KINDS]
    plan += [(parser, input_rel, kind) for parser, input_rel in BAD_INPUT.items() for kind in BAD_KINDS]
    results = []
    for parser, input_rel, kind in plan:
        outcome, detail = classify(parser, input_rel, kind, variant_files(parser, input_rel, kind),
                                   sandbox_runs.run1, baselines[parser], tmp_path_factory.mktemp(f"{parser}_{kind}"))
        results.append({"parser": parser, "input": input_rel, "mutation": kind, "outcome": outcome, "detail": detail})
    return results


@pytest.fixture(scope="module")
def register():
    with open(METADATA_DIR / "known_findings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _as_yaml(items) -> str:
    return yaml.safe_dump([{k: v for k, v in i.items() if k != "detail"} for i in items],
                          allow_unicode=True, sort_keys=False, width=1000)


# =====================================================================
# Tests
# =====================================================================

@pytest.mark.parametrize("parser", sorted(SPREADSHEET))
def test_resave_alone_changes_nothing(parser, sandbox_runs, baselines, tmp_path):
    """Harness check: re-saving the workbook (data_only=True) without a change keeps the output."""
    src = REPO_ROOT / SPREADSHEET[parser]["input"]
    resaved = tmp_path / f"resaved{src.suffix}"
    make_variant(src, "resaved", SPREADSHEET[parser], resaved)
    outcome, detail = classify(parser, SPREADSHEET[parser]["input"], "resaved", resaved,
                               sandbox_runs.run1, baselines[parser], tmp_path / "work")
    assert outcome == "correct", detail


def test_every_outcome_classified(measured):
    """All 57 runs happened and each has one of the four outcomes."""
    assert len(measured) == len(SPREADSHEET) * len(LAYOUT_KINDS) + len(BAD_INPUT) * len(BAD_KINDS) == 57
    assert {m["outcome"] for m in measured} <= OUTCOMES


def test_robustness_outcomes_match_register(measured, register):
    """Every non-clear outcome is registered, and every registered one still occurs."""
    key = lambda e: (e["parser"], e["input"], e["mutation"], e["outcome"])
    found = {key(m): m for m in measured if m["outcome"] not in NOT_REGISTERED}
    listed = {key(e): e for e in register.get("robustness") or [] if e["mutation"] != "non_atomic_write"}
    missing = [found[k] for k in sorted(set(found) - set(listed))]
    stale = [listed[k] for k in sorted(set(listed) - set(found))]
    assert not missing and not stale, (
        f"Unregistered outcomes (add to known_findings.yaml robustness):\n{_as_yaml(missing)}\n"
        f"Stale register entries (no longer measured):\n{_as_yaml(stale)}\n"
        f"Details: {[(m['parser'], m['mutation'], m['detail']) for m in missing]}"
    )


def _is_atomic(path: Path) -> bool:
    """
    A parser writes atomically if it writes to a temporary file and then renames it, or
    writes only through source_io.write_table, which does that.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    targets = [ast.unparse(node.args[0]) for node in calls if node.func.attr == "to_parquet" and node.args]
    if not targets:
        return any(node.func.attr == "write_table" and ast.unparse(node.func.value) == "source_io" for node in calls)
    renames = any(node.func.attr in {"replace", "rename"} for node in calls)
    return renames and all(re.search(r"tmp|part", t, re.I) for t in targets)


def test_atomic_writes_recorded(register):
    """Every parser that writes its outputs non-atomically is registered."""
    measured_set = {p.stem for p in PARSERS_DIR.glob("parse_*.py") if not _is_atomic(p)}
    registered = {Path(e["input"]).stem for e in register.get("robustness") or []
                  if e["mutation"] == "non_atomic_write" and e["outcome"] == "not_atomic"}
    assert measured_set == registered


# --- number formats and formula caches in the workbooks the parsers read

ARABIC_INDIC = re.compile(r"[٠-٩۰-۹]")
NUMBERLIKE_ARABIC = re.compile(r"^[\s\-٠-٩۰-۹٫٬.,]+$")
THOUSANDS = re.compile(r"^\s*-?\d{1,3}(,\d{3})+(\.\d+)?\s*$")
FOOTNOTE = re.compile(r"^\s*-?[\d.,]+\s*[*†‡]+\s*$")


def scan_workbook(path: Path, sheets: list) -> dict:
    with_formulas, cached = _load(path, data_only=False), _load(path, data_only=True)
    counts = {"arabic_indic_digits": 0, "thousands_separators": 0, "footnote_markers": 0,
              "formulas_without_cache": 0}
    for name in sheets:
        ws_f, ws_v = with_formulas[name], cached[name]
        for row in ws_f.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    if ws_v[cell.coordinate].value is None:
                        counts["formulas_without_cache"] += 1
                elif isinstance(cell.value, str):
                    text = cell.value
                    if NUMBERLIKE_ARABIC.match(text) and ARABIC_INDIC.search(text):
                        counts["arabic_indic_digits"] += 1
                    if THOUSANDS.match(text):
                        counts["thousands_separators"] += 1
                    if FOOTNOTE.match(text):
                        counts["footnote_markers"] += 1
    return counts


def test_cell_text_conventions(register):
    """Measured counts per parser equal the cell_text_scan block of the register."""
    measured_scan = {}
    by_input = {}
    for parser, spec in sorted(SPREADSHEET.items()):
        key = (spec["input"], tuple(spec["sheets"]))
        if key not in by_input:
            by_input[key] = scan_workbook(REPO_ROOT / spec["input"], spec["sheets"])
        measured_scan[parser] = {"input": spec["input"], **by_input[key]}
    assert measured_scan == register.get("cell_text_scan"), _as_yaml([measured_scan])
