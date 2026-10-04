from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from defusedxml import ElementTree

from pipeline.documents import NeedsOCR, download, extract_pdf, pages_to_markdown
from pipeline.models import Law, MatchAudit, Source
from pipeline.store import digest, load_records, save_record

FEED_URL = "https://www.recht.bund.de/rss/feeds/rss_bgbl-1.xml"
OFFICIAL_HOSTS = {"www.recht.bund.de", "recht.bund.de"}
META = "{http://recht.bund.de/rss/meta}"


def feed_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return parsedate_to_datetime(value).date()


def parse_feed(content: bytes):
    root = ElementTree.fromstring(content)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected the official RSS 2.0 feed; refusing an empty successful import")
    records = []
    for item in root.findall("./channel/item"):
        # BGBl also contains ordinances and corrections. Do not call these parliamentary laws.
        if item.findtext(META + "typ", "").strip() != "Gesetz":
            continue
        title = item.findtext("title", "").strip()
        url = item.findtext("link", "").strip()
        parsed = urlparse(url)
        match = re.fullmatch(r"/eli/bund/bgbl-1/(\d{4})/(\d+[a-z]?)/?", parsed.path)
        if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS or not match or not title:
            raise ValueError("Invalid or non-official law entry in feed")
        year, number = match.groups()
        records.append({
            "id": f"bgbl-1-{year}-{number}", "title": title, "url": url,
            "published_at": feed_date(item.findtext("pubDate", "")),
            "citation": item.findtext(META + "fundstelle", f"BGBl. {year} I Nr. {number}").strip(),
        })
    if not root.findall("./channel/item"):
        raise ValueError("Official feed is unexpectedly empty")
    return records


class PdfLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if "regelungstext.pdf" in href:
                self.links.append(href)


def pdf_link(html: bytes, url: str):
    parser = PdfLinks()
    parser.feed(html.decode("utf-8"))
    year, number = urlparse(url).path.rstrip("/").split("/")[-2:]
    expected = f"/bgbl/1/{year}/{number}/regelungstext.pdf"
    for href in parser.links:
        absolute = urljoin(url, href)
        parsed = urlparse(absolute)
        if parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS and parsed.path == expected:
            return absolute
    raise ValueError("No canonical law PDF link found; official source markup may have changed")


def ingest_laws(*, root: Path, limit=10, since: date | None = None, feed_url=FEED_URL):
    if not 1 <= limit <= 100:
        raise ValueError("Law limit must be 1–100")
    records = parse_feed(download(feed_url, allowed_hosts=OFFICIAL_HOSTS, limit=8 * 1024 * 1024))
    existing = {law.id for law in load_records(root, "live", "laws")}
    pending = sorted(
        (r for r in records if r["id"] not in existing and r["published_at"] <= date.today()
         and (since is None or r["published_at"] >= since)),
        key=lambda r: (r["published_at"], r["id"]), reverse=True,
    )
    created = []
    for entry in pending[:limit]:
        html = download(entry["url"], allowed_hosts=OFFICIAL_HOSTS, limit=4 * 1024 * 1024)
        pdf_url = pdf_link(html, entry["url"])
        pdf = download(pdf_url, allowed_hosts=OFFICIAL_HOSTS)
        try:
            pages = extract_pdf(pdf)
        except NeedsOCR:
            pages = []
        complete = bool(pages)
        markdown, passages = pages_to_markdown(pages, entry["id"])
        relative_md = f"live/laws/{entry['id']}.md" if complete else None
        law = Law(
            id=entry["id"], dataset="live", title=entry["title"], official_title=entry["title"],
            published_at=entry["published_at"], citation=entry["citation"],
            source=Source(url=entry["url"], title=entry["title"], publisher="Bundesgesetzblatt / recht.bund.de",
                          retrieved_at=datetime.now().date(), sha256=digest(pdf),
                          license_note="Amtlicher Gesetzestext, § 5 Abs. 1 UrhG; Herkunft bitte beibehalten."),
            pdf_url=pdf_url, markdown_path=relative_md,
            text_status="available" if complete else "needs_ocr", passages=passages if complete else [],
            summary=f"Verkündet im {entry['citation']}. Noch keine redaktionelle Zusammenfassung. "
                    "Die Verkündung belegt weder ein einheitliches Inkrafttreten noch das Abstimmungsverhalten.",
            matching=MatchAudit(status="pending" if complete else "needs_ocr"),
        )
        if relative_md:
            (root / relative_md).parent.mkdir(parents=True, exist_ok=True)
            (root / relative_md).write_text(markdown, encoding="utf-8")
        save_record(root, "laws", law)
        created.append(law.id)
    return {"new_laws": created, "remaining_in_feed": max(0, len(pending) - limit),
            "notify": bool(created), "reason": "New official publications" if created else "No new laws in feed"}
