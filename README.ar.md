<div dir="rtl">

# iraqdata

[English](README.md)

**إحصاءات الاقتصاد العراقي: منقّحة ومتّسقة وفي مكان واحد.**

[![Code licence: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE)
[![Data licence: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

يوفّر مشروع `iraqdata` السلاسل الزمنية الرئيسة للاقتصاد العراقي (النقد والمصارف، والأسعار، وأسعار الصرف، والنفط، والمالية العامة، والناتج المحلي الإجمالي، وميزان المدفوعات، وغيرها) في جداول جاهزة للاستخدام، يمكن الوصول إليها من لغة بايثون أو تنزيلها ملفاتِ CSV.

## لماذا هذا المشروع

يواجه كل من يدرس الاقتصاد العراقي الصعوبات نفسها:

- **تشتّت البيانات.** تتوزّع بيانات العراق على مواقع البنك المركزي العراقي، والجهاز المركزي للإحصاء، ووزارة المالية، ووزارة النفط، ومنظمة أوبك، ومنظمات دولية أخرى، وكثيرًا ما تُنقل صفحات هذه المواقع أو تُعدَّل من دون إشعار.
- **صعوبة التعامل مع الملفات.** يصدر كثير من البيانات في جداول بيانات معقّدة باللغة العربية أو باللغتين، أو في ملفات PDF، لا في جداول جاهزة للتحليل.
- **الانقطاعات في السلاسل الزمنية.** نُشر الرقم القياسي لأسعار المستهلك على أربع سنوات أساس (1993 و2007 و2012 و2022)، وعدّل البنك المركزي العراقي إحصاءاته النقدية وفق منهجية صندوق النقد الدولي ابتداءً من عام 2012. ويتطلّب ربط هذه السلاسل بصورة صحيحة عملًا دقيقًا.
- **تكرار الجهد.** يقضي الباحثون في الغالب معظم وقتهم في جمع البيانات وتنقيحها قبل أن يبدأ التحليل نفسه.

يُنجز `iraqdata` هذا العمل مرة واحدة، بعناية وشفافية، كي لا يضطرّ المستخدمون إلى تكراره:

- تُسجَّل لكل قيمة مصدرُها وطريقةُ الحصول عليها. تُقرأ <!-- share:begin -->90%<!-- share:end --> من المشاهدات مباشرة من منشورات رسمية مؤرشفة، أما البقية فمحسوبة من سلاسل أخرى، أو مأخوذة من مصدر غير رسمي، أو مُدخلة يدويًا من منشورات، أو مجهولة المصدر؛ وكل فترة من هذا النوع مذكورة في
  [docs/series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md#data-not-observed-from-an-archived-official-file)، وتحمل القيم المُدخلة يدويًا أو مجهولة المصدر رمز الحالة `U`.
- تُعلَّم الانقطاعات في السلاسل، مثل تغيير سنة الأساس، ولا تُخفى.
- تخضع البيانات لفحوص جودة آلية قبل كل إصدار.

يقدّم هذا المشروع نقطة انطلاق مشتركة ومجانية، تتيح للباحثين دراسة الاقتصاد العراقي بسرعة أكبر، وتسهّل تكرار النتائج والتحقق منها.

## لمن هذا المشروع

- **الباحثون والطلبة:** سلاسل موثّقة مع مصادرها، جاهزة للتقدير القياسي وإعادة إنتاج النتائج.
- **الصحفيون والجمهور:** أرقام رسمية في مكان واحد، يمكن تتبّع كل منها إلى الجهة التي نشرته.
- **المصارف والشركات والمستثمرون:** مؤشرات نقدية ومؤشرات لأسعار الصرف والنفط والمالية العامة، بوحدات قياس ودوريات محدّدة.
- **صانعو السياسات والمحللون:** سلاسل طويلة ومتّسقة للرصد والتقييم.

## البيانات المتاحة

*السلسلة* مؤشر واحد يُقاس عبر الزمن، مثل عرض النقد الواسع (M2) شهرًا بعد شهر.
يضمّ المشروع 82 سلسلة في 9 مجالات:

| المجال | أمثلة | الجهة الناشرة الأصلية |
|---|---|---|
| النقد والمصارف | عرض النقد الواسع `money.m2`، سعر السياسة `money.policy_rate`، الاحتياطيات الرسمية `money.reserves_official`، الائتمان النقدي المباشر الممنوح للقطاع الخاص من المصارف التجارية `credit.private_total`، صافي الديون الحكومية للجهاز المصرفي `govt.system_net_claims` | البنك المركزي العراقي |
| أسعار الصرف | سعر الصرف الرسمي `fx.official`، سعر الصرف في السوق الموازية في بغداد `parallel_rate_iraq`، مبيعات البنك المركزي للعملة الأجنبية `fx.auction_total` | البنك المركزي العراقي؛ مشروع Iraq-parallel-exchange-rate |
| الأسعار والتضخم | الرقم القياسي العام لأسعار المستهلك `cpi_headline` والرقم القياسي الأساس `cpi_core` | الجهاز المركزي للإحصاء، عن طريق البنك المركزي العراقي |
| النفط | سعر خام برنت `oil_price_brent`، سعر خام البصرة `oil_price_basrah`، إنتاج النفط الخام `crude_production_direct` | وزارة النفط وشركة تسويق النفط (سومو)، وأوبك وJODI، وإدارة معلومات الطاقة الأمريكية |
| المالية العامة | الإيرادات `fiscal.revenue_total`، النفقات `fiscal.expenditure_total`، الفائض أو العجز `fiscal.balance` | وزارة المالية، عن طريق البنك المركزي العراقي |
| الناتج المحلي الإجمالي | الناتج بالأسعار الجارية `gdp.nominal`، الناتج بالأسعار الثابتة `gdp.real`، الناتج غير النفطي `gdp.nominal_nonoil` | الجهاز المركزي للإحصاء |
| ميزان المدفوعات والتجارة | الحساب الجاري `bop.current_account`، الصادرات `trade.exports_total`، الواردات `trade.imports_total` | البنك المركزي العراقي |
| المصارف عبر الحدود | المطالبات `bis.lbs.claims_total`، الالتزامات `bis.lbs.liabilities_total` | بنك التسويات الدولية |
| المساعدات الإنمائية | صافي المساعدات الإنمائية الرسمية المتلقّاة `oecd.dac.oda_total_net` | منظمة التعاون الاقتصادي والتنمية / البنك الدولي |

راجع [القائمة الكاملة للسلاسل الـ82](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md) (باللغة الإنكليزية).

## التثبيت

```bash
pip install iraqdata
```

يتطلّب المشروع بايثون 3.10 أو أحدث. لتجربة أحدث نسخة قيد التطوير، نفّذ
`pip install git+https://github.com/husseinkh90/iraqdata` بدلًا من ذلك.
تُشغَّل الاختبارات على الإصدارات من 3.10 إلى 3.13.

## طريقة الاستخدام

يشرح [دليل المستخدم](https://github.com/husseinkh90/iraqdata/blob/main/docs/user_guide.md) (باللغة الإنكليزية) كل خطوة بالتفصيل: البحث عن السلاسل، وتحميلها وإعادة تسميتها، ورموز الحالة، ومصدر كل قيمة، وحفظ البيانات، وتثبيت إصدار البيانات، والعمل من دون اتصال، ومعنى كل رسالة خطأ.

استورد المكتبة:

```python
import iraqdata as id
```

حمّل سلسلة واحدة في جدول مفهرس بالتاريخ:

```python
df = id.get_series("money.m2")
print(df.tail())
```

اطلب عدة سلاسل معًا. تُعاد السلاسل ذات الدوريات المختلفة (شهرية، يومية) في جدول مستقل لكل دورية، فلا تُخلط ولا يُحسب لها متوسط:

```python
tables = id.get_series(["money.m2", "fx.official"])
print(tables["monthly"].tail())
print(tables["daily"].tail())
```

حدّد فترة زمنية وأسماء الأعمدة التي تريدها:

```python
df = id.get_series({"Broad money": "m2", "Narrow money": "m1"}, start="2020-01", end="2024-12")
print(df.head())
```

استخدم الأسماء المختصرة للمؤشرات الشائعة، مثل `m2` و`cpi` و`official_rate` و`parallel_rate` و`brent` و`gdp`:

```python
df = id.get_series(["m2", "cpi"])
print(df.tail())
```

ابحث بالعربية أو بالإنكليزية، أو حمّل جدولًا كاملًا لموضوع واحد:

```python
print(id.search("inflation"))
print(id.search("دينار"))
money = id.get_table("money_banking_monthly")
print(money.head())
```

تُنزَّل البيانات عند طلبها أول مرة، وتُحفظ على جهازك، فتعمل الطلبات اللاحقة من دون اتصال بالإنترنت.

### رموز الحالة

لكل قيمة رمز حالة: `A` عادية، `P` أولية، `B` انقطاع في السلسلة (مثل تغيير سنة أساس الرقم القياسي)، `E` مُقدَّرة، `M` مفقودة، `U` منخفضة الموثوقية. لعرض الرموز بجانب القيم استخدم `flags=True`:

```python
df = id.get_series(["cpi", "m2"], flags=True)
print(df[df["cpi_flag"].isin(["B", "P"])])
```

من دون `flags=True` يظهر التحذير `FlagWarning` عندما يحتوي الجدول على انقطاعات أو قيم أولية. لإخفائه:
`warnings.filterwarnings("ignore", category=id.FlagWarning)`.

### القيم كما نُشرت في تاريخ سابق

تُنقَّح القيم مع مرور الوقت. يعيد الخيار `as_of` القيم كما نُشرت في تاريخ معيّن، اعتمادًا على سجلّ الإصدارات التاريخية (vintages) المرفق بكل إصدار. يحتوي الإصدار على المجلد `history/` بعد أن تُنقَّح قيمة منشورة أو تُسحب. الإصداران المنشوران حتى الآن، `data-2026-10` و`data-2026-11`، لا يحتويان عليه لأن أي قيمة منشورة لم تُنقَّح بعد، ولذلك يؤدي استخدام `as_of` معهما إلى الخطأ `NoVintageHistoryError`. ابتداءً من أول إصدار يتضمن سجلًا تاريخيًا:

<!-- not run: needs a release with a history folder -->
```python
then = id.get_series("cpi", wide=False, as_of="2026-10-28")
print(then[["date", "value", "realtime_start"]].tail())
```

### إصدار البيانات المستخدم

تُنشر البيانات في إصدارات مؤرّخة (`data-2026-10`، `data-2026-11`، ...). تحصل افتراضيًا على أحدث إصدار، ويُحدَّد عند أول استخدام للمكتبة ثم يُحتفظ به إلى أن تطلب إصدارًا أحدث بالأمر `id.refresh_latest()`، فلا تتغيّر نتائجك من تلقاء نفسها. ولضمان إمكانية إعادة إنتاج النتائج، ثبّت إصدارًا محددًا؛ إذ يُستخدم الإصدار المثبّت دائمًا، حتى داخل نسخة من هذا المستودع:

```python
id.set_release("data-2026-11")    # or set the environment variable IRAQDATA_RELEASE
print(id.get_data_source())       # release data-2026-11 (pinned with set_release) from husseinkh90/iraqdata
```

للأمر `id.set_release()` الأولوية على متغيّر البيئة `IRAQDATA_RELEASE`، ويُلغي `id.set_release(None)` التثبيت. تُحفظ الملفات المنزّلة في `~/.cache/iraqdata/` (أو في `IRAQDATA_CACHE_DIR`)، في مجلد مستقل لكل إصدار. يحذف الأمر `id.clear_cache()` الملفات التي نزّلتها المكتبة فقط، ولا يمسّ أي ملف آخر في ذلك المجلد. تُنزَّل البيانات من إصدارات المستودع `husseinkh90/iraqdata` على GitHub، ويمكن استخدام مستودع آخر بضبط المتغيّر `IRAQDATA_REPO`.

## الاستخدام من دون بايثون

كل جدول متاح ملفَّ CSV في
[صفحة أحدث إصدار](https://github.com/husseinkh90/iraqdata/releases/latest)، ملف واحد لكل جدول
(مثل `money_banking_monthly.csv`). ويبيّن
[دليل R وStata](https://github.com/husseinkh90/iraqdata/blob/main/docs/r_and_stata.md) (باللغة الإنكليزية)
كيفية تحميل سلسلة، وتحويل التواريخ، واستخدام رموز الحالة، وإعادة تشكيل الجدول.

- **Excel:** من قائمة Data اختر From Web، ثم الصق
  `https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv`.
- **Stata:**

  ```stata
  import delimited "https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv", clear
  ```

- **R:**

  ```r
  money <- read.csv("https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv")
  ```

## الاستشهاد

إذا استخدمت `iraqdata` فيُرجى الاستشهاد به:

```bibtex
@software{khalid2026iraqdata,
  author  = {Khalid, Hussein},
  title   = {iraqdata: Open, Documented, and Reproducible Iraqi Macroeconomic Data Package},
  year    = {2026},
  version = {1.0.0},
  url     = {https://github.com/husseinkh90/iraqdata}
}
```

سيُضاف معرّف DOI بعد أرشفة الإصدار في Zenodo.

يُرجى الاستشهاد بالمكتبة وبالجهات الناشرة الأصلية للسلاسل التي تستخدمها معًا (مصادر كل سلسلة مذكورة في `datapackage.json`، وشروط استخدامها في
[`pipeline/metadata/sources.yaml`](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml)):
- البنك المركزي العراقي؛
- الجهاز المركزي للإحصاء؛
- وزارة المالية؛
- وزارة النفط وشركة تسويق النفط (سومو)؛
- أوبك وJODI؛
- إدارة معلومات الطاقة الأمريكية وFRED؛
- بنك التسويات الدولية؛
- البنك الدولي؛
- مشروع Iraq-parallel-exchange-rate (سعر الصرف الموازي ابتداءً من عام 2023).

## الترخيص

- **الشيفرة البرمجية:** [MIT](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE).
- **البيانات:** البيانات المجمّعة والمشتقّة مرخّصة بموجب [CC BY 4.0](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA). أما البيانات الأصلية فتبقى خاضعة لشروط الجهات التي نشرتها، وبعضها لا يذكر ترخيصًا؛ راجع
  [`pipeline/metadata/sources.yaml`](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml).

## المساهمة

إذا وجدت رقمًا خاطئًا أو رسالة غير واضحة أو سلسلة ناقصة، فيُرجى فتح بلاغ (issue) في
<https://github.com/husseinkh90/iraqdata/issues> مع ذكر السلسلة والتواريخ وإصدار البيانات
(`print(id.get_data_source())`). تصف الوثائق في
[`docs/`](https://github.com/husseinkh90/iraqdata/tree/main/docs) (باللغة الإنكليزية) السلاسل، والأرقام القياسية المربوطة للأسعار، وطريقة استخدام البيانات.

</div>
