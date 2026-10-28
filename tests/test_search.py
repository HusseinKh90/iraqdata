"""
tests.test_search
=================
Bilingual search returns the expected core series in the top 5,
ranks title and ID matches above description-only matches, and normalises
Arabic spelling variants.
"""

import re

import pandas as pd
import pytest

import iraqdata.catalog as cat

RESULT_COLUMNS = ["series_id", "name_en", "name_ar", "category", "frequency", "unit", "start_date", "table", "source",
                  "origin", "official", "status"]


def _top5(query: str) -> list[str]:
    return cat.search(query)["series_id"].head(5).tolist()


@pytest.mark.parametrize(
    "query, expected",
    [
        ("inflation", {"cpi_headline"}),
        ("oil", {"oil_price_brent", "crude_production_direct"}),
        ("دينار", {"parallel_rate_iraq"}),
    ],
)
def test_expected_core_series_in_top5(query, expected):
    assert expected <= set(_top5(query)), _top5(query)


def test_central_bank_query_returns_cbi_series_in_top5():
    top = cat.search("مركزي").head(5)
    assert top["source"].str.contains("Central Bank of Iraq").any(), top["series_id"].tolist()


def test_whole_word_matches_rank_above_partial_and_description_matches():
    results = cat.search("oil")["series_id"].tolist()
    entries = {s["series_id"]: s for s in cat.get_catalog()["series"]}
    aliases: dict[str, list[str]] = {}
    for alias, sid in cat.ALIASES.items():
        aliases.setdefault(sid, []).append(alias)

    def has_whole_word(sid: str) -> bool:
        fields = [sid, *aliases.get(sid, []), entries[sid].get("name_en", ""), entries[sid].get("name_ar", "")]
        return any("oil" in re.split(r"[^\w]+", f.lower()) for f in fields)

    anchor = results.index("crude_production_direct")
    weaker = [sid for sid in results if not has_whole_word(sid)]
    assert weaker, "expected some partial or description-only matches for 'oil'"
    assert all(results.index(sid) > anchor for sid in weaker)


@pytest.mark.parametrize(
    "variant, plain",
    [
        ("مركزى", "مركزي"),   # alef maqsura
        ("دِينار", "دينار"),  # kasra diacritic
        ("دينـار", "دينار"),  # tatweel
    ],
)
def test_arabic_normalisation(variant, plain):
    assert cat.search(variant)["series_id"].tolist() == cat.search(plain)["series_id"].tolist()


def test_search_is_deterministic():
    pd.testing.assert_frame_equal(cat.search("oil"), cat.search("oil"))


def test_no_match_returns_empty_frame_with_columns():
    df = cat.search("zzzz")
    assert df.empty
    assert list(df.columns) == RESULT_COLUMNS


def test_empty_query_lists_all_series():
    pd.testing.assert_frame_equal(cat.search(""), cat.list_series())
