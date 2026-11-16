<div dir="rtl">

# iraqdata

[English](https://github.com/husseinkh90/iraqdata/blob/main/README.md)

**إحصاءات الاقتصاد العراقي: منقّحة ومتّسقة وفي مكان واحد.**

[![Code licence: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE)
[![Data licence: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

يوفّر مشروع `iraqdata` السلاسل الزمنية الرئيسة للاقتصاد العراقي (النقد والمصارف، والأسعار، وأسعار الصرف، والنفط، والمالية العامة، والناتج المحلي الإجمالي، وميزان المدفوعات، وغيرها) في جداول جاهزة للاستخدام، متاحة من خلال لغة بايثون أو للتنزيل ملفاتِ CSV.

## لماذا `iraqdata`؟

يتطلّب تحليل بيانات الاقتصاد الكلي العراقي حاليًا جهدًا كبيرًا في عمليات الاستخراج والتحويل والتحميل (ETL). يزيل `iraqdata` هذا العبء، فيتفرّغ الباحثون والمحللون للنمذجة. وتعالج المكتبة أربعة تحدّيات بنيوية في البيانات:

- **وصول مركزي:** تتوزّع البيانات الاقتصادية العراقية بين البنك المركزي العراقي، وهيئة الإحصاء ونظم المعلومات الجغرافية (CSGIS)، ووزارتَي المالية والنفط، ومنظمة أوبك، والمنظمات الدولية. ويجمع `iraqdata` هذه المصادر في مكتبة بايثون واحدة.
- **صيغ جاهزة للتحليل:** يغني عن استخلاص البيانات من ملفات PDF أو معالجة جداول البيانات المعقّدة ثنائية اللغة (العربية والإنكليزية)، ويقدّم `iraqdata` جداول بيانات (DataFrames) منقّحة ومحدّدة الأنواع.
- **سلاسل زمنية متصلة:** يربط سنوات الأساس الأربع للرقم القياسي لأسعار المستهلك (1993 و2007 و2012 و2022) في رقمين قياسيين متصلين، عام وأساس (`cpi_headline` و`cpi_core`)، مع الإبقاء على كل سنة أساس أصلية سلسلةً مستقلة. والأرقام القياسية المربوطة من إعداد `iraqdata`، وطريقة ربطها موثّقة في [docs/linked_inflation_method.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/linked_inflation_method.md).
- **سير عمل مختصر:** يستهلك جمع البيانات وترجمتها وتنقيحها عادةً معظم وقت المشروع البحثي، ويختصر `iraqdata` مرحلة الإعداد هذه، فينتقل الباحثون مباشرة إلى التحليل.

تُسجَّل لكل قيمة مصدرُها وطريقةُ الحصول عليها. تأتي <!-- share:begin -->90%<!-- share:end --> من المشاهدات مباشرة من منشورات رسمية مؤرشفة، والاستثناءات مذكورة في [docs/series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md#data-not-observed-from-an-archived-official-file).

يتيح `iraqdata`، بوصفه أساسًا مجانيًا ومفتوح المصدر، دراسة الاقتصاد العراقي بكفاءة أكبر، ويسهّل تكرار النتائج والتحقق منها.

## الفئات المستهدفة

- **الباحثون والطلبة:** سلاسل موثّقة توثيقًا كاملًا ومعروفة المصدر، جاهزة للنمذجة القياسية وإعادة إنتاج النتائج.
- **الصحفيون والجمهور:** أرقام رسمية سهلة الوصول، يمكن التحقق من كل رقم منها لدى الجهة التي نشرته أصلًا.
- **المصارف والشركات والمستثمرون:** متابعة المؤشرات النقدية ومؤشرات أسعار الصرف والنفط والمالية العامة بوحدات قياس ودوريات متّسقة.
- **صانعو السياسات والمحللون:** سلاسل زمنية متّسقة وطويلة الأمد لرصد الأوضاع الاقتصادية وتقييمها.

## نظرة عامة على البيانات

تُنظَّم البيانات في سلاسل زمنية منفصلة، تمثّل كل منها مؤشرًا اقتصاديًا واحدًا (مثل عرض النقد الواسع M2 شهريًا).
وتتيح المكتبة حاليًا 82 سلسلة في 9 مجالات رئيسة للاقتصاد الكلي:

| المجال | أمثلة | الجهة الناشرة الأصلية |
|---|---|---|
| النقد والمصارف | عرض النقد الواسع `money.m2`، سعر السياسة `money.policy_rate`، الاحتياطيات الرسمية `money.reserves_official`، الائتمان المقدّم للقطاع الخاص من المصارف التجارية `credit.private_total`، صافي الديون الحكومية للجهاز المصرفي `govt.system_net_claims` | البنك المركزي العراقي |
| أسعار الصرف | سعر الصرف الرسمي `fx.official`، سعر الصرف في السوق الموازية في بغداد `parallel_rate_iraq`، مبيعات البنك المركزي للعملة الأجنبية `fx.auction_total` | البنك المركزي العراقي؛ مشروع Iraq-parallel-exchange-rate |
| الأسعار والتضخم | الرقم القياسي لأسعار المستهلك `cpi_headline` و`cpi_core` | هيئة الإحصاء ونظم المعلومات الجغرافية، عن طريق البنك المركزي العراقي |
| النفط | سعر خام برنت `oil_price_brent`، سعر خام البصرة `oil_price_basrah`، إنتاج النفط الخام `crude_production_direct` | وزارة النفط وشركة تسويق النفط (سومو)، وأوبك وJODI، وإدارة معلومات الطاقة الأمريكية |
| المالية العامة | الإيرادات `fiscal.revenue_total`، النفقات `fiscal.expenditure_total`، الفائض أو العجز `fiscal.balance` | وزارة المالية، عن طريق البنك المركزي العراقي |
| الناتج المحلي الإجمالي | الناتج بالأسعار الجارية `gdp.nominal`، الناتج بالأسعار الثابتة `gdp.real`، الناتج غير النفطي `gdp.nominal_nonoil` | هيئة الإحصاء ونظم المعلومات الجغرافية |
| ميزان المدفوعات والتجارة | الحساب الجاري `bop.current_account`، الصادرات `trade.exports_total`، الواردات `trade.imports_total` | البنك المركزي العراقي |
| المصارف عبر الحدود | المطالبات `bis.lbs.claims_total`، الالتزامات `bis.lbs.liabilities_total` | بنك التسويات الدولية |
| المساعدات الإنمائية | صافي المساعدات المتلقّاة `oecd.dac.oda_total_net` | منظمة التعاون الاقتصادي والتنمية / البنك الدولي |

راجع [القائمة الكاملة للسلاسل الـ82](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md) (باللغة الإنكليزية).

## التثبيت

```bash
pip install iraqdata
```

يتطلّب `iraqdata` بايثون 3.10 أو أحدث (مُختبَر على الإصدارات من 3.10 إلى 3.13).
لتثبيت أحدث نسخة قيد التطوير مباشرة من GitHub:

```bash
pip install git+https://github.com/husseinkh90/iraqdata
```

## التوثيق

يشرح [دليل المستخدم](https://github.com/husseinkh90/iraqdata/blob/main/docs/user_guide.md) (باللغة الإنكليزية) المكتبة بالتفصيل: البحث عن السلاسل وتحميلها وإعادة تسميتها، وفهم رموز الحالة ومصدر كل قيمة، وحفظ البيانات، وتثبيت إصدارات البيانات، والعمل من دون اتصال، وتفسير رسائل الخطأ.

ويضمّ مجلد [الدروس التعليمية](https://github.com/husseinkh90/iraqdata/tree/main/tutorials) دفاتر Jupyter باللغة العربية تشرح المكتبة خطوة بخطوة، بدءًا بمقدمة عن المكتبة والبحث في البيانات باللغة العربية.

استورد المكتبة:

```python
import iraqdata as id
```

حمّل سلسلة واحدة في جدول مفهرس بالتاريخ:

```python
df = id.get_series("money.m2")
print(df.tail())
```

حمّل عدة سلاسل معًا. ولتجنّب أي تجميع ضمني، تُعاد السلاسل ذات الدوريات المختلفة (الشهرية واليومية مثلًا) في جداول منفصلة بحسب الدورية:

```python
tables = id.get_series(["money.m2", "fx.official"])
print(tables["monthly"].tail())
print(tables["daily"].tail())
```

حدّد الفترة الزمنية وأسماء الأعمدة:

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

تُنزَّل البيانات عند الطلب الأول وتُحفظ على جهازك، فتعمل الطلبات اللاحقة من دون اتصال بالإنترنت.

## رموز الحالة

لكل قيمة رمز حالة يبيّن جودتها أو وضعها. ويمكن عرض هذه الرموز بجانب القيم بتمرير `flags=True`.

الرموز المتاحة: `A` عادية، `P` أولية، `B` انقطاع في السلسلة (مثل تغيير سنة أساس الرقم القياسي)، `E` مُقدَّرة، `M` مفقودة، `U` منخفضة الموثوقية.

```python
df = id.get_series(["cpi", "m2"], flags=True)
print(df[df["cpi_flag"].isin(["B", "P"])])
```

من دون `flags=True`، يظهر التحذير `FlagWarning` عندما يحتوي الجدول على انقطاعات أو قيم أولية. لإخفائه:

```python
import warnings
warnings.filterwarnings("ignore", category=id.FlagWarning)
```

## الاستعلام عن القيم في تاريخ سابق (`as_of`)

تُنقَّح بيانات الاقتصاد الكلي باستمرار. ولضمان إمكانية إعادة إنتاج النتائج، يتيح الخيار `as_of` استرجاع القيم كما نُشرت بالضبط في تاريخ سابق محدّد.

<!-- not run: needs a release with a history folder -->
```python
then = id.get_series("cpi", wide=False, as_of="2026-10-28")
print(then[["date", "value", "realtime_start"]].tail())
```

## تثبيت إصدار البيانات

تُنشر البيانات في إصدارات مؤرّخة (مثل `data-2026-10` و`data-2026-11`). وتنزّل المكتبة افتراضيًا أحدث إصدار متاح عند أول استخدام وتحفظه، ثم تستمر في استخدام هذه النسخة المحفوظة كي لا تتغيّر نتائجك على نحو غير متوقّع، إلى أن تنفّذ صراحةً الأمر `id.refresh_latest()`.

ولضمان إعادة إنتاج النتائج تمامًا على أجهزة مختلفة أو لدى مستخدمين مختلفين، ثبّت إصدارًا محدّدًا؛ فبعد تثبيته يُستخدم ذلك الإصدار نفسه دائمًا:

```python
id.set_release("data-2026-11")    # or set the environment variable IRAQDATA_RELEASE
print(id.get_data_source())       # release data-2026-11 (pinned with set_release) from husseinkh90/iraqdata
```

للأمر `id.set_release()` الأولوية على متغيّر البيئة `IRAQDATA_RELEASE`، ويُلغي `id.set_release(None)` التثبيت. تُحفظ الملفات المنزّلة في `~/.cache/iraqdata/` (أو في `IRAQDATA_CACHE_DIR`)، في مجلد مستقل لكل إصدار. ويحذف الأمر `id.clear_cache()` الملفات التي نزّلتها المكتبة فقط، ولا يمسّ أي ملف آخر في ذلك المجلد. تُنزَّل البيانات من إصدارات المستودع `husseinkh90/iraqdata` على GitHub، ويمكن استخدام مستودع آخر بضبط المتغيّر `IRAQDATA_REPO`.

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
  version = {1.1.0},
  url     = {https://github.com/husseinkh90/iraqdata}
}
```

سيُضاف معرّف DOI بعد أرشفة الإصدار في Zenodo.

يُرجى الاستشهاد بالمكتبة وبالجهات الناشرة الأصلية للسلاسل التي تستخدمها معًا (مصادر كل سلسلة مذكورة في `datapackage.json`، وشروط استخدامها في
[`pipeline/metadata/sources.yaml`](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml)):
- البنك المركزي العراقي؛
- هيئة الإحصاء ونظم المعلومات الجغرافية (CSGIS)؛
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
(`print(id.get_data_source())`). وتصف الوثائق في
[`docs/`](https://github.com/husseinkh90/iraqdata/tree/main/docs) (باللغة الإنكليزية) السلاسل، والأرقام القياسية المربوطة للأسعار، وطريقة استخدام البيانات.

</div>
