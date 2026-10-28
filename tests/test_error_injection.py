"""
tests.test_error_injection
==========================
Errors injected into the published data are reported by the gate.

For every ruled series, 20 random periods (fixed seed) receive an error, one at a time.
Periods next to a B-flagged break, and periods the unmodified data already flag (a real event),
are skipped: an error there cannot be told apart.

- every series: x10 and x0.1 are reported 100% of the time. For series that can be zero or
  negative (a scaled jump measure), this applies where |value| >= 1/4 of the series' median
  |value|, the whole table is validated (accounting identities count) together with the
  sanity checks, and bop.capital_account, bop.financial_account and bop.reserve_assets_change are
  excluded (no identity covers them: the known gap);
- stable series (monthly CPI and the money and interest-rate series, `cpi*` and `money.*`):
  at least 95% of x1.5 and x0.5 errors are reported, over the group;
- every series: a move of 1.5 x its jump limit (10 x the typical change for statistical rules)
  is reported at least 95% of the time.

For positive series the injected row and its neighbours are validated first (every per-series
check is local); a scale error they miss is then checked on the whole table, with the identities
and sanity checks.
"""

import numpy as np
import pandas as pd
import pytest

import validate

N = 20
CHECKS = {"envelope", "sign", "jump", "scale_shift"}
RULES = validate.load_rules()["series"]
SCALE_GAP = {"bop.capital_account", "bop.financial_account", "bop.reserve_assets_change"}
STABLE = ("cpi", "money.")


class Gate:
    """Warnings and errors at given periods, before and after an injection."""

    def __init__(self, tables):
        self.tables = tables

    def window(self, g, i, sid, new_value):
        window = g.iloc[i - 1:i + 2].copy()
        periods = {str(g.at[i, "date"]), str(g.at[i + 1, "date"])}

        def seen(df):
            _, warnings = validate.validate_tier2_details(df, "t")
            return {(w.check, p) for w in warnings if w.series == sid and w.check in CHECKS
                    for p in w.periods if p in periods}

        before = seen(window)
        if before:
            return None
        window.loc[i, "value"] = new_value
        return bool(seen(window))

    def table(self, name, row, sid, new_value):
        df = self.tables[name]
        period = str(df.at[row, "date"])

        def seen(frame):
            errors, warnings = validate.validate_tier2_details(frame, name)
            frames = {**self.tables, name: frame}
            found = {e for e in errors if period in e}
            found |= {(w.check, w.series) for w in warnings if w.series == sid and period in w.periods}
            found |= {(w.check, w.series) for w in validate.sanity_warnings(frames) if period in w.periods}
            return found

        before = seen(df)
        changed = df.copy()
        changed.loc[row, "value"] = new_value
        return bool(seen(changed) - before)


@pytest.fixture(scope="module")
def results(garden_tables):
    """{(sid, kind): (reported, injected)} for every series and error kind."""
    gate = Gate(garden_tables)
    rng = np.random.default_rng(13)
    out = {}
    for name, df in sorted(garden_tables.items()):
        for sid, g in sorted(df.dropna(subset=["value"]).groupby("series_id"), key=lambda x: x[0]):
            rule = RULES.get(sid)
            if rule is None or rule.get("exempt") or len(g) < 3:
                continue
            g = g.sort_values("date", kind="mergesort")
            rows = g.index.to_numpy()  # positions in the table, for whole-table checks
            g = g.reset_index(drop=True)
            flags = g["status_flag"].astype(str).to_numpy()
            ok = [i for i in range(1, len(g) - 1) if "B" not in flags[i - 1:i + 2]]
            picks = sorted(int(i) for i in rng.choice(ok, size=min(N, len(ok)), replace=False)) if ok else []
            values = g["value"].to_numpy(dtype=float)
            median_abs = float(np.median(np.abs(values)))
            jump = rule["jump"]
            signed = jump["measure"] == "scaled"
            kinds = ["limit"] + ([] if sid in SCALE_GAP else ["x10", "x0.1"]) + (["x1.5", "x0.5"] if sid.startswith(STABLE) else [])
            for kind in kinds:
                hit = n = 0
                for i in picks:
                    x, prev = values[i], values[i - 1]
                    if kind == "limit":
                        sign = 1 if i % 2 else -1
                        if jump["measure"] == "log":
                            new = prev * np.exp(sign * 1.5 * jump["threshold"])
                        else:
                            new = prev + sign * 1.5 * jump["threshold"] * jump["scale"]
                        found = gate.window(g, i, sid, new)
                    elif signed:
                        if abs(x) < median_abs / 4:
                            continue
                        found = gate.table(name, rows[i], sid, x * float(kind[1:]))
                    else:
                        found = gate.window(g, i, sid, x * float(kind[1:]))
                        if found is False:  # not visible locally: an identity or sanity check may see it
                            found = gate.table(name, rows[i], sid, x * float(kind[1:]))
                    if found is None:
                        continue
                    n += 1
                    hit += found
                out[(sid, kind)] = (hit, n)
    return out


def test_scale_errors_are_always_reported(results):
    assert len({k[0] for k in results}) == 62
    misses = {k: v for k, v in results.items() if k[1] in ("x10", "x0.1") and v[0] < v[1]}
    assert not misses


def test_moderate_errors_on_stable_series_are_reported(results):
    stable = {k[0] for k in results if k[1] == "x1.5"}
    assert {"cpi_headline", "cpi_core", "money.m2", "money.policy_rate"} <= stable
    for kind in ("x1.5", "x0.5"):
        hit = sum(v[0] for k, v in results.items() if k[1] == kind)
        n = sum(v[1] for k, v in results.items() if k[1] == kind)
        worst = sorted((v[0] / v[1], k[0]) for k, v in results.items() if k[1] == kind and v[1])[:3]
        assert hit / n >= 0.95, (kind, hit, n, worst)


def test_moves_beyond_the_limit_are_reported(results):
    misses = {k: v for k, v in results.items() if k[1] == "limit" and v[1] and v[0] / v[1] < 0.95}
    assert not misses
