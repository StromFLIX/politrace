"""Reconcile the official paginated BGBl I + II archive, not just the short RSS window."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from pipeline.documents import download, public_url
from pipeline.laws import OFFICIAL_HOSTS, ingest_entries
from pipeline.store import digest, load_records, write_json

SEARCH_URL = "https://www.recht.bund.de/SiteGlobals/Forms/Suche/Expertensuche_Formular.html"
LAW_PATH = re.compile(r"/bgbl/([12])/(\d{4})/(\d+[a-z]?)/VO\.html")
CITATION = re.compile(r"BGBl\. (\d{4}) (II|I) Nr\. (\d+[a-z]?) vom (\d{2}\.\d{2}\.\d{4})")


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


def ingest_archive(*, root: Path, since: date, until: date | None = None, limit=1000):
    until = until or date.today()
    entries, pages = archive_entries(since=since, until=until)
    result = ingest_entries(root=root, entries=entries, limit=limit, since=since)
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
            "kind": "Gesetz", "official_count": len(expected), "imported_count": len(expected) - len(pending),
            "complete": not pending, "expected_ids": expected, "pending_ids": pending,
            "source_pages": pages,
            "note": "Official archive inventory by publication date. Not a claim about the Bundestag vote date, "
                    "entry into force, consolidated law, voting behaviour or completeness of AI impact matching.",
        })
    result.update({"archive_count": len(entries), "remaining_in_archive": len(pending),
                   "coverage_complete": not pending, "since": str(since), "until": str(until)})
    return result
