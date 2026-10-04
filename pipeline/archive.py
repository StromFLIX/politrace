"""Reconcile the official paginated BGBl I + II archive, not just the short RSS window."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from pydantic import Field, HttpUrl, model_validator

from pipeline.documents import download, public_url
from pipeline.laws import OFFICIAL_HOSTS, ingest_entries, parse_feed
from pipeline.models import ArchiveSourcePage, Identifier, Model
from pipeline.store import digest, load_records, write_json

SEARCH_URL = "https://www.recht.bund.de/SiteGlobals/Forms/Suche/Expertensuche_Formular.html"
LAW_PATH = re.compile(r"/bgbl/([12])/(\d{4})/(\d+[a-z]?)/VO\.html")
CITATION = re.compile(r"BGBl\. (\d{4}) (II|I) Nr\. (\d+[a-z]?) vom (\d{2}\.\d{2}\.\d{4})")
INVENTORY_FILE = 'laws-bundestag-21.json'
logger = logging.getLogger(__name__)


class InventoryEntry(Model):
    id: Identifier
    title: str = Field(min_length=1)
    url: HttpUrl
    published_at: date
    citation: str

    @model_validator(mode='after')
    def identified(self):
        parsed = urlparse(str(self.url))
        match = re.fullmatch(r'/eli/bund/bgbl-([12])/(\d{4})/(\d+[a-z]?)', parsed.path)
        if parsed.scheme != 'https' or parsed.hostname not in OFFICIAL_HOSTS or not match:
            raise ValueError('Inventory law must have an official canonical ELI URL')
        part, year, number = match.groups()
        roman = 'I' if part == '1' else 'II'
        if self.id != f'bgbl-{part}-{year}-{number}' or self.citation != f'BGBl. {year} {roman} Nr. {number}':
            raise ValueError('Inventory law ID/citation does not match its URL')
        return self


class ArchiveInventory(Model):
    schema_version: str = Field(pattern=r'^1\.0$')
    since: date
    until: date
    total: int = Field(ge=0)
    entries: list[InventoryEntry]
    source_pages: list[ArchiveSourcePage] = Field(min_length=1)
    note: str

    @model_validator(mode='after')
    def complete(self):
        if (self.since > self.until or self.until > date.today() or self.total != len(self.entries)
                or len({r.id for r in self.entries}) != self.total
                or any(not self.since <= r.published_at <= self.until for r in self.entries)):
            raise ValueError('Archive inventory has duplicate, missing or out-of-window entries')
        for page in self.source_pages:
            parsed = urlparse(str(page.url))
            if parsed.scheme != 'https' or parsed.hostname not in OFFICIAL_HOSTS or parsed.path != urlparse(SEARCH_URL).path:
                raise ValueError('Inventory provenance must identify the official search pages')
        return self


def snapshot_archive(*, root: Path, since: date, until: date | None = None):
    until = until or date.today()
    entries, pages = archive_entries(since=since, until=until)
    inventory = ArchiveInventory(schema_version='1.0', since=since, until=until, total=len(entries),
        entries=entries, source_pages=pages,
        note='Complete, count-reconciled official BGBl I/II search inventory at this dated retrieval. '
             'Saved because the public search endpoint can reject GitHub runner IPs. Individual '
             'publications/PDFs are still fetched from the official host. This is not a fresh '
             'archive scan on later runs and does not establish any parliamentary vote or legal effect.')
    write_json(root / 'sources' / INVENTORY_FILE, inventory)
    return {'snapshot': INVENTORY_FILE, 'laws': inventory.total, 'until': str(until)}


class ArchivePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.next_url = None
        self.text = []
        self.in_results = False
        self.in_next = False
        self.heading = None
        self.last_heading = ""
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "section" and "searchresult" in classes:
            self.in_results = True
        if tag == "h3" and self.in_results:
            self.heading = []
        if tag == "li" and "c-nav-index__item--next" in classes:
            self.in_next = True
        if tag == "a":
            href = attrs.get("href", "")
            if "forward" in classes or self.in_next:
                if self.next_url and self.next_url != href:
                    raise ValueError("Conflicting archive pagination links")
                self.next_url = href
            if self.in_results and LAW_PATH.fullmatch(urlparse(href).path):
                self.link = {"url": href, "text": [], "heading": self.last_heading}

    def handle_data(self, value):
        self.text.append(value)
        if self.heading is not None:
            self.heading.append(value)
        if self.link is not None:
            self.link["text"].append(value)

    def handle_endtag(self, tag):
        if tag == "li":
            self.in_next = False
        if tag == "section":
            self.in_results = False
        if tag == "h3" and self.heading is not None:
            self.last_heading = " ".join("".join(self.heading).split())
            self.heading = None
        if tag == "a" and self.link is not None:
            link, self.link = self.link, None
            parsed = urlparse(link["url"])
            match = LAW_PATH.fullmatch(parsed.path)
            citation = CITATION.fullmatch(link["heading"])
            if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS or not match or not citation:
                raise ValueError("Invalid official archive law or citation")
            part, year, number = match.groups()
            cyear, roman, cnumber, published = citation.groups()
            if (year, number, part) != (cyear, cnumber, "1" if roman == "I" else "2"):
                raise ValueError("Archive citation does not identify its linked law")
            title = " ".join("".join(link["text"]).split())
            if not title:
                raise ValueError("Empty archive law title")
            self.results.append({
                "id": f"bgbl-{part}-{year}-{number}", "title": title,
                "url": f"https://www.recht.bund.de/eli/bund/bgbl-{part}/{year}/{number}",
                "published_at": datetime.strptime(published, "%d.%m.%Y").date(),
                "citation": f"BGBl. {year} {roman} Nr. {number}",
            })

    @property
    def total(self):
        match = re.search(r"Suchergebnisse:\s*([\d.]+)", " ".join(self.text))
        if not match:
            raise ValueError("Archive result count missing; source markup may have changed")
        return int(match[1].replace(".", ""))


def archive_entries(*, since: date, until: date, max_pages=50):
    if not date(2023, 1, 1) <= since <= until <= date.today():
        raise ValueError("Archive requires 2023-01-01 <= since <= until <= today")
    params = {"lastChangeVdAfter": since.isoformat(), "lastChangeVdBefore": until.isoformat(),
              "cl2Metadaten_cl2Categories_Typ": "gesetz", "resultsPerPage": "100",
              "sortOrder": "dateOfIssue_dt asc"}
    url = SEARCH_URL + "?" + urlencode(params)
    records, seen, pages, total = [], set(), [], None
    for _ in range(max_pages):
        if url in seen:
            raise ValueError("Archive pagination loop")
        seen.add(url)
        public_url(url, OFFICIAL_HOSTS)
        if urlparse(url).path != urlparse(SEARCH_URL).path:
            raise ValueError("Archive pagination left the official search endpoint")
        content = download(url, allowed_hosts=OFFICIAL_HOSTS, limit=8 * 1024 * 1024)
        page = ArchivePage()
        page.feed(content.decode("utf-8"))
        if total is not None and page.total != total:
            raise ValueError("Archive changed during pagination; retry for a consistent inventory")
        total = page.total
        pages.append({"url": url, "sha256": digest(content)})
        records.extend(page.results)
        if len({r["id"] for r in records}) != len(records):
            raise ValueError("Duplicate law in paginated archive")
        if any(not since <= r["published_at"] <= until for r in page.results):
            raise ValueError("Archive did not respect the requested publication window")
        if not page.next_url:
            if len(records) != total:
                raise ValueError(f"Incomplete archive: parsed {len(records)} of {total} advertised laws")
            return records, pages
        if not page.results:
            raise ValueError("Empty intermediate archive page")
        url = urljoin(url, page.next_url).split("#")[0]
    raise ValueError("Archive page limit reached; refusing a falsely complete backfill")


def ingest_archive(*, root: Path, since: date, until: date | None = None, limit=1000,
                   snapshot_fallback=False):
    until = until or date.today()
    requested_until, mode, recent = until, 'archive', []
    try:
        entries, pages = archive_entries(since=since, until=until)
    except httpx.HTTPStatusError as error:
        if not snapshot_fallback or error.response.status_code != 403:
            raise
        inventory = ArchiveInventory.model_validate_json((root / 'sources' / INVENTORY_FILE).read_text())
        if not inventory.since <= since <= inventory.until:
            raise ValueError('Saved archive inventory does not cover the requested start; refresh it explicitly') from None
        until = min(requested_until, inventory.until)
        entries = [{**r.model_dump(), 'url': str(r.url)} for r in inventory.entries
                   if since <= r.published_at <= until]
        pages = [p.model_dump(mode='json') for p in inventory.source_pages]
        mode = 'snapshot-and-rss'
        logger.warning('Official search returned 403; using the checked archive inventory through %s '
                       'plus both public RSS feeds. This is not a fresh complete archive scan.', until)
        for part in (1, 2):
            url = f'https://www.recht.bund.de/rss/feeds/rss_bgbl-{part}.xml'
            feed = parse_feed(download(url, allowed_hosts=OFFICIAL_HOSTS, limit=8 * 1024 * 1024))
            recent.extend(r for r in feed if since <= r['published_at'] <= requested_until)
    combined = {r['id']: r for r in entries}
    for row in recent:
        if row['id'] in combined and combined[row['id']]['published_at'] != row['published_at']:
            raise ValueError('RSS and archive disagree about a publication date')
        combined.setdefault(row['id'], row)
    result = ingest_entries(root=root, entries=list(combined.values()), limit=limit, since=since)
    existing = {law.id for law in load_records(root, "live", "laws")}
    expected = sorted(r["id"] for r in entries)
    pending = [identifier for identifier in expected if identifier not in existing]
    coverage_path = root / "live" / "coverage" / f"laws-since-{since.isoformat()}.json"
    # A source check with no changes is a real no-op, not a daily timestamp-only PR.
    previous = json.loads(coverage_path.read_text()) if coverage_path.exists() else {}
    if (result["new_laws"] or previous.get("expected_ids") != expected
            or previous.get("pending_ids") != pending):
        write_json(coverage_path, {
            "schema_version": "1.0", "dataset": "live", "period_start": str(since),
            "as_of": str(until), "date_basis": "promulgation", "parts": ["I", "II"],
            "inventory_mode": mode,
            "kind": "Gesetz", "official_count": len(expected), "imported_count": len(expected) - len(pending),
            "complete": not pending, "expected_ids": expected, "pending_ids": pending,
            "source_pages": pages,
            "note": "Official archive inventory by publication date. Not a claim about the Bundestag vote date, "
                    "entry into force, consolidated law, voting behaviour or completeness of AI impact matching.",
        })
    result.update({"archive_count": len(entries), "remaining_in_archive": len(pending),
                   "coverage_complete": not pending, "since": str(since), "until": str(until),
                   "source_mode": mode, "requested_until": str(requested_until),
                   "rss_laws_beyond_inventory": sum(r['id'] not in expected for r in recent),
                   "coverage_note": 'Completeness refers only to the dated archive inventory. '
                                    'RSS updates do not extend its verified full-archive coverage date.'})
    return result
