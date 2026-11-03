"""Discover OPEC reports and extract Iraq production from supplied HTML; no network or file writes."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

from lxml import html

HOST = "publications.opec.org"
INDEX = f"https://{HOST}/momr"
SERIES = "crude_production_direct"
MONTHS = "January February March April May June July August September October November December".split()
ABBR = {m[:3]: i for i, m in enumerate(MONTHS, 1)}
PERIOD_LABEL = re.compile(r"^(" + "|".join(MONTHS) + r") (20\d{2})$")
MONTH_COLUMN = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2}|20\d{2})$")
NUMBER = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
MAX_BYTES = 5_000_000


class CollectionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CollectionError(message)


def public_url(url):
    p = urlsplit(url)
    require(p.scheme == "https" and p.hostname == HOST and p.port in (None, 443)
            and not p.username and not p.password and not p.fragment,
            f"Refusing unexpected destination: {url}")
    return url


def normalize(text):
    return " ".join(text.split())


def document(body):
    require(len(body) <= MAX_BYTES, "HTML exceeds size limit")
    try:
        text = body.decode("utf-8-sig")
        require("<html" in text.lower(), "Expected an HTML document")
        return html.fromstring(text, parser=html.HTMLParser(no_network=True))
    except (UnicodeError, html.etree.ParserError) as exc:
        raise CollectionError(f"Invalid HTML: {exc}") from exc


def metadata_period(doc):
    nodes = doc.xpath('//strong | //span[contains(concat(" ", normalize-space(@class), " "), " h3 ") '
                      'or contains(concat(" ", normalize-space(@class), " "), " h4 ")]')
    periods = set()
    for node in nodes:
        m = PERIOD_LABEL.fullmatch(normalize(node.text or ""))
        if m:
            periods.add(f"{m[2]}-{MONTHS.index(m[1]) + 1:02d}")
    require(len(periods) == 1, f"Missing or ambiguous report identity: {sorted(periods)}")
    return periods.pop()


def shift_month(period, offset):
    year, month = map(int, period.split("-"))
    absolute = year * 12 + month - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


@dataclass(frozen=True)
class Report:
    period: str
    publication_id: str
    archive_url: str | None = None
    chapter_url: str | None = None


def supply_link(doc, publication_id, archived):
    prefix = "/momr/archive/chapter/" if archived else "/momr/chapter/"
    pattern = re.compile(re.escape(prefix + publication_id) + r"/\d+/?$")
    links = set()
    for anchor in doc.xpath('//a[@href]'):
        if normalize(anchor.text_content()).lower() != "world oil supply":
            continue
        url = urljoin(INDEX, anchor.get("href"))
        if pattern.fullmatch(urlsplit(url).path):
            links.add(public_url(url))
    require(len(links) == 1, f"Expected one supply chapter for publication {publication_id}; found {len(links)}")
    return links.pop()


def discover(body, *, year=None, today=None):
    doc = document(body)
    latest = metadata_period(doc)
    today = today or datetime.now(timezone.utc).date()
    require(latest <= today.strftime("%Y-%m"), "Publication index advertises a future report")
    ids = set()
    for a in doc.xpath('//a[@href]'):
        if normalize(a.text_content()).lower() == "world oil supply":
            p = urlsplit(urljoin(INDEX, a.get("href")))
            match = re.fullmatch(r"/momr/chapter/(\d+)/\d+/?", p.path)
            if match:
                public_url(urljoin(INDEX, a.get("href")))
                ids.add(match[1])
    require(len(ids) == 1, "Latest report has missing/ambiguous publication IDs")
    latest_id = ids.pop()
    current = Report(latest, latest_id, chapter_url=supply_link(doc, latest_id, False))
    if year is None:
        return [current]
    reports = {}
    for a in doc.xpath('//a[@href]'):
        label = normalize(a.text_content())
        match = re.match(r"^(" + "|".join(MONTHS) + r") (20\d{2})(?:\s|$)", label)
        url = urljoin(INDEX, a.get("href"))
        route = re.fullmatch(r"/momr/archive/(\d+)/?", urlsplit(url).path)
        if not match or not route or int(match[2]) != year:
            continue
        period = f"{match[2]}-{MONTHS.index(match[1]) + 1:02d}"
        require(period <= latest, "Archive links to a report newer than the index")
        report = Report(period, route[1], archive_url=public_url(url))
        require(period not in reports or reports[period] == report, "Conflicting archive identities")
        reports[period] = report
    if int(latest[:4]) == year:
        require(latest not in reports or reports[latest].publication_id == latest_id, "Latest/archive identity conflict")
        reports[latest] = current
    require(bool(reports), f"No reports discovered for {year}")
    last = min(latest, f"{year}-12")
    expected = {f"{year}-{m:02d}" for m in range(1, int(last[5:]) + 1)}
    require(set(reports) == expected, f"Missing report months: {sorted(expected - set(reports))}")
    return sorted(reports.values(), key=lambda r: r.period)


def resolve_archive(report, body):
    doc = document(body)
    require(metadata_period(doc) == report.period, "Archive page belongs to a different report month")
    return Report(report.period, report.publication_id, report.archive_url,
                  supply_link(doc, report.publication_id, True))


def extract(report, body):
    doc = document(body)
    require(metadata_period(doc) == report.period, "Chapter belongs to a different report month")
    route = re.fullmatch(r"/momr/(?:archive/)?chapter/(\d+)/\d+/?", urlsplit(report.chapter_url or "").path)
    require(route is not None and route[1] == report.publication_id, "Chapter publication ID mismatch")
    captions = [n for n in doc.xpath('//h6') if normalize(n.text_content()).lower()
                == "opec crude oil production based on direct communication, tb/d"]
    require(len(captions) == 1, "Expected one direct-communication production caption with tb/d units")
    caption = captions[0]
    headings = caption.xpath('preceding::h4[1]')
    require(bool(headings) and re.fullmatch(r"Table \d+\s*-\s*\d+", normalize(headings[0].text_content())),
            "Missing production table number")
    tables = caption.xpath('following::table[1]')
    require(bool(tables), "Production table is missing")
    table = tables[0]
    # The first following table must actually belong to this caption, not the next section.
    preceding = table.xpath('preceding::h6[1]')
    require(bool(preceding) and preceding[0] is caption, "Production table moved to an ambiguous section")
    rows = []
    for tr in table.xpath('.//tr'):
        cells = tr.xpath('./th|./td')
        require(all(c.get('rowspan', '1') == '1' and c.get('colspan', '1') == '1' for c in cells),
                "Unexpected merged table cells require review")
        rows.append([normalize(c.text_content()) for c in cells])
    heads = [r for r in rows if r and r[0] == "Direct communication"]
    iraq = [r for r in rows if r and r[0] == "Iraq"]
    require(len(heads) == len(iraq) == 1, "Missing or duplicated header/Iraq row")
    headers, values = heads[0], iraq[0]
    require(len(headers) == len(values), "Iraq row has a different column count")
    observations = []
    digest = hashlib.sha256(body).hexdigest()
    for i, label in enumerate(headers):
        m = MONTH_COLUMN.fullmatch(label)
        if not m:
            continue
        yr = int(m[2]); yr = yr + 2000 if yr < 100 else yr
        period = f"{yr:04d}-{ABBR[m[1]]:02d}"
        raw = values[i]
        require(bool(NUMBER.fullmatch(raw)), f"Missing, footnoted or malformed Iraq value for {period}: {raw!r}")
        value = Decimal(raw.replace(',', ''))
        observations.append(dict(date=period, series_id=SERIES, value=str(value), unit="TB_PER_D",
                                 report_month=report.period, source_url=report.chapter_url,
                                 source_sha256=digest, table=normalize(headings[0].text_content())))
    expected = [shift_month(report.period, n) for n in (-3, -2, -1)]
    require([o['date'] for o in observations] == expected,
            f"Unexpected monthly columns: {[o['date'] for o in observations]}; expected {expected}")
    return observations
