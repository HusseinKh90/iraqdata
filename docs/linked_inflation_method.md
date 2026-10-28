# Linked CPI Method: `cpi_headline` and `cpi_core`

## 1. Status and scope

The Central Bank of Iraq (CBI) publishes Iraq's consumer price index on four bases: 1993 = 100,
2007 = 100, 2012 = 100 and 2022 = 100. iraqdata publishes all four unchanged as
`cpi.headline_<base>` and `cpi.core_<base>`. It also builds one continuous series for each
measure, `cpi_headline` and `cpi_core`, by linking the bases.

**The linked series are an iraqdata construction, not an official COSIT or CBI series.** They are
built from official series, and the catalog marks them `official: false`. Use the native base series when
you need the official figures for a given period. Section 11 lists what the linked series cannot do, and
section 13 explains the terms used here.

> **Warning: `cpi_core` before 2010 does not measure the same thing as `cpi_core` from 2010.** The core
> basket changes definition at the first splice (section 10), so a trend read across 2009 to 2010 is partly
> the change of definition. Use `cpi_core` for trends from 2010-01 on, or use the native base series for
> earlier periods. The linked headline series has no such change.

## 2. Sources and coverage

**Data source (archived).** All eight native series are read from the CBI Key Financial
Indicators workbook: the newest dated copy, `pipeline/raw/cbi/cbi_key_financial_indicators_<date>.xlsx`, when
there is one, otherwise the earlier `pipeline/raw/cbi/key_financial_indicators.xlsx` (`run_parsers.py`
chooses). The workbook's first row names the date it was published. Each native value is published rounded to
4 decimals, from 2004-01 on: the workbook also holds December 2003 for the 1993 base, which is not published.
Its own labels give the core definitions:

- **1993 base:** the core index "Exclude(s) F&L and T&C" (fuel & lighting, and transport &
  communications), row label in cell B4.
- **2007, 2012 and 2022 bases:** the workbook's note 7 (cell B125) reads "exclude the fruit &
  vegetables and Kerosene & LPG".

**Methodology sources (cited, not archived).** The documents below are public. They were read on
2026-10-26, but they are **not archived in this repository**, so they may change or disappear.

| Topic | What the source says | Source |
|-------|----------------------|--------|
| Compiler | COSIT (Central Organization for Statistics and Information Technology) compiles the CPI; the CBI republishes it. | ILO (2013), *Iraq: Consumer Price Index – description*, https://webapps.ilo.org/ilostat-files/SSM/SSM1_NEW/E/IRQ_CPI_Descriptions%20-2013.pdf |
| Geographic coverage (2007 base) | Weights and price collection are "nation-wide". The index covers "all households in the country, including the three governorates of Kurdistan region"; national figures aggregate 18 governorates. | ILO (2013), as above |
| Population (2007 base) | "Resident households of nationals." | ILO (2013), as above |
| Weights (2007 base) | From the 2007 Iraqi Household Social and Economic Survey (IHSES); weights updated every 3–5 years. Classification: COICOP, 12 major groups. | ILO (2013), as above |
| Formulas (2007 base) | Elementary indices: ratio of geometric mean prices (Jevons). Higher levels: Laspeyres. | ILO (2013), as above |
| Weights and formula (2022 base) | Kurdistan Region Statistics Office (KRSO) states that Iraq's weights were updated for 2022, replacing weights based on the 2012 survey, using the 2017–2018 SWIFT survey. It also says main and subgroup indices moved from arithmetic to geometric means, with month-on-month chaining. This is KRSO's statement, not COSIT's. | KRSO (April 2024), *Consumer Price Index (CPI) in Kurdistan Region, Feb 2024*, https://krso.gov.krd/content/upload/1/root/cpi-report-2-2024-en.pdf |
| 2022-base publication | COSIT publishes national CPI and core indices on 100 = 2022 with division weights (Table 7/1), and separate indices for the Kurdistan, Middle and South regions. | COSIT (2025), *Annual Abstract of Statistics 2024*, Part Seven "Index Numbers", https://www.cosit.gov.iq/documents/AAS2024/07.pdf |

**Not documented** (no source found):

- urban/rural coverage for any base;
- COSIT's own statement of whether the 2012 and 2022 national indices include the Kurdistan Region;
- the 1993 base's coverage, weights and formulas;
- the 2012 base's survey and formulas, apart from KRSO's mention of the 2012 survey;
- the 2022 base's division weights in machine-readable form. Table 7/1 does not extract reliably,
  so no weight is quoted here.

## 3. Method

The linked series uses a **December one-month overlap**, as described in the IMF/ILO/Eurostat/
UNECE/OECD/World Bank *Consumer Price Index Manual: Concepts and Methods* (2020), Chapter 9
"Updating CPI Weights and Linking New to Previous CPI Series", section "Linking the Previous CPI to
the New Price Index Reference Period", paragraphs 9.70–9.77
(https://www.imf.org/-/media/files/data/cpi/cpi-manual-concepts-and-methods.pdf). The title and chapter
were confirmed; **the paragraph numbers, and the Manual's remark quoted in section 11, have not been checked
against the Manual** and should be treated as unverified until they are.

**Why December, and why there is no choice of year.** The CBI publishes each new base for the twelve months
before it replaces the previous one (2009, 2015 and 2023), so each pair of bases has one overlap year. The
series therefore links in December of that year and switches to the new base the following January, which is
when the publisher itself changed base. December is the usual link month in chain-linked consumer price
indices; section 9 shows how much the choice matters here.

For each pair of consecutive bases (old, new):

1. **Overlap year:** the last calendar year in which both bases have all 12 months (for the data, the only one).
2. **Old base use:** the old base is used through December of the overlap year.
3. **Switch:** the series switches to the new base the following January (the *splice month*).
4. **Step factor:** `new(December of the overlap year) / old(December of the overlap year)`.
5. **Chain factor:** the product of the step factors from that base down to the 2022 base. The
   2022 base's chain factor is 1.
6. **Linked value:** `linked(t) = base(t) × chain factor(base(t))`, where `base(t)` is the base in
   use in month `t`.

As a result:

- **Overlap year:** month-on-month and year-on-year rates in every month of an overlap year equal the old
  base's official rates (to the published 4 decimals). This follows the Manual's §9.77: 12-month rates come
  from the old series through the link month.
- **Splice month:** the month-on-month rate at each splice month equals the new base's official
  rate (to the same precision).
- **The year after a splice:** year-on-year rates compare a new-base month with an old-base month a
  year earlier, so they can differ from the new base's official rate. Section 8 lists every one of
  these months.

The computation lives in `pipeline/cpi_linking.py`. The parser (`pipeline/parsers/parse_cbi_cpi.py`),
the generator of the numbers below (`pipeline/docs_cpi.py`) and the tests all share it. It links
the published native values, rounded to 4 decimals, so anyone can recompute every linked value
from the published native series.

An annual-overlap method is not used. It would switch base each January of the overlap year and
scale by the mean of the 12 monthly ratios, which distorts the switch months.

<!-- cpi-linking:begin -->

_Generated by `pipeline/docs_cpi.py` from the published native series; do not edit by hand._

## 4. Factors and splices

| Series | Old base | New base | Overlap year | Step factor | Chain factor to the 2022 base | Last month on old base | Splice month |
|--------|----------|----------|--------------|-------------|-------------------------------|------------------------|--------------|
| `cpi_headline` | 1993 | 2007 | 2009 | 0.005022312 | 0.002978604 | 2009-12 | 2010-01 |
| `cpi_headline` | 2007 | 2012 | 2015 | 0.6938911 | 0.5930741 | 2015-12 | 2016-01 |
| `cpi_headline` | 2012 | 2022 | 2023 | 0.8547078 | 0.8547078 | 2023-12 | 2024-01 |
| `cpi_core` | 1993 | 2007 | 2009 | 0.006175926 | 0.003604065 | 2009-12 | 2010-01 |
| `cpi_core` | 2007 | 2012 | 2015 | 0.6912257 | 0.5835668 | 2015-12 | 2016-01 |
| `cpi_core` | 2012 | 2022 | 2023 | 0.8442492 | 0.8442492 | 2023-12 | 2024-01 |

## 5. Continuity checks

Month-on-month change at each splice month, linked series against the new base, and the largest difference between the linked series and the old base over every month of the overlap year (month-on-month and year-on-year rates).

| Series | Splice month | Linked MoM | New-base MoM | Largest overlap-year difference (pp) |
|--------|--------------|------------|--------------|--------------------------------------|
| `cpi_headline` | 2010-01 | -0.40% | -0.40% | 0.00 |
| `cpi_headline` | 2016-01 | +0.29% | +0.29% | 0.00 |
| `cpi_headline` | 2024-01 | +0.09% | +0.09% | 0.00 |
| `cpi_core` | 2010-01 | +0.08% | +0.08% | 0.00 |
| `cpi_core` | 2016-01 | +1.55% | +1.55% | 0.00 |
| `cpi_core` | 2024-01 | +0.28% | +0.28% | 0.00 |

## 6. Reference period

The newest base is not rescaled, so the linked series is on the 2022 base's scale but its 2022 average is not exactly 100:

| Series | Average over 2022 |
|--------|-------------------|
| `cpi_headline` | 100.008 |
| `cpi_core` | 100.015 |

## 7. Status flags

| Series | Months flagged `B` (break) |
|--------|----------------------------|
| `cpi_headline` | 2010-01, 2016-01, 2024-01 |
| `cpi_core` | 2010-01, 2016-01, 2024-01 |

## 8. Post-splice year-on-year gaps

Linked year-on-year inflation against the new base's official rate for the 12 months from each splice month. Gaps above the tolerance of 0.5 percentage points are exceptions (see Limitations).

`cpi_headline`: 17 of 36 months above the tolerance.

| Month | Linked YoY | New-base YoY | Gap (pp) | Exception |
|-------|------------|--------------|----------|-----------|
| 2010-01 | -2.28% | +2.24% | 4.51 | yes |
| 2010-02 | -1.15% | +2.49% | 3.64 | yes |
| 2010-03 | +3.54% | +3.43% | 0.12 |  |
| 2010-04 | +4.46% | +2.91% | 1.55 | yes |
| 2010-05 | +5.01% | +1.57% | 3.44 | yes |
| 2010-06 | +3.28% | +1.66% | 1.63 | yes |
| 2010-07 | +4.00% | +0.57% | 3.43 | yes |
| 2010-08 | +3.50% | +1.69% | 1.81 | yes |
| 2010-09 | +3.47% | +2.66% | 0.81 | yes |
| 2010-10 | +5.31% | +3.56% | 1.75 | yes |
| 2010-11 | +5.01% | +3.05% | 1.96 | yes |
| 2010-12 | +3.31% | +3.31% | 0.00 |  |
| 2016-01 | +3.16% | -0.95% | 4.11 | yes |
| 2016-02 | +3.40% | +1.55% | 1.85 | yes |
| 2016-03 | +3.00% | +1.76% | 1.24 | yes |
| 2016-04 | +2.06% | +2.06% | 0.00 |  |
| 2016-05 | +2.04% | +2.47% | 0.43 |  |
| 2016-06 | +1.33% | +0.10% | 1.23 | yes |
| 2016-07 | +0.47% | -0.38% | 0.86 | yes |
| 2016-08 | +0.50% | +0.19% | 0.31 |  |
| 2016-09 | +1.31% | +0.29% | 1.02 | yes |
| 2016-10 | +1.15% | +0.19% | 0.96 | yes |
| 2016-11 | -0.53% | -0.96% | 0.43 |  |
| 2016-12 | -0.67% | -0.67% | 0.00 |  |
| 2024-01 | +0.09% | +0.09% | 0.00 |  |
| 2024-02 | +0.54% | +0.57% | 0.03 |  |
| 2024-03 | +1.57% | +1.63% | 0.06 |  |
| 2024-04 | +3.04% | +3.00% | 0.04 |  |
| 2024-05 | +3.39% | +3.40% | 0.01 |  |
| 2024-06 | +3.58% | +3.57% | 0.01 |  |
| 2024-07 | +3.56% | +3.65% | 0.09 |  |
| 2024-08 | +3.63% | +3.73% | 0.10 |  |
| 2024-09 | +3.05% | +3.06% | 0.00 |  |
| 2024-10 | +2.88% | +2.86% | 0.01 |  |
| 2024-11 | +2.80% | +2.86% | 0.06 |  |
| 2024-12 | +2.66% | +2.66% | 0.00 |  |

`cpi_core`: 12 of 36 months above the tolerance.

| Month | Linked YoY | New-base YoY | Gap (pp) | Exception |
|-------|------------|--------------|----------|-----------|
| 2010-01 | +6.58% | +3.78% | 2.81 | yes |
| 2010-02 | +6.77% | +3.35% | 3.42 | yes |
| 2010-03 | +4.43% | +3.61% | 0.82 | yes |
| 2010-04 | +4.69% | +3.00% | 1.69 | yes |
| 2010-05 | +5.90% | +3.00% | 2.90 | yes |
| 2010-06 | +4.27% | +2.74% | 1.53 | yes |
| 2010-07 | +5.00% | +1.80% | 3.20 | yes |
| 2010-08 | +1.74% | +1.88% | 0.13 |  |
| 2010-09 | +1.71% | +1.87% | 0.16 |  |
| 2010-10 | +4.09% | +3.16% | 0.93 | yes |
| 2010-11 | +4.01% | +3.07% | 0.93 | yes |
| 2010-12 | +3.32% | +3.32% | 0.00 |  |
| 2016-01 | +2.93% | -2.06% | 4.99 | yes |
| 2016-02 | +2.96% | +2.24% | 0.72 | yes |
| 2016-03 | +2.44% | +2.56% | 0.12 |  |
| 2016-04 | +1.67% | +1.86% | 0.19 |  |
| 2016-05 | +1.92% | +2.96% | 1.04 | yes |
| 2016-06 | +1.71% | +1.36% | 0.35 |  |
| 2016-07 | +1.63% | +1.75% | 0.12 |  |
| 2016-08 | +1.54% | +1.84% | 0.30 |  |
| 2016-09 | +1.74% | +1.55% | 0.20 |  |
| 2016-10 | +1.19% | +1.26% | 0.07 |  |
| 2016-11 | +0.84% | +0.68% | 0.17 |  |
| 2016-12 | +1.65% | +1.65% | 0.00 |  |
| 2024-01 | +0.77% | +0.76% | 0.01 |  |
| 2024-02 | +1.64% | +1.62% | 0.01 |  |
| 2024-03 | +2.67% | +2.69% | 0.03 |  |
| 2024-04 | +4.14% | +4.19% | 0.05 |  |
| 2024-05 | +4.08% | +4.08% | 0.00 |  |
| 2024-06 | +3.51% | +3.54% | 0.03 |  |
| 2024-07 | +3.12% | +3.14% | 0.02 |  |
| 2024-08 | +2.79% | +2.85% | 0.06 |  |
| 2024-09 | +2.85% | +2.85% | 0.01 |  |
| 2024-10 | +2.81% | +2.86% | 0.05 |  |
| 2024-11 | +2.30% | +2.28% | 0.02 |  |
| 2024-12 | +2.27% | +2.27% | 0.00 |  |

## 9. Sensitivity to the link month

The new base divided by the old base is not constant through an overlap year: the two measure different baskets. The method uses December's ratio. Linking in another month would move **every level before the splice** (the percentages below apply to that pair; across several pairs they multiply).

| Series | Old → new base | Overlap year | Ratio in January | Ratio in December (used) | Mean of the 12 ratios | Lowest | Highest | Link in January instead | Link at the mean instead |
|--------|----------------|--------------|------------------|--------------------------|-----------------------|--------|---------|-------------------------|-------------------------|
| `cpi_headline` | 1993 → 2007 | 2009 | 0.00480057 | 0.00502231 | 0.00505665 | 0.00480057 | 0.00519343 | -4.42% | +0.68% |
| `cpi_headline` | 2007 → 2012 | 2015 | 0.722678 | 0.693891 | 0.700588 | 0.690996 | 0.722678 | +4.15% | +0.97% |
| `cpi_headline` | 2012 → 2022 | 2023 | 0.854708 | 0.854708 | 0.854513 | 0.853878 | 0.855012 | +0.00% | -0.02% |
| `cpi_core` | 1993 → 2007 | 2009 | 0.00634287 | 0.00617593 | 0.00626554 | 0.00616647 | 0.00638036 | +2.70% | +1.45% |
| `cpi_core` | 2007 → 2012 | 2015 | 0.726409 | 0.691226 | 0.693929 | 0.684246 | 0.726409 | +5.09% | +0.39% |
| `cpi_core` | 2012 → 2022 | 2023 | 0.844302 | 0.844249 | 0.844105 | 0.84375 | 0.844427 | +0.01% | -0.02% |

<!-- cpi-linking:end -->

## 10. Core definition change

The core index changes definition at the 1993 → 2007 splice:

- **1993 base:** excludes fuel & lighting, and transport & communications.
- **2007, 2012 and 2022 bases:** exclude fruit & vegetables, and kerosene & LPG.

So `cpi_core` before the 2010-01 splice measures a different core basket from `cpi_core` after it.
The 2009 step factor mixes the rebase with that definition change. `cpi_core` is kept continuous
and flagged `B` at the splice, so do not read a core trend across 2009–2010 as purely price
movement. This is why the warning at the top of this document recommends `cpi_core` only from 2010-01.

## 11. Limitations

- **The official bases disagree within overlap years.** In each overlap year, the old and new bases
  measure different price movements: different baskets, weights and formulas. So no single-factor
  link can match both bases' official rates in every month. This method keeps the old base's rates
  through the overlap year and the new base's month-on-month rate at the switch.
- **Residual year-on-year gaps after each splice.** In the 12 months from each splice month, linked
  year-on-year inflation compares months on different bases. Section 8 prints every gap, and
  marks the months above the 0.5 percentage-point tolerance as exceptions. Use the native base
  series if you need the official rate for those months.
- **A single link month.** The Manual (§9.72) is quoted as noting that a single overlap period "is not the
  ideal method" when weights are updated infrequently (the quote is unverified, section 3). A change in the
  December seasonal pattern between bases would shift the level of everything before the splice. Section 9
  quantifies this: linking in January instead would move all earlier levels by several percent for the
  1993 to 2007 and the 2007 to 2012 pairs, and by almost nothing for the 2012 to 2022 pair.
- **The tolerance is a convention.** The 0.5 percentage-point tolerance in section 8 is a stated threshold for
  calling a gap an exception, not a statistical bound.
- **Core definition change.** See section 10.
- **"2022 = 100" is approximate.** The 2022 base's first published month is 2023-01, so 2022 itself
  is linked from the 2012 base, and its average is not exactly 100 (section 6). Values from the
  2024-01 splice on equal the official 2022-base figures.
- **Not an official series.** COSIT and the CBI publish the native bases, not this linked series.
- **Coverage is not documented.** Whether each base covers urban and rural households alike, and whether the
  1993 base covers the same governorates as the later ones, is not stated in any document found.
- **Methodology sources are not archived.** The coverage and weights facts in section 2 come from
  public documents read on 2026-10-26 that are not stored in this repository.

## 12. Data vintage, flags and revisions

- **Vintage.** The generated tables come from the native series as published in the repository, which are
  read from the workbook named in section 2. They change only when a native value changes; `pipeline/docs_cpi.py`
  rewrites them, and the test suite fails until it has been run.
- **Provisional months.** The latest 12 months of every CPI series, native and linked, carry status flag `P`;
  the splice months carry `B` (section 7).
- **Revisions.** The CBI revises recent months. If it revises a December that serves as a link month (December
  of 2009, 2015 or 2023 in either base of a pair), the step factor changes and **every linked value before that
  splice moves by the same factor**; the vintage history keeps the earlier values. The native series are not
  affected by anything done here.
- **January 2011.** The workbook's own note (cell B126) says the rise in monthly, annual and core inflation in
  January 2011 came from a new electricity tariff. It is a price change, not an error, and it appears in the
  2007-base series and so in the linked ones.

## 13. Glossary

| Term | Meaning |
|------|---------|
| Base (`2007 = 100`) | A published index whose average level in its base period is 100; a new base replaces the old one when the basket and weights are updated. |
| Basket, weights | The goods and services priced and their shares in household spending. |
| Core inflation | Inflation excluding items that move a lot: for the 1993 base, fuel and lighting and transport and communications; from the 2007 base, fruit and vegetables and kerosene and LPG. |
| COICOP | Classification of Individual Consumption by Purpose, the 12 groups the 2007-base weights use. |
| COSIT | Central Organization for Statistics and Information Technology, which compiles the CPI. |
| CBI | Central Bank of Iraq, which republishes it. |
| F&L, T&C, LPG | Fuel and lighting; transport and communications; liquefied petroleum gas. |
| IHSES | Iraqi Household Socio-Economic Survey, the source of the 2007 weights. |
| Jevons, Laspeyres | The formula for the elementary indices (a ratio of geometric means of prices) and for the higher levels (fixed-basket). |
| KFI | The CBI's Key Financial Indicators workbook, the source of every series here. |
| KRSO | Kurdistan Region Statistics Office. |
| Link, splice | Joining two bases into one series: the old base is scaled to the new one at a link month (December of the overlap year) and the series switches to the new base at the splice month (the following January). |
| MoM, YoY | Change from the previous month; change from the same month a year earlier. |
| Overlap year | A calendar year in which two bases are both published for all 12 months. |
| pp | Percentage points: the difference between two rates. |
| Step factor, chain factor | The ratio of new to old base in the link month; the product of step factors down to the newest base (section 4). |
| SWIFT survey | The 2017–2018 survey KRSO says the 2022 weights use. |
| Status flags `A`, `B`, `P` | Normal value; break in the series (a splice month); provisional (the latest 12 months). |

## 14. Reproducing the numbers

Sections 4–9 are generated:

```bash
python pipeline/docs_cpi.py          # rewrite the generated block
python pipeline/docs_cpi.py --check  # exit 1 if it is out of date
```

`tests/test_cpi_linking.py` recomputes the factors and checks continuity, the flags and this
document.
