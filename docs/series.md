# The full list of series

Each row is one *series*: a single indicator measured over time, such as broad money (M2) month by
month. Get any of them with `iraqdata.get_series("<series>")`, or list them from Python with
`iraqdata.list_series()`.

Not every number is read directly from an official file. Some are computed from other series,
some were typed in by hand from a publication that is not archived here, and a few come from a
seed of unknown publisher or from a non-official source. Each series' origin, period by period, is
listed at the end of this page ([Data not observed from an archived official file](#data-not-observed-from-an-archived-official-file)),
in the `origin` and `official` columns of `iraqdata.list_series()`, and in full by
`iraqdata.get_origin("<series>")`.


## 1. Money & Banking
*Source: Central Bank of Iraq (CBI)*

<!-- series:money_banking:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `money.currency_outside_banks` | Monthly | Billion IQD | 2004-01 | Banknotes and coins held by the public outside commercial banks. |
| `money.m0` | Monthly | Billion IQD | 2004-01 | Monetary base: currency outside banks plus commercial bank reserves at CBI. |
| `money.m1` | Monthly | Billion IQD | 2004-01 | Narrow money: currency outside banks plus demand (checking) deposits. |
| `money.m2` | Monthly | Billion IQD | 2004-01 | Headline broad money: M1 plus savings, time, and foreign currency deposits. |
| `money.fx_deposits` | Monthly | Billion IQD | 2004-12 | Resident private sector foreign currency deposits in commercial banks. |
| `money.reserves_official` | Monthly | Billion IQD | 2004-01 | Official gross foreign exchange reserves held by CBI (USD, Treasuries, gold). |
| `money.policy_rate` | Monthly | Percent | 2004-08 | Official benchmark policy interest rate set by CBI. |
| `money.bank_deposit_rate` | Monthly | Percent | 2004-01 | Commercial banks' weighted average interest rate on 1-year fixed deposits. |
| `money.bank_lending_rate` | Monthly | Percent | 2004-01 | Commercial banks' weighted average interest rate on medium-term loans. |
| `money.required_reserves` | Monthly | Billion IQD | 2004-12 | Statutory mandatory reserves maintained by commercial banks at CBI. |

<!-- series:money_banking:end -->

## 2. Exchange Rates
*Sources: Central Bank of Iraq (CBI) & Baghdad Market Consensus*

<!-- series:exchange_rates:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `parallel_rate_iraq` | Daily | IQD per USD | 2004-01-01 | Daily closing parallel market exchange rate in Baghdad: CBI's published market rate to 2022, then the Baghdad close of the [Iraq-parallel-exchange-rate](https://github.com/HusseinKh90/Iraq-parallel-exchange-rate) dealer consensus (CC-BY 4.0). Flag `B` on 2023-01-01 marks the change of source. |
| `fx.official` | Daily | IQD per USD | 2004-01-01 | Official statutory exchange rate set by CBI for government foreign exchange (CBI workbook, `cbi.iq/page/144`). |

<!-- series:exchange_rates:end -->

## 3. Oil Sector
*Sources: U.S. EIA (International Energy Statistics; Brent via FRED), JODI-Oil, and OPEC Monthly Oil Market Reports (transcribed figures)*

<!-- series:oil:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `crude_production_secondary` | Monthly | Th. Barrels/Day | 2004-01 | Iraq crude production estimated by secondary sources (U.S. EIA International Energy Statistics). |
| `crude_production_direct` | Monthly | Th. Barrels/Day | 2007-01 | Iraq crude production reported by the Ministry of Oil: read from JODI to March 2024, then typed in from OPEC MOMR figures (flag `U`). |
| `oil_price_basrah` | Monthly | USD per Barrel | 2004-07 | Basrah crude price, OPEC MOMR anchor months only: ten prices typed in from OPEC reports (flag `U`). The other months are not estimated. |
| `oil_price_brent` | Daily | USD per Barrel | 2004-01-06 | Daily Europe Brent spot crude oil price (U.S. EIA via FRED). |

<!-- series:oil:end -->

## 4. Consumer Prices & Inflation
*Compiled by the Central Organization for Statistics and Information Technology (COSIT); read from
the Central Bank of Iraq (CBI) Key Financial Indicators workbook*

<!-- series:prices:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `cpi.headline_1993` | Monthly | Index | 2004-01 | Headline CPI under official 1993 base basket. |
| `cpi.headline_2007` | Monthly | Index | 2009-01 | Headline CPI under official 2007 base basket. |
| `cpi.headline_2012` | Monthly | Index | 2015-01 | Headline CPI under official 2012 base basket. |
| `cpi.headline_2022` | Monthly | Index | 2023-01 | Headline CPI under official 2022 base basket. |
| `cpi.core_1993` | Monthly | Index | 2004-01 | Core CPI excluding Fuel & Lighting and Transport & Comm. (1993 basket). |
| `cpi.core_2007` | Monthly | Index | 2009-01 | Core CPI excluding Fruit & Vegetables and Kerosene & LPG (2007 basket). |
| `cpi.core_2012` | Monthly | Index | 2015-01 | Core CPI excluding volatile components under 2012 methodology. |
| `cpi.core_2022` | Monthly | Index | 2023-01 | Current Core CPI under 2022 rebased methodology. |
| `cpi_headline` | Monthly | Index | 2004-01 | Index, 2022 base (approx. 2022=100). Headline CPI linked by iraqdata from the 1993, 2007, 2012 and 2022 bases by a December one-month overlap; flagged `B` at each switch month (2010-01, 2016-01, 2024-01). Not an official series; see [the method doc](linked_inflation_method.md). |
| `cpi_core` | Monthly | Index | 2004-01 | Index, 2022 base (approx. 2022=100). Core CPI linked the same way, flagged `B` at the same switch months. The core definition changes at the 2010-01 switch (1993 base: excludes fuel & lighting and transport & communications; later bases: fruit & vegetables and kerosene & LPG). See [the method doc](linked_inflation_method.md). |

<!-- series:prices:end -->

## 5. Fiscal & Public Finance
*Source: Ministry of Finance (MoF) via CBI Statistical Bulletins from 2024. The 2004–2023 values come
from a seed table compiled by the maintainer whose publisher per value is unknown (flag `U`).*

<!-- series:fiscal:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `fiscal.revenue_total` | Annual | Million IQD | 2004 | Total actual government revenues (oil and non-oil receipts). |
| `fiscal.revenue_current` | Annual | Million IQD | 2004 | Current operational revenue receipts. |
| `fiscal.revenue_investment` | Annual | Million IQD | 2004 | Capital revenues received by the treasury. |
| `fiscal.expenditure_total` | Annual | Million IQD | 2004 | Total actual general government outlays (current plus capital). |
| `fiscal.expenditure_current` | Annual | Million IQD | 2004 | Operating expenditure (public payroll, pensions, subsidies, social safety). |
| `fiscal.expenditure_investment` | Annual | Million IQD | 2004 | Investment expenditure on infrastructure, oil development, and public projects. |
| `fiscal.balance` | Annual | Million IQD | 2004 | Actual budget outturn balance: revenue minus expenditure. |

<!-- series:fiscal:end -->

## 6. National Accounts / GDP
*Source: Central Organization for Statistics and Information Technology (COSIT). The totals and oil
components were typed in from COSIT publications that are not archived here (flag `U`); the non-oil
series are computed as total minus oil.*

<!-- series:gdp:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `gdp.nominal` | Quarterly | Million IQD | 2015-Q1 | Headline Gross Domestic Product at current basic prices. |
| `gdp.nominal_nonoil` | Quarterly | Million IQD | 2015-Q1 | Value added of non-oil sectors at current basic prices. |
| `gdp.nominal_oil` | Quarterly | Million IQD | 2015-Q1 | Value added of crude petroleum and natural gas at current basic prices. |
| `gdp.real` | Quarterly | Million IQD | 2015-Q1 | Headline real Gross Domestic Product in constant 2007 basic prices. |
| `gdp.real_nonoil` | Quarterly | Million IQD | 2015-Q1 | Real value added of non-oil sectors in constant 2007 basic prices. |
| `gdp.real_oil` | Quarterly | Million IQD | 2015-Q1 | Real value added of crude petroleum in constant 2007 basic prices. |

<!-- series:gdp:end -->

## 7. Balance of Payments & Foreign Trade
*Source: Central Bank of Iraq (CBI)*

<!-- series:bop_trade:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `bop.current_account` | Quarterly | Million USD | 2013-Q1 | Net current account balance (goods, services, primary & secondary income). |
| `bop.trade_balance` | Quarterly | Million USD | 2013-Q1 | Net merchandise trade balance (FOB exports minus FOB imports). |
| `bop.services_net` | Quarterly | Million USD | 2013-Q1 | Net services balance (transportation, travel, construction, government). |
| `bop.income_net` | Quarterly | Million USD | 2013-Q1 | Net primary income (employee compensation and investment income). |
| `bop.transfers_net` | Quarterly | Million USD | 2013-Q1 | Net secondary income / current transfers (worker remittances, official transfers). |
| `bop.capital_account` | Quarterly | Million USD | 2013-Q1 | Net capital account transfers. |
| `bop.financial_account` | Quarterly | Million USD | 2013-Q1 | Net financial flows (direct, portfolio, deposits abroad, reserve assets). |
| `bop.reserve_assets_change` | Quarterly | Million USD | 2013-Q1 | Net quarterly change in official foreign reserve assets held by CBI. |
| `trade.exports_total` | Quarterly | Million USD | 2013-Q1 | Total merchandise exports (crude oil, refined products, non-oil goods). |
| `trade.exports_crude_oil` | Quarterly | Million USD | 2013-Q1 | Total crude oil export earnings shipped by SOMO and international operators. |
| `trade.exports_oil_products` | Quarterly | Million USD | 2013-Q1 | Exports of refined petroleum products. |
| `trade.exports_nonoil` | Quarterly | Million USD | 2013-Q1 | Non-oil merchandise exports (dates, agricultural goods, sulfur, fertilizers). |
| `trade.imports_total` | Quarterly | Million USD | 2013-Q1 | Total merchandise imports compiled from banking financial settlements. |
| `trade.imports_government` | Quarterly | Million USD | 2013-Q1 | Imports executed by Iraqi ministries (food ration basket, pharmaceuticals). |
| `trade.imports_private` | Quarterly | Million USD | 2013-Q1 | Private commercial imports (consumer durables, vehicles, machinery). |

<!-- series:bop_trade:end -->

## 8. Cross-Border Banking Statistics
*Source: Bank for International Settlements (BIS Locational Banking Statistics)*

All six series are measured from the books of the BIS reporting banks (all reporting countries),
with Iraqi residents as the counterparty. A liability of those banks to Iraq is an asset of Iraq
(deposits and similar), and a claim on Iraq is a debt of Iraq, so a positive
`bis.lbs.net_position` means Iraqi residents are net creditors of the reporting banks.

<!-- series:bis:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `bis.lbs.claims_total` | Quarterly | Million USD | 2004-Q1 | Total cross-border claims of BIS reporting banks on Iraqi counterparties. |
| `bis.lbs.liabilities_total` | Quarterly | Million USD | 2004-Q1 | Total liabilities of BIS reporting banks to Iraqi entities (deposits, custody). |
| `bis.lbs.liabilities_banks` | Quarterly | Million USD | 2004-Q1 | International bank liabilities to the Iraqi banking system (CBI & commercial banks). |
| `bis.lbs.liabilities_nonbank` | Quarterly | Million USD | 2004-Q1 | International bank liabilities to Iraqi non-bank counterparties (government & private). |
| `bis.lbs.claims_nonbank` | Quarterly | Million USD | 2004-Q1 | Cross-border loans extended by international banks to Iraqi non-banks. |
| `bis.lbs.net_position` | Quarterly | Million USD | 2004-Q1 | Iraq's net position against BIS reporting banks: their liabilities to Iraqi residents minus their claims on Iraqi residents. Positive means Iraq is a net creditor of the reporting banks. Cross-border bank positions only; not the international investment position. |

<!-- series:bis:end -->

## 9. Official Development Assistance
*Source: OECD Development Assistance Committee (DAC), via World Bank WDI indicators*

<!-- series:oecd:begin -->

| Series | Frequency | Unit | Starts | Description |
| :--- | :---: | :---: | :---: | :--- |
| `oecd.dac.oda_total_net` | Annual | Million USD | 2004 | Net ODA and official aid received (WDI `DT.ODA.ALLD.CD`, from OECD DAC data): disbursements minus principal repayments. |
| `oecd.dac.grants_excl_tc` | Annual | Million USD | 2004 | Grants received, excluding technical cooperation (WDI `BX.GRT.EXTA.CD.WD`, from OECD DAC table DAC2A). Not total ODA grants. |

<!-- series:oecd:end -->

<!-- origin:begin -->

### Origin of every series

Generated from `src/iraqdata/series_catalog.yaml` by `pipeline/docs_origin.py`; do not edit by hand.

| Series | Origin |
|--------|--------|
| `money.currency_outside_banks` | observed 2004-01..open |
| `money.m0` | observed 2004-01..open |
| `money.m1` | observed 2004-01..open |
| `money.m2` | observed 2004-01..open |
| `money.fx_deposits` | observed 2004-12..open |
| `money.reserves_official` | observed 2004-01..open |
| `money.policy_rate` | observed 2004-08..open |
| `money.bank_deposit_rate` | observed 2004-01..open |
| `money.bank_lending_rate` | observed 2004-01..open |
| `money.required_reserves` | observed 2004-12..open |
| `parallel_rate_iraq` | observed 2004-01-01..2022-12-31; observed (unofficial) 2023-01-01..open |
| `fx.official` | observed 2004-01-01..open |
| `crude_production_secondary` | observed 2004-01..open |
| `crude_production_direct` | observed 2007-01..2024-03; transcribed 2024-04..open |
| `oil_price_basrah` | transcribed 2004-07..open |
| `oil_price_brent` | observed 2004-01-06..open |
| `cpi.headline_1993` | observed 2004-01..open |
| `cpi.headline_2007` | observed 2009-01..open |
| `cpi.headline_2012` | observed 2015-01..open |
| `cpi.headline_2022` | observed 2023-01..open |
| `cpi.core_1993` | observed 2004-01..open |
| `cpi.core_2007` | observed 2009-01..open |
| `cpi.core_2012` | observed 2015-01..open |
| `cpi.core_2022` | observed 2023-01..open |
| `cpi_headline` | derived (unofficial) 2004-01..open |
| `cpi_core` | derived (unofficial) 2004-01..open |
| `fiscal.revenue_total` | unknown (unofficial) 2004..2023; observed 2024..open |
| `fiscal.revenue_current` | unknown (unofficial) 2004..2023; observed 2024..open |
| `fiscal.revenue_investment` | unknown (unofficial) 2004..2023; observed 2024..open |
| `fiscal.expenditure_total` | unknown (unofficial) 2004..2023; observed 2024..open |
| `fiscal.expenditure_current` | unknown (unofficial) 2004..2023; observed 2024..open |
| `fiscal.expenditure_investment` | unknown (unofficial) 2004..2023; observed 2024..open |
| `fiscal.balance` | unknown (unofficial) 2004..2023; observed 2024..open |
| `bop.current_account` | observed 2013-Q1..open |
| `bop.trade_balance` | observed 2013-Q1..open |
| `bop.services_net` | observed 2013-Q1..open |
| `bop.income_net` | observed 2013-Q1..open |
| `bop.transfers_net` | observed 2013-Q1..open |
| `bop.capital_account` | observed 2013-Q1..open |
| `bop.financial_account` | observed 2013-Q1..open |
| `bop.reserve_assets_change` | observed 2013-Q1..open |
| `trade.exports_total` | observed 2013-Q1..open |
| `trade.exports_crude_oil` | observed 2013-Q1..open |
| `trade.exports_oil_products` | observed 2013-Q1..open |
| `trade.exports_nonoil` | observed 2013-Q1..open |
| `trade.imports_total` | observed 2013-Q1..open |
| `trade.imports_government` | observed 2013-Q1..open |
| `trade.imports_private` | observed 2013-Q1..open |
| `gdp.nominal` | transcribed 2015-Q1..2019-Q4; observed 2020-Q1..2021-Q2; transcribed 2021-Q3..2021-Q4; observed 2022-Q1..2022-Q1; transcribed 2022-Q2..2022-Q3; observed 2022-Q4..open |
| `gdp.nominal_nonoil` | derived 2015-Q1..open |
| `gdp.nominal_oil` | transcribed 2015-Q1..2019-Q4; observed 2020-Q1..2021-Q2; transcribed 2021-Q3..2021-Q4; observed 2022-Q1..2022-Q1; transcribed 2022-Q2..2022-Q3; observed 2022-Q4..2023-Q2; transcribed 2023-Q3..2023-Q3; observed 2023-Q4..open |
| `gdp.real` | transcribed 2015-Q1..2019-Q4; observed 2020-Q1..2021-Q2; transcribed 2021-Q3..2021-Q4; observed 2022-Q1..2022-Q1; transcribed 2022-Q2..2022-Q3; observed 2022-Q4..open |
| `gdp.real_nonoil` | derived 2015-Q1..open |
| `gdp.real_oil` | transcribed 2015-Q1..2019-Q4; observed 2020-Q1..2021-Q2; transcribed 2021-Q3..2021-Q4; observed 2022-Q1..2022-Q1; transcribed 2022-Q2..2022-Q3; observed 2022-Q4..open |
| `bis.lbs.claims_total` | observed 2004-Q1..open |
| `bis.lbs.liabilities_total` | observed 2004-Q1..open |
| `bis.lbs.liabilities_banks` | observed 2004-Q1..open |
| `bis.lbs.liabilities_nonbank` | observed 2004-Q1..open |
| `bis.lbs.claims_nonbank` | observed 2004-Q1..open |
| `bis.lbs.net_position` | derived 2004-Q1..open |
| `oecd.dac.oda_total_net` | observed 2004..open |
| `oecd.dac.grants_excl_tc` | observed 2004..open |

## Data not observed from an archived official file

These periods are derived, modelled, transcribed by hand, of unknown origin, or observed from a non-official source. Transcribed and unknown-origin values carry status flag `U`, modelled values `E`; derived values take the flag of their inputs.

| Series | Periods | Class | Method | Source |
|--------|---------|-------|--------|--------|
| `parallel_rate_iraq` | 2023-01-01..open | observed (unofficial) | Read from the Iraq-parallel-exchange-rate dataset (Baghdad close of dealer quotes) | HusseinKh90/Iraq-parallel-exchange-rate dealer consensus (CC-BY 4.0) |
| `crude_production_direct` | 2024-04..open | transcribed | Typed in from OPEC Monthly Oil Market Report direct-communication figures; source document not archived | OPEC Monthly Oil Market Report (issue and table not recorded); record `pipeline/raw/transcribed/opec_momr_crude_direct_2026-10-25.csv` |
| `oil_price_basrah` | 2004-07..open | transcribed | Ten anchor months typed in from OPEC Monthly Oil Market Reports; source documents not archived | OPEC Monthly Oil Market Report (issues not recorded); record `pipeline/raw/transcribed/opec_momr_basrah_anchors_2026-10-25.csv` |
| `cpi_headline` | 2004-01..open | derived (unofficial) | Linked from the four published CPI bases (1993, 2007, 2012, 2022 = 100) by a December one-month overlap, switching base each January after an overlap year (flag B); see docs/linked_inflation_method.md | Central Bank of Iraq & COSIT |
| `cpi_core` | 2004-01..open | derived (unofficial) | Linked from the four published CPI bases (1993, 2007, 2012, 2022 = 100) by a December one-month overlap, switching base each January after an overlap year (flag B); see docs/linked_inflation_method.md | Central Bank of Iraq & COSIT |
| `fiscal.revenue_total` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `fiscal.revenue_current` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `fiscal.revenue_investment` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `fiscal.expenditure_total` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `fiscal.expenditure_current` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `fiscal.expenditure_investment` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `fiscal.balance` | 2004..2023 | unknown (unofficial) | Seed table compiled by the maintainer from unnamed publisher documents (raw manifest, 2026-10-25); the origin stays unknown, but of the 108 values the CBI Monthly Statistical Bulletin (sheet 6-1) also prints for 2004-2023, 106 are identical and 2 differ only because the bulletin has two 2012 columns transposed (pipeline/check_fiscal_seed.py) | unknown (pipeline/seeds/iraq_fiscal_historical.csv) |
| `gdp.nominal` | 2015-Q1..2019-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal` | 2021-Q3..2021-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal` | 2022-Q2..2022-Q3 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal_nonoil` | 2015-Q1..open | derived | Computed as gdp.nominal minus gdp.nominal_oil | COSIT (via the transcribed totals); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal_oil` | 2015-Q1..2019-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal_oil` | 2021-Q3..2021-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal_oil` | 2022-Q2..2022-Q3 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.nominal_oil` | 2023-Q3..2023-Q3 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real` | 2015-Q1..2019-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real` | 2021-Q3..2021-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real` | 2022-Q2..2022-Q3 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real_nonoil` | 2015-Q1..open | derived | Computed as gdp.real minus gdp.real_oil | COSIT (via the transcribed totals); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real_oil` | 2015-Q1..2019-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real_oil` | 2021-Q3..2021-Q4 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `gdp.real_oil` | 2022-Q2..2022-Q3 | transcribed | Typed in from COSIT quarterly national accounts; the source document is not archived | COSIT Directorate of National Accounts (document not recorded); record `pipeline/raw/transcribed/cosit_gdp_quarterly_2026-10-28.csv` |
| `bis.lbs.net_position` | 2004-Q1..open | derived | Computed as liabilities_total minus claims_total | Bank for International Settlements (BIS) |

<!-- origin:end -->
