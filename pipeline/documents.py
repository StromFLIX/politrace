from __future__ import annotations

import ipaddress
import re
import socket
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from pipeline.models import Leaf, Span
from pipeline.store import stable_id

MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_PDF_PAGES = 400


class NeedsOCR(ValueError):
    """No complete, trustworthy text layer; metadata may be ingested, never matching evidence."""


def public_url(url: str, allowed_hosts: set[str] | None = None) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Sources must be public HTTPS URLs without credentials")
    if parsed.port not in (None, 443):
        raise ValueError("Non-standard source ports are not permitted")
    if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
        raise ValueError("Source redirected outside the official source host allowlist")
    for address in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("Private, loopback and link-local source addresses are not permitted")


def download(url: str, *, allowed_hosts: set[str] | None = None, limit=MAX_DOWNLOAD_BYTES) -> bytes:
    # Never attach the OpenRouter token to source requests or follow unchecked redirects.
    with httpx.Client(timeout=httpx.Timeout(60, connect=15), headers={"User-Agent": "Politrace/0.1"}) as client:
        for _ in range(5):
            public_url(url, allowed_hosts)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    target = urljoin(url, response.headers["location"])
                    # recht.bund.de's ELI resolver emits an HTTP Location even though HTTPS exists.
                    # Upgrade same-host redirects locally; NEVER send an HTTP request.
                    if urlparse(target).scheme == "http" and urlparse(target).netloc == urlparse(url).netloc:
                        target = "https:" + target[5:]
                    url = target
                    continue
                response.raise_for_status()
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > limit:
                        raise ValueError("Source exceeds the download size limit")
                return bytes(result)
    raise ValueError("Too many source redirects")


def extract_pdf(pdf: bytes, *, textless_pages: set[int] | None = None) -> list[str]:
    import pymupdf
    import pymupdf4llm

    if len(pdf) > MAX_DOWNLOAD_BYTES or not pdf.startswith(b"%PDF-"):
        raise ValueError("Expected a PDF smaller than 40 MiB")
    with tempfile.TemporaryDirectory(prefix="politrace-pdf-") as temporary:
        path = Path(temporary) / "source.pdf"
        path.write_bytes(pdf)
        with pymupdf.open(path) as document:
            if document.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            if not 1 <= document.page_count <= MAX_PDF_PAGES:
                raise ValueError("PDF page count outside the supported range (1–400)")
            if any(p < 1 or p > document.page_count for p in (textless_pages or set())):
                raise ValueError("Textless-page declaration is outside the PDF")
            native_pages = [page.get_text(sort=True).strip() for page in document]
        chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True, show_progress=False)
        # Some graphic chapter covers have a valid text layer but the layout converter drops it.
        # Preserve that source text instead of treating these pages as blank or fabricating OCR.
        pages = [chunk["text"].strip() or native for chunk, native in zip(chunks, native_pages, strict=True)]
        # An explicitly inspected, SHA-pinned artwork/blank page is kept as a Markdown marker.
        # Unknown textless pages still stop ingestion: they may contain scanned policy text.
        unknown = {i for i, page in enumerate(pages, 1) if not page.strip()} - (textless_pages or set())
        if unknown:
            raise NeedsOCR(f"PDF has unverified textless pages {sorted(unknown)}; inspect or supply reviewed OCR")
        if not any(page.strip() for page in pages):
            raise NeedsOCR("PDF has no extractable text")
        return pages


def pages_to_markdown(pages: list[str], prefix: str) -> tuple[str, list[Leaf]]:
    lines: list[str] = []
    leaves = []
    seen: Counter = Counter()
    for page, text in enumerate(pages, 1):
        lines.extend([f"<!-- page:{page} -->", ""])
        # Empty pages remain visible in the exported transcription.
        if not text.strip():
            lines.extend(["<!-- no extractable text on this page -->", ""])
            continue
        page_lines = text.strip().splitlines()
        offset = len(lines)
        lines.extend(page_lines + [""])
        index = 0
        while index < len(page_lines):
            if not page_lines[index].strip():
                index += 1
                continue
            start = index
            while index < len(page_lines) and page_lines[index].strip():
                index += 1
            block = "\n".join(page_lines[start:index]).strip()
            # Bounded leaves retain verbatim text and the original encompassing line range.
            parts = []
            while len(block) > 4500:
                split = block.rfind(" ", 1000, 4500)
                if split < 0:
                    split = 4500
                parts.append(block[:split])
                block = block[split:].strip()
            if block:
                parts.append(block)
            for part in parts:
                # Match stable_id's whitespace/case normalization when counting occurrences.
                # Otherwise tables repeating 'Text' and 'TEXT' can generate the same passage ID.
                occurrence = (page, " ".join(part.split()).casefold())
                seen[occurrence] += 1
                leaf_id = stable_id(f"{prefix}-p", f"{page}:{seen[occurrence]}:{part}")
                leaves.append(Leaf(id=leaf_id, text=part, reference=Span(
                    page=page, line_start=offset + start + 1, line_end=offset + index, quote=part,
                )))
    return "\n".join(lines).rstrip() + "\n", leaves


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
