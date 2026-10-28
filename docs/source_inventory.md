# Iraq Macro Data Package — Source Inventory

Oct 20, 2026 · @Hussein Khalid

This is the inventory of the package's series: where each comes from and what is known about each source. Where an entry describes something the package does not publish, it says so (*not implemented*); `series.md` lists what is published.

<!-- terms:begin -->

## Terms of reuse by source

Generated from `pipeline/metadata/sources.yaml` by `pipeline/docs_origin.py`; do not edit by hand. The compiled and derived data are licensed CC-BY 4.0; each source's own terms still apply to its data. Cite both the package and the original publisher.

| Source | Publisher | Terms | Licence | Status | Redistribution | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| `bis_lbs`: [Locational Banking Statistics (SDMX API, WS_LBS_D_PUB)](https://data.bis.org) | Bank for International Settlements (BIS) | Open data; attribution required | none stated | Not yet confirmed | To confirm against the BIS terms of use; republished with attribution to the BIS | 2026-10-27 |
| `cbi_bop`: [Balance of Payments Data Archive](https://cbi.iq/page/145) | Central Bank of Iraq (CBI) | No licence stated | none stated | No licence stated | Free public download with no stated terms (no CBI terms of reuse found on cbi.iq, 2026-10-24); republished unchanged in value with attribution to the CBI | 2026-10-24 |
| `cbi_bulletin`: [Monthly Statistical Bulletin](https://cbi.iq/page/122) | Central Bank of Iraq (CBI) | No licence stated | none stated | No licence stated | Free public download with no stated terms (no CBI terms of reuse found on cbi.iq, 2026-10-24); republished unchanged in value with attribution to the CBI | 2026-10-24 |
| `cbi_fx`: [Exchange-rate files (dinar per US dollar)](https://cbi.iq/page/144) | Central Bank of Iraq (CBI) | No licence stated | none stated | No licence stated | Free public download with no stated terms (checked 2026-10-24); republished unchanged in value with attribution to the CBI | 2026-10-24 |
| `cbi_kfi`: [Key Financial Indicators](https://cbi.iq/news/view/94) | Central Bank of Iraq (CBI) | No licence stated | none stated | No licence stated | Free public download with no stated terms (no CBI terms of reuse found on cbi.iq, 2026-10-24); republished unchanged in value with attribution to the CBI | 2026-10-24 |
| `cosit_national_accounts`: [National Accounts (quarterly GDP)](https://cosit.gov.iq/ar/national-accounts/income) | Central Organization for Statistics and Information Technology (COSIT) | Government publication; free download | none stated | Not yet confirmed | To confirm with COSIT; republished with attribution to COSIT | 2026-10-27 |
| `eia_intl`: [International Energy Statistics bulk file (series INTL.57-1-IRQ-TBPD.M)](https://www.eia.gov/opendata/bulk/INTL.zip) | U.S. Energy Information Administration (EIA) | US government open data; free public API | none stated | Not yet confirmed | To confirm against the EIA copyright and reuse page; republished with attribution to the EIA | 2026-10-27 |
| `fred_brent`: [Crude Oil Prices, Brent - Europe (DCOILBRENTEU)](https://fred.stlouisfed.org/series/DCOILBRENTEU) | U.S. Energy Information Administration (EIA), via FRED (Federal Reserve Bank of St. Louis) | US government open data; free public API | none stated | Not yet confirmed | To confirm against the series' copyright note on FRED; republished with attribution to the EIA and FRED | 2026-10-27 |
| `iraq_parallel_fx`: [Iraq-parallel-exchange-rate, data/daily_fx.csv](https://github.com/HusseinKh90/Iraq-parallel-exchange-rate) | Hussein Khalid (Iraq-parallel-exchange-rate repository) | CC-BY 4.0 | CC-BY-4.0 | Licensed | Licensed CC-BY 4.0 by the repository | 2026-10-25 |
| `jodi_oil`: [JODI Oil World Database](https://jodidata.org/oil/database/data-downloads.aspx) | Joint Organisations Data Initiative (JODI) | Free; open download | none stated | Not yet confirmed | To confirm against the JODI terms of use; republished with attribution to JODI | 2026-10-27 |
| `maintainer_fiscal_seed`: [Historical fiscal seed, 2004-2023](../pipeline/seeds/iraq_fiscal_historical.csv) | Compiled by the maintainer from the original publishers' documents | Redistribution confirmed by the maintainer on 2026-10-25 | none stated | Confirmed by the maintainer | Redistribution confirmed by the maintainer (statement, 2026-10-25); the publisher of each value is unknown (flag U) | 2026-10-25 |
| `opec_momr`: [Monthly Oil Market Report (figures typed into transcription records)](https://www.opec.org) | Organization of the Petroleum Exporting Countries (OPEC) | Public PDF download | none stated | Not yet confirmed | To confirm against the OPEC terms of use; a few figures are republished with attribution to OPEC | 2026-10-27 |
| `wb_wdi`: [WDI API, indicators DT.ODA.ALLD.CD and BX.GRT.EXTA.CD.WD](https://api.worldbank.org) | World Bank (World Development Indicators, compiled from OECD DAC data) | Creative Commons Attribution 4.0 (World Bank Data Catalog, dataset 0037712) | CC-BY-4.0 | Licensed | Licensed CC-BY 4.0 (licence check 2026-10-26, docs/source_inventory.md) | 2026-10-26 |

**Open items:** the terms of these sources have not yet been confirmed at the publisher: `bis_lbs`, `cosit_national_accounts`, `eia_intl`, `fred_brent`, `jodi_oil`, `opec_momr`.

<!-- terms:end -->

## Sources

The CBI Key Financial Indicators Excel file gives monthly money-and-banking data from December 2003 to September 2026 in one sheet. It is the primary source; the other files fill gaps and cross-check it.

| Source | Format | Frequency and coverage | Revisions and archive | Terms and access | Role |
| --- | --- | --- | --- | --- | --- |
| [CBI Key Financial Indicators](https://cbi.iq/news/view/94) | Excel, 1 sheet, months as columns, about 120 indicator rows with footnotes on breaks | Monthly, Dec 2003 to Sep 2026 (M1 and M2 to Aug 2026), plus the latest week. Covers CPI and core CPI, T-bill auctions, CBI policy and facility rates, bank rates, M0 sources and uses, M1, M2, FX deposits, reserve requirements | One file, overwritten on each update (this copy dated 14 Oct 2026); we must archive each download | No licence stated; free download | Primary for money and banking (100% monthly from Dec 2003) |
| [CBI Monthly Statistical Bulletin](https://cbi.iq/page/122) | Excel, 45 sheets, periods as rows, Arabic and English labels | Mostly annual for 2004 to 2022–24, then monthly to Jul or Aug 2026. Covers currency outside banks, M0–M2, reserve requirement (from 2008), interest rates, balance of payments, budget, public debt (from 2015), payments | Says its data are preliminary and may be amended; one file, overwritten | No licence stated; free download | Cross-check for overlapping money series; also serves other families |
| IMF Data Portal (former IFS) | API | Monthly monetary survey for about 2005–2017, per an aggregator listing (to verify on IMF) | IMF revises | IMF terms of use to check | Cross-check for 2005–2017 |

**Archiving CBI downloads.** Because both CBI files are overwritten at the source, every download
is now archived as a new dated file, `pipeline/raw/cbi/cbi_key_financial_indicators_<YYYY-MM-DD>.xlsx`
or `pipeline/raw/cbi/cbi_bulletin_<YYYY-MM-DD>.xlsx`, and added to the raw-file manifest
(`pipeline/metadata/raw_manifest.yaml`). The parsers read the newest dated file, falling back to
the earlier archived `key_financial_indicators.xlsx` and `bulletin_latest.xlsx`, which are kept
unchanged.

## Money and banking series

All series below are **100% monthly** (Dec 2003+) and end of period, extracted directly from the **CBI Key Financial Indicators Excel file** without any PDF dependencies or annual series. Tables published only annually or starting late in the Monthly Bulletin (such as sectoral deposits, private-sector credit, and banking-system balance sheets) are not published.

| Series | Unit as published | Primary source | Cross-check | Monthly from |
| --- | --- | --- | --- | --- |
| Currency outside banks | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 1-a | Dec 2003 |
| Monetary base (M0) | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 2-a | Dec 2003 |
| Narrow money (M1) | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 1-c | Dec 2003 |
| Broad money (M2) | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 2-b | Dec 2003 |
| Foreign-currency deposits | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 2-b | Dec 2004 |
| Official reserves of the CBI | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 4 / IMF IFS | Dec 2003 |
| Policy rate and standing facilities | % | Key Financial Indicators | CBI announcements | Aug 2004 |
| Bank deposit and lending rates | % | Key Financial Indicators | Monthly Bulletin, sheet 4-1 | Dec 2003 |
| Required and excess reserves | Billion IQD | Key Financial Indicators | Monthly Bulletin, sheet 11-a | Dec 2004 |
| Treasury bill auctions and stock | Million IQD | Key Financial Indicators | Monthly Bulletin, sheet 6-2 | 2004, by tenor |

The Monthly Bulletin also carries currency by denomination (sheet 1-b, monthly from Jan 2022), check clearing (sheets 12-a and 12-b, monthly from Jan 2024), financial soundness indicators (quarterly 2023 Q1–2025 Q2), payment systems (sheets 7-1 to 7-3, monthly from Jan 2024), balance of payments, budget, and public debt. Those belong to their respective dedicated families.

## Exchange rates

This family covers the daily parallel market exchange rate and official CBI exchange rates.

Per explicit design decisions:
- **COSIT exchange rate series are removed entirely.**
- **CBI FX window sales series are removed entirely** (`cbi_fx_sales_total`, `cbi_fx_sales_transfers`, `cbi_fx_sales_cash`, `cbi_mof_dollar_purchases`).
- **Parallel Exchange Rate Historical Continuity (2004–present):**
  - **2004 to 31 December 2022:** Daily parallel exchange rate data will be ingested from a **user-provided Excel file**.
  - **1 January 2023 to present:** Daily parallel exchange rate data is sourced from the [Iraq parallel exchange rate GitHub repo](https://github.com/HusseinKh90/Iraq-parallel-exchange-rate). The **Baghdad series is considered the headline Iraq national series**.

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| User-provided Excel file (`pipeline/seeds/cbi_exchange_rate_historical.xlsx`, sheet `Daily Market price`) | Excel | Daily parallel exchange rate for Iraq (Baghdad), 2004 through 31 Dec 2022 | Provided by user | Primary for historical daily parallel rate (2004–2022) |
| [Iraq parallel exchange rate (GitHub)](https://github.com/HusseinKh90/Iraq-parallel-exchange-rate) | CSV (`data/daily_fx.csv`), updated daily by GitHub Actions; archived as `pipeline/raw/github/daily_fx_<date>.csv` | Daily open and close for Baghdad (also Basra and Erbil), from 1 Dec 2020; the project uses the Baghdad close from 1 Jan 2023. Consensus of 3 public Telegram channels (@dollariraqi, @iqborsa, @dollar\_price) | CC-BY 4.0; public repo, no login. Publisher: the repo; underlying source: the Telegram channels. Licence confirmed by the maintainer on 2026-10-24 | Primary for daily parallel rate from 1 Jan 2023 on (Baghdad considered national Iraq series) |
| [CBI exchange-rate files](https://cbi.iq/page/144) | Excel file: dinar per USD (daily, monthly, annual); archived as `pipeline/raw/cbi/fx/cbi_fx_usd_<date>.xlsx` | Daily, monthly, annual; daily from 2004 | No licence stated; free download (checked 2026-10-24) | Primary for official CBI exchange rate (whole history) |
| [World Bank RTFX](https://microdata.worldbank.org/index.php/catalog/6160/study-description) | Data files via the Microdata Library | Monthly unofficial (parallel) rate estimates by market, Jan 2007 to Oct 2026, updated weekly | Published as open data | Secondary / cross-check only |

| Series | Unit | Primary source | Cross-check | From |
| --- | --- | --- | --- | --- |
| `parallel_rate_iraq` (Daily; Baghdad close as national Iraq series) | IQD per USD | User Excel file (2004–2022); GitHub repo Baghdad close (`daily_fx.csv`, from 1 Jan 2023; flag `B` on 2023-01-01, the change of source) | World Bank RTFX | Jan 2004 |
| `fx.official` (Official CBI base buying rate from MoF) | IQD per USD | CBI exchange-rate portal (`page/144`, Sheet `'Daily Price basis'`) | Monthly Bulletin sheet `المؤشرات الاقتصادية` | Nov 2003 |

**Decisions & Open Questions for Exchange Rates**

- [x] **Parallel rate coverage & source handoff:** Decided: User provides Excel file for daily data from 2004 until end of Dec 2022. From 1 January 2023 to present, the Baghdad series from the GitHub repo is considered the national Iraq series. Implemented: the Baghdad close from 2023-01-01; the seed supplies the days up to the end of 2022.
- [x] **COSIT exchange rate series:** Decided: Removed entirely per user direction.
- [x] **CBI FX sales series:** Decided: `cbi_fx_sales_total`, `cbi_fx_sales_transfers`, `cbi_fx_sales_cash`, and `cbi_mof_dollar_purchases` removed entirely per user direction.
- [x] **CBI exchange-rate files layout & strategy:** Decided: Inspected all 3 files on `cbi.iq/page/144`. Ignored major currencies/gold and foreign cross-rates. Parsed strictly `'Daily Price basis'` from primary USD workbook (`file-179256987150948.xlsx`) as a one-time historical seed (`pipeline/seeds/cbi_official_fx_history.parquet`, 5,674 daily records from Nov 2003 to present) named `fx.official`. Future updates handled via lightweight tail extension on statutory peg decrees.

## Oil

The Oil family focuses on monthly crude oil production and crude benchmark prices. Secondary-source production is read from the U.S. EIA International Energy Statistics bulk file. Direct-communication production is read from JODI-Oil to March 2024, then from OPEC Monthly Oil Market Report figures typed into a transcription record. Prices cover ten transcribed monthly Basrah anchor months (OPEC MOMR) and daily Brent spot (FRED / EIA).

Per explicit design decisions, attempting to build monthly crude oil export series (total or by outlet: Basra vs Ceyhan) from Ministry of Oil press releases or SOMO web dashboards is excluded from the package scope. Neither agency maintains an accessible historical machine-readable archive, and flows on the northern pipeline route (Kirkuk–Ceyhan) had long interruptions and changes of operator. Crude oil export earnings are published quarterly from the CBI **Balance of Payments** (`trade.exports_crude_oil`, from 2013-Q1).

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [EIA International Energy Statistics](https://www.eia.gov/opendata/bulk/INTL.zip) | Bulk ZIP (`INTL.zip`, series `INTL.57-1-IRQ-TBPD.M`), archived as `pipeline/raw/eia/INTL.zip` | Monthly crude production of Iraq from secondary sources, 2004 to present | US government open data; free public API | Primary for `crude_production_secondary` |
| OPEC Monthly Oil Market Report | PDF archive from 2001 on opec.org (`momr-*.pdf`); no PDF is parsed | Monthly, Jan 2004 to present. Secondary sources production reported in all issues; direct communication from Iraq MoO reported from ~2008. Basrah Light price to Dec 2021; Basrah Medium from Jan 2022 | Public PDF download | Source of the transcribed direct-communication figures (Apr 2024 on) and the ten Basrah anchor months |
| [JODI Oil World Database](https://jodidata.org/oil/database/data-downloads.aspx) | CSV, one file per year (`2007.csv`, `2023.csv`, etc.), plus API | Monthly crude production (`INDPROD` in KBD and KBBL). Coverage continuous in 2007 and 2023, stops after Mar 2024 | Free; open download | Historical cross-check for crude production (to Mar 2024) |
| EIA (via FRED series `DCOILBRENTEU`) | REST API | Daily Brent spot price, continuous 1987 to present | US government open data; free public API | Primary for daily Brent crude price |

| Series | Unit | Frequency | Primary source | Cross-check | From |
| --- | --- | :-: | --- | --- | :-: |
| `crude_production_secondary` | Thousand barrels per day | **Monthly** | U.S. EIA (`INTL.57-1-IRQ-TBPD.M`) | JODI-Oil (2007–Mar 2024) | Jan 2004 |
| `crude_production_direct` | Thousand barrels per day | **Monthly** | JODI-Oil (`INDPROD`, 2007–Mar 2024); OPEC MOMR Direct, transcribed (Apr 2024+) | None | Jan 2007 |
| `oil_price_basrah` (Light to 2021; Medium from 2022) | USD per barrel | **Monthly only** | OPEC MOMR (ORB component), ten transcribed anchor months | None | Jul 2004 |
| `oil_price_brent` | USD per barrel | **Daily** | EIA via FRED (`DCOILBRENTEU`) | None | 6 Jan 2004 |

**Decisions & Open Questions for Oil**

- [x] **Crude exports by outlet (Basra vs Ceyhan):** Decided: Excluded entirely. Neither MoO nor SOMO maintains a machine-readable historical time series, and pipeline flows to Ceyhan had long interruptions and changes of operator. Crude export earnings are reported quarterly via the CBI Balance of Payments.
- [x] **Price frequencies:** Decided: `oil_price_basrah` is strictly **monthly** (from OPEC MOMR); `oil_price_brent` is **daily** (from FRED). No free public daily series exists for Basrah.
- [x] **Basrah benchmark grade transition:** Decided: Basrah Light up to Dec 2021; Basrah Medium from Jan 2022, following OPEC Reference Basket definitions.
- [x] **Direct vs. Secondary start dates & JODI 2007 timeline:** Decided: `crude_production_secondary` starts in Jan 2004 (continuous, from the EIA bulk file). `crude_production_direct` starts in Jan 2007 because Iraqi ministerial reporting was not formally established in international databases (JODI/OPEC) until 2007 (verified in `2007.csv`). From April 2024 onward, direct production transitions to OPEC MOMR Chapter 5 (Table 5-8). Both series are preserved separately to enable academic spread analysis.

## Prices

COSIT compiles the Iraqi Consumer Price Index (CPI) and core CPI; the CBI republishes the full monthly history of headline and core CPI across all base periods in Key Financial Indicators.

> **Decision on CPI base periods:** We will publish each native base-year series as reported (`1993 = 100`, `2007 = 100`, `2012 = 100`, and `2022 = 100` — or the three post-2004 rebased series plus the 1993 base covering 2004–2009), and we will also construct and publish a **unified CPI series** by merging/splicing all base periods together using their 12–13 month overlap windows.

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [CBI Key Financial Indicators](https://cbi.iq/news/view/94) (`file-179205300470528.xlsx`, rows 3–10, 152–164) | Excel | Monthly Headline CPI and Core CPI across four overlapping bases: `1993 = 100` (Dec 2003–Dec 2009, 73 months), `2007 = 100` (Jan 2009–Dec 2015, 84 months), `2012 = 100` (Jan 2015–Jan 2024, 109 months), and `2022 = 100` (Jan 2023–Aug 2026, 44 months), plus MoM, 6-month and YoY inflation rates | No licence stated; free download | Primary for long monthly Headline and Core CPI across all bases |
| [COSIT CPI monthly reports and Annual Statistical Abstract](https://cosit.gov.iq) | PDF and Excel, Arabic and English | Monthly CPI bulletins; Annual Abstract price indices chapter gives multi-year tables | Government publication; licence to check | Original compiler; cross-check for CBI headline and core CPI |

| Series | Unit | Primary source | Cross-check | From |
| --- | --- | --- | --- | --- |
| Headline CPI (native bases: `1993 = 100`, `2007 = 100`, `2012 = 100`, `2022 = 100`) | Index | CBI Key Financial Indicators | COSIT monthly reports; CBI Monthly & Annual Bulletins | Jan 2004 (Dec 2003 in file) |
| Headline CPI (unified merged series) | Index (`2022 = 100`) | Derived by splicing the native base series in CBI Key Financial Indicators across their 12–13 month overlap windows (`2009`, `2015`, `2023`) | COSIT long-term series | Jan 2004 |
| Core CPI (native bases: `1993 = 100`, `2007 = 100`, `2012 = 100`, `2022 = 100`) | Index | CBI Key Financial Indicators | COSIT monthly reports | Jan 2004 |
| Core CPI (unified merged series) | Index (`2022 = 100`) | Derived by splicing the native Core CPI base series in CBI Key Financial Indicators (flagging the 2009 basket exclusion change) | COSIT monthly reports | Jan 2004 |

**Open questions for prices**

- [x] **CPI base periods.** Decided: publish each native base series as reported, plus a unified CPI series merging all bases together.
- [x] **Splicing method for the unified CPI.** Decided: link in December of each overlap year and switch to the new base the following January (`docs/linked_inflation_method.md`).
- [x] **Core CPI definition break in 2009.** In the `1993 = 100` series, Core CPI excludes Fuel & Lighting (`F&L`) and Transport & Communications (`T&C`). From `2007 = 100` onward (Footnote 7), "New Core Inflation" excludes Fruit & Vegetables and Kerosene & LPG. Decided: the unified core series is kept across the change and flagged `B` at the 2010-01 splice, with a warning in `docs/linked_inflation_method.md`.
- [ ] **Geographic coverage break in 2007.** Check whether the `1993 = 100` CPI excluded the three northern governorates and whether `2007 = 100` onward covers all 18 governorates.

## Government finance

Federal government revenue and expenditure are compiled on a cash basis by the Ministry of Finance (Accounting Department) and republished in summary form by the CBI in Sheet `6-1` (`الميزانية العامة للدولة / Public Budget`). Ministry of Finance oil revenue (cash basis, IQD) is kept strictly separate from Ministry of Oil export revenue (shipment/sales basis, USD).

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [CBI Monthly Statistical Bulletin](https://cbi.iq/page/122) (`file-179015939752236.xlsx`, sheet `6-1`: `الميزانية العامة للدولة / Public Budget`) | Excel | Sheet `6-1` (`Public Budget`, Million IQD): annual `2004–2023` (rows 9–28) and monthly cumulative year-to-date (YTD) for `Jan–Dec 2024` (rows 30–41, where `Dec. 2024` is full-year 2024), `Jan–Dec 2025` (rows 43–54, where `Dec. 2025` is full-year 2025), and `Jan–Jun 2026` (rows 56–61) across 7 columns (`Actual Revenues`, `Current Revenues`, `Investment Revenues`, `Actual Expenditures`, `Current Expenditures`, `Investment Expenditures`, `Surplus / Deficit*`) | No licence stated; free download | **Primary source for the 7 annual public budget series (`2004–2025`)** |
| [Ministry of Finance Open Budget JSON API](https://mof.gov.iq/api/obs-reports/revenues-expenditures) and [Monthly State Accounts Archive](https://mof.gov.iq/Budget-implementation-Archive) (`/api/dl/vn03j0vt9kvhklylb4in72lq?locale=ar`) | JSON API, Excel, and PDF on `mof.gov.iq` | `/api/obs-reports/revenues-expenditures` (backed by `Compare between Expenditures and Revenues.xlsx`): exact IQD annual Budget vs Actual figures (`2015–2024`) across 8 revenue categories and 11 expenditure categories. Monthly State Accounts (`حساب الدولة لغاية شهر ... للموازنة الاتحادية`): cumulative YTD PDF/Excel tables (`2015–2026`) | Government publication; licence to check | **Primary cross-check for annual budget totals and current vs investment breakdowns (`2015–2024`)** |
| [CBI Annual Statistical Bulletin](https://cbi.iq/page/142) and Annual Economic Report | PDF | Annual and monthly public budget execution tables, 2004–2023 | No licence stated; free download | Cross-check for pre-2015 annual rows (including the 2012 column swap in Sheet `6-1`) |

| Series | Sheet `6-1` Column | Unit | Primary source | Cross-check | Frequency & coverage |
| --- | :-: | --- | --- | --- | --- |
| Total actual revenues (`الإيرادات الفعلية`) | `Col B` | Million IQD | CBI Monthly Bulletin (sheet `6-1`, annual rows `2004–2023` + `Dec.` cumulative YTD rows for `2024–2025`) | MoF Open Budget JSON (`/api/obs-reports/revenues-expenditures`) & CBI Annual Bulletins | Annual, 2004 on |
| Current revenues (`الايرادات الجارية`) | `Col C` | Million IQD | As above (populated from **2011** onward in Sheet `6-1`; 2012 column swap corrected) | MoF Open Budget JSON & CBI Annual Bulletins | Annual, 2011 on (`NA` for 2004–2010 in Sheet `6-1`) |
| Investment / capital revenues (`الإيرادات الإستثمارية`) | `Col D` | Million IQD | As above (populated from **2011** onward in Sheet `6-1`; 2012 column swap corrected) | MoF Open Budget JSON (`Capital revenues`) & CBI Annual Bulletins | Annual, 2011 on (`NA` for 2004–2010 in Sheet `6-1`) |
| Total actual expenditures (`النفقات الفعلية`) | `Col E` | Million IQD | As above | MoF Open Budget JSON & CBI Annual Bulletins | Annual, 2004 on |
| Current (operational) expenditures (`النفقات الجارية`) | `Col F` | Million IQD | As above (populated from **2013** onward in Sheet `6-1`) | MoF Open Budget JSON & CBI Annual Bulletins | Annual, 2013 on (`NA` for 2004–2012 in Sheet `6-1`) |
| Investment (capital) expenditures (`النفقات الإستثمارية`) | `Col G` | Million IQD | As above (populated from **2013** onward in Sheet `6-1`) | MoF Open Budget JSON (`INVESTMENT PROJECTS`) & CBI Annual Bulletins | Annual, 2013 on (`NA` for 2004–2012 in Sheet `6-1`) |
| Fiscal surplus or deficit (`الفائض او العجز*`) | `Col H` | Million IQD | As above (`Actual Revenues - Actual Expenditures`) | MoF Open Budget JSON & CBI Annual Bulletins | Annual, 2004 on |

**Findings from `file-179015939752236.xlsx` (Sheet `6-1`) and `mof.gov.iq`**

- **Constructing the full `2004–2025` annual series from Sheet `6-1`:** In `file-179015939752236.xlsx` Sheet `6-1`, rows `9–28` give explicit annual totals for `2004–2023`, while `2024` and `2025` are reported as monthly cumulative year-to-date (YTD) blocks (`Jan.` through `Dec.`). Because the monthly blocks are cumulative YTD, the **`Dec. 2024` row (`R41`)** and **`Dec. 2025` row (`R54`)** represent the full-year annual totals for `2024` and `2025` (`140,774,106` Million IQD revenues and `150,527,346` Million IQD expenditures in 2024; `124,185,236` Million IQD revenues and `141,227,925` Million IQD expenditures in 2025).
- **Exact cross-check match with MoF Open Budget JSON (`2015–2024`):** Calling `https://mof.gov.iq/api/obs-reports/revenues-expenditures` returns the exact IQD values from MoF's `Compare between Expenditures and Revenues.xlsx`. For `2024`, the MoF JSON sum of actual revenues is `140,774,106,157,464 IQD` (`140,774,106 Million IQD`), matching CBI Sheet `6-1` `Dec. 2024` (`140,774,106`) to the exact million IQD. Similarly, MoF's 2024 `INVESTMENT PROJECTS` expenditure is `25,313,302,223,675 IQD` (`25,313,302 Million IQD`), matching CBI Sheet `6-1` `Dec. 2024` `Investment Expenditures` (`25,313,302`) to the exact million IQD.
- **2012 column swap bug in CBI Sheet `6-1` (`Row 17`):** In `file-179015939752236.xlsx` Sheet `6-1` row 17 (`2012`), `Current Revenues` (`Col C`) is recorded as `78,495` Million IQD and `Investment Revenues` (`Col D`) is recorded as `119,387,908` Million IQD — the exact reverse of every other year (`Current Revenues + Investment Revenues = 119,466,403 = Actual Revenues`). In the clean dataset layer, swap `Col C` and `Col D` for `2012` and flag the correction in validation metadata.
- **Start dates of sub-components in Sheet `6-1`:** While `Actual Revenues` (`Col B`), `Actual Expenditures` (`Col E`), and `Surplus / Deficit*` (`Col H`) are populated for every year from `2004` onward, `Current Revenues` (`Col C`) and `Investment Revenues` (`Col D`) are blank (`None`) for `2004–2010` (starting in `2011`), and `Current Expenditures` (`Col F`) and `Investment Expenditures` (`Col G`) are blank (`None`) for `2004–2012` (starting in `2013`).

**Decisions and open questions for government finance**

- [x] **Series selection (`7` core series from CBI Sheet `6-1`).** **Decided:** Include only the 7 headline public budget series from CBI Sheet `6-1` (`Total actual revenues`, `Current revenues`, `Investment revenues`, `Total actual expenditures`, `Current expenditures`, `Investment expenditures`, and `Fiscal surplus or deficit`).
- [x] **Annual frequency only.** **Decided:** Publish all 7 Government finance series at **annual frequency only** (`2004–2025`), using the explicit annual rows (`2004–2023`) and the `Dec.` cumulative YTD rows (`Dec. 2024`, `Dec. 2025`, and future completed `Dec.` rows) from CBI Sheet `6-1`. Exclude in-year partial months (such as `Jan–Jun 2026`) until the full-year `Dec.` row is published.
- [ ] **Backfilling `2004–2010` revenue split and `2004–2012` expenditure split.** Check whether the CBI Annual Statistical Bulletins (`2004–2012`) report the annual split between Current vs Investment revenues (`2004–2010`) and Current vs Investment expenditures (`2004–2012`), or whether those years should remain `NA` as in Sheet `6-1`.
- [ ] **Years without an enacted federal budget law (`2014`, `2020`, `2022`).** Flag `2014`, `2020`, and `2022` in series metadata as years where Iraq operated under the 1/12th Financial Management Law rule without an enacted budget law.

## Balance of payments

The CBI compiles Iraq's quarterly and annual Balance of Payments in USD according to the IMF's Sixth Edition manual (`BPM6`, where `Financial Account net = Net lending (+) / Net borrowing (-)` and `Net Errors & Omissions = Financial Account - (Current Account + Capital Account)`).

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [CBI Balance of Payments Data Archive](https://cbi.iq/page/145) | Excel (`.xlsx`) for 2013–2026; PDF for 2000–2012 | Dedicated BOP download page hosting standalone Excel workbooks for `2013–2016` (`file-169209685485309.xlsx`), each individual year `2017` through `2026`, multi-year workbooks (`2021–2023`, `2021–2024`), and a single consolidated PDF for `2000–2012` (`file-154461165970692.pdf`) | No licence stated; free download | **Primary source for all Balance of Payments series (2004–present)** |
| [CBI Annual Balance of Payments Reports](https://cbi.iq/page/152), [BOP Guide](https://cbi.iq/page/154), and [Annual Statistical Bulletins](https://cbi.iq/page/142) | PDF | Annual narrative & statistical reports (e.g. *Annual Report of Iraq's Balance of Payments 2024*) and Annual Statistical Bulletin tables (table 51/52 in 2022 numbering), 2004–2024 | No licence stated; free download | Methodological reference (e.g., 15% CIF-to-FOB adjustment, IOC in-kind oil exports and cost-recovery accounting) and cross-check |
| IMF Balance of Payments Statistics (BOP/IIP API) | API | Quarterly and annual BPM6 series reported by the CBI to the IMF | IMF terms of use to check | Cross-check for 2005–2025 |

| Series | Unit | Primary source | Cross-check | From |
| --- | :-: | --- | --- | --- |
| Current account balance, net (`اولا- الحساب الجاري`) | Million USD | CBI BOP Data page (`cbi.iq/page/145`, Excel 2013–2026; PDF 2004–2012) | IMF BOP API | Quarterly, 2004 on |
| Trade balance (Goods, net) (`1- الميزان التجاري`) | Million USD | As above | IMF BOP API; COSIT trade | Quarterly, 2004 on |
| Exports of goods (FOB), total (`الصادرات (فوب )`) | Million USD | As above | IMF BOP API; COSIT trade | Quarterly, 2004 on |
| Imports of goods (FOB), total (`الاستيرادات`) | Million USD | As above | IMF BOP API; COSIT trade | Quarterly, 2004 on |
| Imports of goods: Government imports (`1- الاستيرادات الحكومية`) | Million USD | As above | COSIT trade | Quarterly, 2004 on |
| Imports of goods: Private sector imports (`2- استيرادات القطاع الخاص`) | Million USD | As above | COSIT trade | Quarterly, 2004 on |
| Capital account balance, net (`ثانيا- صافي الحساب الراسمالي`) | Million USD | As above | IMF BOP API | Quarterly, 2004 on |
| Financial account balance, net (`ثالثاً- صافي الحساب المالي`) | Million USD | As above | IMF BOP API | Quarterly, 2004 on |

**Findings on CBI Balance of Payments and the 2024 Annual BOP Report**

- **Excel availability back to 2013:** Unlike most tables that require PDF extraction before 2024, the CBI's dedicated [Balance of Payments Data page (`cbi.iq/page/145`)](https://cbi.iq/page/145) hosts Excel workbooks covering **2013–2016** and every individual year **2017–2026**, leaving only **2004–2012** in a single consolidated PDF (`file-154461165970692.pdf`).
- **15% CIF-to-FOB conversion rule:** The 2024 Annual BOP Report (p. 2) and official methodology document that CBI converts total merchandise imports from CIF to FOB by deducting a flat **15%** for freight and insurance (`$13,111.5M` deducted from `$87,410M` CIF in 2024 to reach `$74,298.5M` FOB; `$1,540M` deducted in 2026 Q1 to reach `$8,726.4M` FOB) and transferring that amount to Services payments.
- **In-kind crude oil exports and IOC cost recovery:** Official methodology notes that Governmental Crude Oil Exports include "the value of oil in kind" paid to international oil companies (IOCs) under technical service contracts (`$13,342.6M` out of `$96,189.9M` in 2024 per the 2024 Annual BOP Report, p. 1).

**Decisions and open questions for balance of payments**

- [x] **Series selection (`8` core series).** **Decided:** Keep the 8 core series listed in the table above (`R11` Current account net, `R12` Trade balance, `R13` Exports FOB total, `R21` Imports FOB total, `R22` Government imports, `R28` Private sector imports, `R54` Capital account net, and `R57` Financial account net).
- [x] **Quarterly series only.** **Decided:** Publish **quarterly series only**.
- [ ] **BPM5 (`2000–2012` PDF) to BPM6 (`2013–2026` Excel) transition.** The `cbi.iq/page/145` archive splits between the `2000–2012` PDF (`file-154461165970692.pdf`) and the `2013–2026` Excel files. Download and inspect `file-154461165970692.pdf` and `file-169209685485309.xlsx` (`2013–2016`) to check whether `2004–2012` is quarterly or annual.

## Foreign trade

Iraq's merchandise trade is compiled on two distinct bases: (1) **Financial/Payments basis** by the Central Bank of Iraq (CBI) under the Balance of Payments framework (FOB, Million USD), measuring foreign exchange paid and received through the banking system; and (2) **Physical Customs declaration basis** by COSIT and the General Commission of Customs (CIF imports, FOB exports). In addition, international mirror trade is accessible via the IMF Direction of Trade Statistics (DOTS) API.

> **Decision on Foreign Trade Architecture:**
> 1. **Primary Anchor (Default):** The package's default trade series uses the **official CBI Balance of Payments Merchandise Trade series** (Quarterly, `2004 Q1` onward, Million USD, FOB) from `https://cbi.iq/page/145`. This ensures 100% internal consistency with Iraq's Balance of Payments, GDP, and foreign exchange reserves.
> 2. **Multi-Source Transparency:** The IMF DOTS partner-country mirror dataset, if added (*not implemented*), would be a separate source and never blended with CBI into a single hybrid column.
> 3. **Metadata & Reconciliation:** Each observation carries metadata tags (`valuation`: `"FOB"` vs `"CIF"`, `basis`: `"payments_financing"` vs `"customs_partner_mirror"`), and the package documents the standard **15% CIF-to-FOB adjustment** applied by the CBI.

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [CBI Balance of Payments Data Archive](https://cbi.iq/page/145) | Excel (`.xlsx`), rows 12–31 | Quarterly, `2004 Q1 – 2026 Q1` (Excel back to 2013 on `cbi.iq/page/145`; PDF for 2004–2012), Million USD (FOB). Disaggregated by sector (Crude oil, Oil products, Other exports) and end-use (Government vs Private; Consumption vs Capital goods) | No licence stated; free download | **Primary source for quarterly merchandise trade flows (`trade_quarterly`)** |
| [CBI Annual Statistical Bulletin](https://cbi.iq/page/142) and CBI Foreign Trade Reports | PDF | Annual SITC 1-digit commodity sections (0–9) and geographical distribution by major trading partner, 2004–2024 | No licence stated; free download | Primary for historical annual SITC commodity sections and partner groups |
| [COSIT Foreign Trade Statistics](https://cosit.gov.iq) | PDF and Excel | Annual and quarterly customs declaration reports: imports (CIF) and exports (FOB) by SITC/HS commodity and partner country | Government publication; free download | Cross-check for physical customs declarations |
| [IMF Direction of Trade Statistics (DOTS) API](https://data.imf.org/dot) (`CompactData/DOT/`) | REST JSON API (open, no key required) | Monthly, quarterly, and annual bilateral trade between Iraq and all world economies (`A.IQ.TMG_CIF_USD.{partner}` and mirror `A.{partner}.TXG_FOB_USD.IQ`) | IMF terms of use; free public API | **Supplemental source for bilateral partner country trade (`source="imf"`)** |

| Series | Description (Arabic) | Unit | Valuation | Primary source | Coverage |
| --- | --- | :-: | :-: | --- | :-: |
| `trade.exports_total` | إجمالي الصادرات السلعية | Million USD | FOB | CBI BOP Data Archive (`cbi.iq/page/145`) | 2004 Q1 on |
| `trade.exports_crude_oil` | صادرات النفط الخام الحكومية | Million USD | FOB | as above | 2004 Q1 on |
| `trade.exports_oil_products` | صادرات المشتقات النفطية (حكومي + خاص) | Million USD | FOB | as above | 2004 Q1 on |
| `trade.exports_nonoil` | الصادرات السلعية الأخرى (غير النفطية) | Million USD | FOB | as above | 2004 Q1 on |
| `trade.imports_total` | إجمالي الاستيرادات السلعية | Million USD | FOB | as above | 2004 Q1 on |
| `trade.imports_government` | استيرادات القطاع الحكومي | Million USD | FOB | as above | 2004 Q1 on |
| `trade.imports_private` | استيرادات القطاع الخاص | Million USD | FOB | as above | 2004 Q1 on |

The trade balance is published as `bop.trade_balance` with the other balance-of-payments series. The imports by end use (consumption, capital goods, oil products, for government and private sector) were considered and are *not implemented*.

**Findings on Foreign Trade**

- **The 15% CIF-to-FOB conversion factor:** The CBI converts total merchandise imports from CIF to FOB by deducting a flat **15%** for freight and insurance (documented in official BOP methodology and the 2024 Annual BOP Report, p. 2) and allocating that amount to Services payments. This explains why IMF/customs CIF numbers are consistently ~15–18% higher than CBI FOB numbers.
- **In-kind oil exports to IOCs:** Governmental crude exports include in-kind crude allocated to international oil companies for cost-recovery and remuneration fees under technical service contracts (e.g. `$13,342.6M` in 2024).
- **Kurdistan Region customs gap:** Physical customs declarations compiled by COSIT have historically undercounted imports due to delayed integration of northern border crossings (e.g. Ibrahim Khalil). CBI's banking-financing trade data and IMF partner mirror exports provide complete coverage of total merchandise entering the entire territory of Iraq.

**Decisions for foreign trade**

- [x] **Primary vs. secondary compiler.** **Decided:** Use CBI Balance of Payments merchandise trade as the authoritative series. IMF DOTS partner mirror trade is *not implemented*.
- [x] **Quarterly frequency.** **Decided:** Primary trade flows are published at **quarterly frequency** (`2004 Q1` onward).
- [x] **Series selection (`7` series).** **Decided:** Publish the seven series above: total exports and their split by commodity, and total imports and their split by executing sector (government and private). The end-use split of imports is not published.

## Output

COSIT's Directorate of National Accounts (`مديرية الحسابات القومية`) compiles Iraq's quarterly Gross Domestic Product (GDP) at current basic prices and at constant (`2007 = 100`) basic prices. It publishes it in *Early Warning Indicators* reports (`مؤشرات الإنذار المبكر`, Table 1) and in preliminary quarterly workbooks on `cosit.gov.iq/ar/national-accounts/income`. The CBI repeats headline nominal and real GDP in its Monthly Statistical Bulletin (sheet `المؤشرات الاقتصادية`, rows 18–21, in billion IQD).

> **Decision on Output / GDP:** quarterly data only, the **headline nominal and real GDP and the oil and non-oil parts**, from **2015 Q1**. COSIT published no official quarterly accounts before 2015, and the package does not model or estimate values, so the series start there. The series run to 2026 Q1.

| Source | Format | What is archived here | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [COSIT Early Warning Indicators reports](https://cosit.gov.iq/ar/national-accounts/income) (`مؤشرات الإنذار المبكر`) | PDF, Arabic | Ten reports in `pipeline/raw/cosit/alarm/`: Q1 2023, each quarter of 2024 and 2025, and Q1 2026 (the Q2 2025 one is a scan). Each shows the quarter, the one before and the same quarter a year earlier. Table 1 gives GDP and non-oil GDP at current and at constant 2007 prices, in million IQD | Government publication; free download | Source of 2022 Q1 to 2026 Q1 (the newest report that shows a quarter wins, as COSIT revises) |
| [COSIT preliminary quarterly GDP workbooks](https://cosit.gov.iq/ar/national-accounts/income) (`التقديرات الأولية الفصلية والإجمالية للناتج المحلي الإجمالي`) | Excel (`.xlsx`, one `.xls`) | The 2020 quarterly estimates (`.xls`), the 2021 first-quarter and first-half workbooks, `الاسعار الثابتة 2025.xlsx` (constant prices, 2025), and the annual estimates for 2014–2019, in `pipeline/raw/cosit/` | Government publication; free download | Source of 2020 Q1 to 2021 Q2 and of 2025 real GDP; crude oil is a line of its own |
| [CBI Monthly Statistical Bulletin](https://cbi.iq/page/122) (sheet `المؤشرات الاقتصادية`, rows 18–21) | Excel | Nominal and real GDP in billion IQD: December 2023, 2024 and 2025, and the 2026 months | No licence stated; free download | Cross-check (below) |

| Series | Unit as published | Arabic Name | Source | Coverage |
| --- | :-: | --- | --- | :-: |
| `gdp.nominal` (headline nominal GDP) | Million IQD | الناتج المحلي الإجمالي بالأسعار الأساسية الجارية | COSIT workbooks and reports, the line COSIT calls GDP | 2015 Q1 – 2026 Q1 |
| `gdp.nominal_nonoil` (nominal non-oil GDP) | Million IQD | الناتج المحلي الإجمالي عدا النفط بالأسعار الجارية | Derived: total minus oil | 2015 Q1 – 2026 Q1 |
| `gdp.nominal_oil` (nominal crude oil GDP) | Million IQD | ناتج نشاط النفط الخام بالأسعار الجارية | Workbooks give it; for the reports it is total minus the printed non-oil figure | 2015 Q1 – 2026 Q1 |
| `gdp.real` (headline real GDP, `2007 = 100`) | Million IQD | الناتج المحلي الإجمالي بالأسعار الأساسية الثابتة لسنة 2007 | as `gdp.nominal` | 2015 Q1 – 2026 Q1 |
| `gdp.real_nonoil` (real non-oil GDP) | Million IQD | الناتج المحلي الإجمالي عدا النفط بالأسعار الثابتة لسنة 2007 | Derived: total minus oil | 2015 Q1 – 2026 Q1 |
| `gdp.real_oil` (real crude oil GDP) | Million IQD | ناتج نشاط النفط الخام بالأسعار الثابتة لسنة 2007 | as `gdp.nominal_oil` | 2015 Q1 – 2026 Q1 |

**Findings on Iraq quarterly GDP**

- **Which documents the values come from.** `docs/collecting_data_doc.md` (Source 8) lists, quarter by quarter, which archived document each value is read from; `docs/transcription_records.md` describes the record that cites them. The quarters 2015–2019, 2021 Q3–Q4 and 2022 Q2–Q3 come from documents that are not archived and keep flag `U`.
- **COSIT revises its quarters, by a lot.** Q1 2024 is 76,956,186 million IQD in the Q1 2024 report and 84,160,312 in the Q1 2025 one. The newest report wins.
- **Reporting prices:** COSIT compiles national accounts at **basic prices** (`الأسعار الأساسية`): gross value added before net taxes on products. "GDP" is the sum by activity less the imputed bank service charge.
- **Crude oil against non-oil:** the reports print total and non-oil GDP, so crude oil GDP is total minus non-oil; the workbooks give crude oil as a line.
- **Agreement with the CBI bulletin (billion IQD).** The bulletin's December figures against the sum of the four published quarters:

  | Year | CBI nominal / quarters | CBI real / quarters |
  | --- | --- | --- |
  | 2023 | 353,780 / 335,925 | 215,232 / 209,553 |
  | 2024 | 359,069 / 366,019 | 210,314 / 217,516 |
  | 2025 | 330,677 / 331,249 | 207,338 / 207,338 |

  The bulletin's 2026 Q1 figures (80,972 nominal, 47,133 real) equal COSIT's report for that quarter. 2025 agrees closely. 2023 and 2024 differ by up to 5%: COSIT's quarters changed between reports, and which vintage the bulletin used is not stated.
- **Before 2015:** no official quarterly national accounts exist, so the series start in 2015 Q1.

**Decisions for output**

- [x] **Quarterly frequency only.** `2015 Q1 – 2026 Q1`.
- [x] **Series selection (`6` core series).** Headline nominal GDP, nominal non-oil GDP, nominal oil GDP, headline real GDP (`2007 = 100`), real non-oil GDP and real oil GDP.
- [x] **Constant-price base year.** Constant-price series use the official national accounts base of `2007 = 100`, in million IQD.

## Cross-Border Banking (BIS)

The Bank for International Settlements (BIS) in Basel compiles and publishes the Locational Banking Statistics (LBS, dataflow `BIS/WS_LBS_D_PUB/1.0`), tracking the cross-border claims and liabilities of internationally active banks in 48 reporting jurisdictions vis-à-vis counterparties resident in Iraq (`IQ`). This gives researchers an independent, internationally audited mirror view of Iraqi deposits, reserves held abroad, and international bank loans.

> **Decision on BIS Cross-Border Banking:** Include quarterly cross-border claims, liabilities, sectoral splits (bank vs. non-bank), and bilateral partner breakdowns from **2004 Q1 onward** (historical records extend back to 1977 Q4 with **zero missing quarters**). Published through the same `get` as every other series (`bis.lbs.*`: claims, liabilities and their sector splits, 2004 Q1 on); the bilateral partner breakdowns are *not implemented*.

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [BIS SDMX 2.1 REST API & Data Portal](https://data.bis.org) (dataflow `WS_LBS_D_PUB`) | REST API (SDMX-CSV), keyless public endpoint (`https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/{KEY}?format=csv`) | Quarterly, 1977 Q4 to latest rolling quarter (`2026 Q1`), zero missing quarters. All currencies (`TO1`) and USD-denominated stocks in Million USD | Open data, free public access, no API key required; attribution required ("Source: BIS Locational Banking Statistics") | Primary source for cross-border banking assets and liabilities |
| [World Bank WDI Mirror](https://data.worldbank.org/indicator/DT.DOD.BLAT.CD) | API / CSV | Annual bilateral and commercial bank lending aggregates | CC-BY 4.0 | Cross-check for annual commercial bank debt stock |

| Series | Unit as published | Dimension / Key Filter | Description | Primary source | Coverage |
| --- | :-: | --- | --- | --- | :-: |
| `bis_claims_total` | Million USD | `Q.S.C.A.TO1.A.5J.A.5A.A.IQ.N` | Total foreign bank claims (loans & debt) on all Iraqi sectors | BIS SDMX API | 2004 Q1 on |
| `bis_liabilities_total` | Million USD | `Q.S.L.A.TO1.A.5J.A.5A.A.IQ.N` | Total foreign bank liabilities to all Iraqi sectors (Iraqi deposits abroad) | BIS SDMX API | 2004 Q1 on |
| `bis_liabilities_banks` | Million USD | `Q.S.L.A.TO1.A.5J.A.5A.B.IQ.N` | Foreign bank liabilities to Iraqi banks & CBI (~93% of total liabilities) | BIS SDMX API | 2004 Q1 on |
| `bis_liabilities_nonbank` | Million USD | `Q.S.L.A.TO1.A.5J.A.5A.N.IQ.N` | Foreign bank liabilities to Iraqi non-bank entities (corporate & household) | BIS SDMX API | 2004 Q1 on |
| `bis_claims_nonbank` | Million USD | `Q.S.C.A.TO1.A.5J.A.5A.N.IQ.N` | Foreign bank claims on Iraqi non-bank private sector | BIS SDMX API | 2004 Q1 on |
| `bis_bilateral_liabilities` | Million USD | `Q.S.L.A.TO1.A.5J.A.{CTY}.A.IQ.N` | Foreign bank liabilities to Iraq by reporting jurisdiction (US, DE, GB, ES, CH, FR, etc.) | BIS SDMX API | 2004 Q1 on |

**Findings on BIS Data for Iraq**

- **Continuous 50-year track record:** The BIS LBS time series for Iraq contains 195 continuous quarterly periods from `1977 Q4` to `2026 Q1` (390 observations across headline claims and liabilities) without a single broken quarter or missing interval.
- **Heavy concentration in official bank deposits:** Over 93% of all foreign bank liabilities to Iraq are held vis-à-vis Iraqi banks and the Central Bank of Iraq (`L_CP_SECTOR = B`), directly reflecting foreign reserve placements and commercial bank nostro balances in global financial centers.
- **Geographic distribution:** As of 2026 Q1, the United States holds ~33.0% ($9.24B) of reported Iraqi deposits abroad, the United Kingdom holds ~21.1% ($5.90B), Germany holds ~16.5% ($4.61B), Switzerland holds ~1.8% ($0.51B), and France holds ~1.1% ($0.30B).
- **Zero authentication barriers:** The live BIS SDMX 2.1 REST API endpoint (`https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/{KEY}?format=csv`) returns pre-filtered CSV slices with standard HTTP GET requests, making automated downloading and integration into `iraqdata` robust and deterministic.

**Decisions for cross-border banking**

- [x] **Quarterly frequency.** **Decided:** Include quarterly series from `2004 Q1` onward (preserving full history back to `1977 Q4` in raw archives).
- [x] **Series selection (`6` core series).** **Decided:** Headline Claims, Headline Liabilities, Bank vs Non-Bank Sector splits, and Bilateral Jurisdiction breakdowns.
- [x] **Access.** The BIS series are read with the same `get` as the others; each series' origin and terms are in `series.md`. There is no separate `external` module.

## Development Assistance & Reconstruction (OECD DAC)

The OECD Development Assistance Committee (DAC) compiles and audits international development assistance, reconstruction grants, and concessional loans disbursed to Iraq under the Creditor Reporting System (CRS / DAC Table 2a). Between 2003 and 2010, Iraq received over $60 Billion in international aid. This series provides an independent, internationally audited view of non-oil external financing, infrastructure grants, and the 2005 peak.

> **Decision on OECD DAC Aid:** Include annual Net Official Development Assistance (ODA) receipts, flow types (grants vs. concessional loans), and bilateral donor breakdowns (US, Japan, Germany, UK, EU Institutions, Multilateral) from **2003 onward** (historical records extend back to 1960 with **zero missing years**). Published through the same `get` (`oecd.dac.oda_total_net` and `oecd.dac.grants_excl_tc`, annual); the concessional-loan split and the bilateral donor series are *not implemented*.

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [OECD Data Explorer & Creditor Reporting System](https://stats.oecd.org) / [World Bank WDI API Gateway](https://api.worldbank.org/v2/country/IRQ/indicator/DT.ODA.ALLD.CD) | REST API (JSON, CSV), keyless public endpoint | Annual, continuous 1960 to 2023 (zero missing years). Net ODA flows in Current Million USD and Constant 2021 USD | Open data, free public access, no API key required; CC-BY 4.0 | Primary source for foreign aid, reconstruction financing, and donor breakdowns |

| Series | Unit as published | Dimension / Indicator Code | Description | Primary source | Coverage |
| --- | :-: | --- | --- | --- | :-: |
| `oecd.dac.oda_total_net` | Million USD | `DT.ODA.ALLD.CD` | Net official development assistance and official aid received | OECD DAC via WB WDI | 2003 on (1960+) |
| `oecd.dac.grants_excl_tc` | Million USD | `BX.GRT.EXTA.CD.WD` | Grants **excluding** technical cooperation (WDI title: "Grants, excluding technical cooperation (BoP, current US$)"); not total ODA grants | OECD DAC table DAC2A via WB WDI | 2003 on |

**Licence check (2026-10-26):** the WDI indicator metadata (`api.worldbank.org/v2/indicator/BX.GRT.EXTA.CD.WD`)
gives the source organization as "DAC2A: Aid (ODA) disbursements to countries and regions,
Organisation for Economic Co-operation and Development (OECD)". The World Development Indicators
dataset (World Bank Data Catalog, dataset 0037712) is licensed Creative Commons Attribution 4.0.
`DT.ODA.ALLD.CD` is likewise sourced from the OECD DAC. Both may be redistributed with attribution.

**Bilateral donor series (*not implemented*; the codes are the World Bank indicators that would supply them)**

| Series | Unit as published | Indicator code | Description | Primary source | Coverage |
| --- | :-: | --- | --- | --- | :-: |
| `oda_donor_usa` | Million USD | `DC.DAC.USAL.CD` | Bilateral net ODA from the United States (peaked at $11.2B in 2005) | OECD DAC / WB | 2003 on |
| `oda_donor_germany` | Million USD | `DC.DAC.DEUL.CD` | Bilateral net ODA from Germany | OECD DAC / WB | 2003 on |
| `oda_donor_japan` | Million USD | `DC.DAC.JPNL.CD` | Bilateral net ODA from Japan (JICA energy & port infrastructure loans) | OECD DAC / WB | 2003 on |
| `oda_donor_uk` | Million USD | `DC.DAC.GBRL.CD` | Bilateral net ODA from the United Kingdom | OECD DAC / WB | 2003 on |
| `oda_donor_eu` | Million USD | `DC.DAC.CECL.CD` | Net development and humanitarian assistance from EU Institutions | OECD DAC / WB | 2003 on |

**Findings on OECD DAC Aid for Iraq**

- **Continuous 24-year post-2000 record:** Every single year from 2000 through 2023 is fully reported with zero missing intervals across headline flows and bilateral donor allocations.
- **The 2005 peak:** In 2005, Net ODA reached **$22,057.1 Million** ($22.06 Billion), mostly debt-related flows recorded as ODA. Accounting for this series is vital for any external debt or capital account modeling.
- **Stabilisation and recovery (2014–2023):** During 2014–2023, international assistance provided an essential counter-cyclical cushion, averaging **$2.0–$2.9 Billion per year** (led by Japan and Germany in infrastructure and stabilization loans).
- **Independent cross-check for CBI Secondary Income:** The Central Bank of Iraq compiles "Foreign Grants" under Secondary Income in its Balance of Payments. OECD DAC provides the authoritative donor-reported mirror to assess disbursements and pipeline execution.

**Decisions for development assistance**

- [x] **Annual frequency.** **Decided:** Preserved strictly at **annual frequency** without artificial monthly interpolation.
- [x] **Series selection (`8` core series).** **Decided:** Headline Net ODA, Grants vs Concessional Loans, and 5 major bilateral/multilateral donors (US, Japan, Germany, UK, EU Institutions).
- [x] **Access.** Same `get` as the other series; no separate `external` module.

## Climate & Environmental Shocks (NASA / ERA5)

Climate shocks in Iraq directly transmit into the macroeconomy through agricultural harvest collapses, electricity demand surges, labor productivity losses during extreme heat, and severe water scarcity. This module provides continuous, satellite-observed meteorological and hydrological time series from the NASA POWER Project and ECMWF ERA5 reanalysis across the national territory of Iraq as well as its distinct sub-national agricultural and urban basins.

> **Decision on Climate & Environmental Shocks:** Include monthly and daily temperature, precipitation, root-zone soil moisture, and land evaporation from **2000 onward** (historical records extend back to 1981 with **zero missing values**). Provides a **national country-wide aggregate (`region="national"`)** by default, with optional provincial/city drill-downs for **Baghdad, Nineveh (Mosul breadbasket), Basra (southern heat & marshes), Erbil (Kurdistan highlands), and Anbar (Euphrates basin)**. *Not implemented*: no parser reads the NASA POWER API yet.

| Source | Format | Frequency and coverage | Terms and access | Role |
| --- | --- | --- | --- | --- |
| [NASA POWER Project](https://power.larc.nasa.gov) (Langley Research Center / GEOS-5 & SMAP satellite reanalysis) | REST API (JSON, CSV), keyless public endpoint | Monthly and Daily, continuous 1981 to present (zero missing values). Resolution: 0.5° x 0.5° global grid | Free, open public access, no API key required; US Government open science data | Primary source for national and regional temperature, rainfall, and soil moisture |
| [ECMWF / Copernicus ERA5 Reanalysis](https://cds.climate.copernicus.eu) | REST API / NetCDF / CSV | Hourly, daily, monthly continuous 1940 to present | Open Data (Copernicus Licence) | Cross-check for national area-weighted climate reanalysis |
| [Iraqi Meteorological Organization (IMOS) via COSIT Chapter 1](https://cosit.gov.iq/documents/AAS2023/1.pdf) | PDF (Annual Statistical Abstract) | Monthly and annual surface station readings for Baghdad, Basra, Mosul, Rutba | Government publication | Domestic ground-truth cross-check |

| Series | Unit as published | NASA Parameter Code | Description | Coverage |
| --- | :-: | --- | --- | :-: |
| `temp_mean_2m` | °C | `T2M` | Mean 2-meter air temperature | 2000 on (1981+) |
| `temp_max_2m` | °C | `T2M_MAX` | Maximum daily/monthly temperature (identifies days > 45°C/50°C) | 2000 on |
| `temp_min_2m` | °C | `T2M_MIN` | Minimum daily/monthly temperature | 2000 on |
| `precipitation` | mm/day or mm/month | `PRECTOTCORR` | Total bias-corrected precipitation (satellite + gauge merged) | 2000 on |
| `soil_moisture_root` | Index (`0.0 – 1.0`) | `GWETROOT` | Root-zone soil wetness (0 to 1 meter depth; agricultural drought indicator) | 2000 on |
| `soil_moisture_surface`| Index (`0.0 – 1.0`) | `GWETTOP` | Surface topsoil moisture (0 to 5 cm depth; dust storm vulnerability) | 2000 on |
| `evaporation_land` | mm/day | `EVLAND` | Total land surface evapotranspiration | 2000 on |

**Predefined Regional Profiles:**
* `national` (Default): National geographic and population-weighted center of Iraq (`33.22°N, 43.68°E`).
* `nineveh`: Northern rainfed wheat belt / Mosul (`36.34°N, 43.13°E`) — explains domestic grain harvest swings.
* `baghdad`: Central Tigris agricultural and population center (`33.31°N, 44.36°E`).
* `basra`: Southern alluvial plain, extreme summer thermal stress, and coastal marshes (`30.51°N, 47.81°E`).
* `erbil`: Northern Kurdistan mountain watershed (`36.19°N, 44.01°E`).
* `anbar`: Western Euphrates river valley (`33.42°N, 43.30°E`).

**Findings on Iraq Satellite Climate Data**

- **Zero missing values across 25 years:** 300 continuous months (2000–2024) verified live for Iraq with 0 missing observations.
- **Accurately captures agricultural boom-and-bust:** Root-zone soil wetness in Nineveh in April plunged to `0.580` during the severe 2021 drought (with only 0.9 mm rain) and surged to `0.860` during the historic 2019 flood boom (122.1 mm rain), perfectly correlating with COSIT wheat production figures.
- **Captures severe summer heat stress:** In Basra and Baghdad, July and August daily temperatures consistently breach 49–51°C, driving peak electricity consumption and public administration shutdowns.
- **Zero API friction:** The NASA POWER API requires no user account, tokens, or API keys, and responds in under 2 seconds.

**Decisions for climate & environmental shocks**

- [x] **Monthly (default) and daily frequencies.** **Decided:** Monthly series by default with optional daily resolution (`freq="daily"`), preserving native observation frequencies without artificial interpolation.
- [x] **National and regional granularity.** **Decided:** Country-level aggregate (`region="national"`) by default, with pre-configured coordinates for the 5 major economic/agricultural basins (Nineveh, Baghdad, Basra, Erbil, Anbar).
- [ ] **Access.** To be decided when the climate feed is implemented.

## Open questions for money and banking

- [x] **Excel contents.** Answered: Key Financial Indicators (`file-179205300470528.xlsx`) is continuous monthly from Dec 2003 to Sep 2026 (plus week ending 1 Oct 2026) and is the sole primary source for Money and Banking; no PDFs or annual bulletins are required.
- [x] **Long continuous monthly history.** All 10 core Money and Banking series are populated monthly from Dec 2003 (or 2004 for FX deposits and policy rates) directly in the Key Financial Indicators Excel sheet.
- [ ] **Statistical Website.** Probably not needed now. Use it only if the Excel files have gaps, and then ask the CBI for permission first, because robots.txt blocks automated access.
- [ ] **Licence.** No CBI terms of reuse found yet. Ask the CBI, or check the cbi.iq site terms.
- [x] **Revisions.** The bulletin says its data may be amended. Confirmed: M2 for Jul 2026 is 171,404 billion IQD in Key Financial Indicators but 171,376 in the Monthly Bulletin, so values change between releases. This supports keeping vintages from the start.
- [x] **Method breaks.** Answered from the Monthly Bulletin Excel file: sheets `1-c`, `4`, and `6` carry the footnote *"تم التعديل وفق احدث المنهجيات الدولية لصندوق النقد الدولي من عام 2012"* ("Amended according to the latest international methodologies of the IMF from 2012"), which is why `1-c`, `5`, `7-a`–`7-c`, `8-a`–`8-c` and `9-a`–`9-c` start in 2012. In addition, sheets `10-a` and `10-b` note a new sectoral credit classification starting in 2025 Q1.
- [x] **Headline foreign reserves.** **Decided:** Use official reserves of the CBI (`Official Reserve`, row 67) as the headline foreign reserves series.
- [x] **Sectoral credit and banking balance sheet tables.** **Decided:** Not published, which avoids yearly series and PDF dependencies.

**New from the Excel files**

- [x] **CPI base periods.** Key Financial Indicators holds CPI on four bases (`1993 = 100` for Dec 2003–Dec 2009, `2007 = 100` for Jan 2009–Dec 2015, `2012 = 100` for Jan 2015–Jan 2024, and `2022 = 100` for Jan 2023–Aug 2026). **Decided:** publish each native base series as its own series, and also construct a unified CPI series by merging all bases together across their 12–13 month overlap windows.
- [x] **Footnoted breaks.** Key Financial Indicators notes 13 numbered breaks (`Notes 1–13`), including investments amended from Jan 2006 (`Note 9`), overnight ID deposits replaced by 7-day deposits in July 2007 (`Note 1`), SDR treatment revised in Oct 2009 and excluded from Nov 2015 (`Note 5`), 91-day T-bills replaced in Jan 2010 (`Note 6`), data amended from Jan 2012 (`Note 11`), discounted T-bills including farmers' dues from Feb 2015 (`Note 8`), and CSD deficit-financing T-bills in Sep 2024 and Feb 2026 (`Note 13`). Each becomes a break flag in metadata/observations.
- [x] **Monthly history for Monthly Bulletin tables.** Verified across all 46 sheets of `file-179015939752236.xlsx`: sheet `1-b` is monthly from Jan 2022; sheet `1-a` is monthly from Jan 2023; all other monthly sheets (`1-c`, `2-a`–`2-c`, `4`–`6`, `11-a`–`11-b`, `12-a`–`12-b`, `6-1`, `6-2`, `7-1`–`7-3`) are monthly from Jan 2024. For non-banking families, pre-2024 history draws on annual PDF bulletins where applicable.

## Families research status

- [x] Money and banking (first pass + Excel verification)
- [x] Exchange rates (parallel & official; first pass)
- [x] Prices: COSIT CPI headline and core (first pass + CBI Excel verification)
- [x] Oil: price, production, exports and revenue (first pass + OPEC PDF & JODI CSV verification)
- [x] Government finance: Ministry of Finance monthly reports & CBI tables (first pass + CBI Excel verification)
- [x] Output: GDP and national accounts (first pass + CBI Excel verification)
- [x] Balance of payments: CBI quarterly BPM6 data (first pass + CBI Excel verification)
- [x] Foreign trade: exports and imports (CBI, COSIT) (first pass + CBI Excel verification)
- [x] Cross-border banking: BIS Locational Banking Statistics (first pass + live SDMX API verification)
- [x] Development assistance & reconstruction: OECD DAC ODA (first pass + API verification)
- [x] Climate & environmental shocks: NASA POWER / ERA5 (first pass + live API verification)

## Sources

- [CBI Monthly Statistical Bulletin page](https://cbi.iq/page/122)
- [CBI Key Financial Indicators page](https://cbi.iq/news/view/94)
- [CBI Annual Statistical Bulletin archive, 2003–2025](https://cbi.iq/page/142)
- [CBI Balance of Payments Data archive, 2000–2026](https://cbi.iq/page/145)
- [CBI Annual Balance of Payments Reports](https://cbi.iq/page/152)
- [CBI Iraq Balance of Payments Guide](https://cbi.iq/page/154)
- [CBI Foreign Trade Data archive](https://cbi.iq/page/146)
- [CBI Annual Statistical Bulletin 2022](https://cbi.iq/static/uploads/up/file-169337742297754.pdf)
- [CBI Monetary Policy Report 2024](https://cbi.iq/static/uploads/up/file-176172293495610.pdf)
- [CBI Monetary Stability Report, Q1 2025](https://cbi.iq/static/uploads/up/file-175791938992330.pdf)
- [CBI Statistical Website](https://www.cbiraq.org/SeriesChart.aspx)
- [COSIT (Authority of Statistics and GIS) Portal](https://cosit.gov.iq)
- [Ministry of Finance Open Budget Portal](https://mof.gov.iq/pages/OBSBudget.aspx)
- [JODI Oil World Database Downloads](https://jodidata.org/oil/database/data-downloads.aspx)
- [Bank for International Settlements (BIS) Stats API & Data Portal](https://data.bis.org)
- [OECD Data Explorer & Creditor Reporting System (CRS)](https://stats.oecd.org)
- [NASA POWER Project (Langley Research Center)](https://power.larc.nasa.gov)
- [Iraqi Meteorological Organization via COSIT Chapter 1](https://cosit.gov.iq/documents/AAS2023/1.pdf)
