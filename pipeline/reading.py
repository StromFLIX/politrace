"""Page-complete, versioned reading editions. Never overwrite an existing evidence span.

Mistral receives only public source PDFs. Credentials, responses containing images and
provider error bodies are never persisted. Per-page caches survive partial failures.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Literal

import httpx
from pydantic import Field, HttpUrl

from pipeline.documents import MAX_DOWNLOAD_BYTES, MAX_PDF_PAGES, download
from pipeline.models import Model
from pipeline.store import digest, json_text, load_records, write_json

logger = logging.getLogger(__name__)
VERSION = 'mistral-reading-v1'
TABLE_LINK = re.compile(r'!?\[[^\]\n]*\]\((tbl-\d+\.(?:md|html))\)')


class DocumentMirror(Model):
    document_id: str
    source_url: HttpUrl
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    mirror_urls: list[HttpUrl] = Field(min_length=1, max_length=5)
    verified_at: date
    note: str


class DocumentMirrors(Model):
    schema_version: Literal['1.0'] = '1.0'
    documents: list[DocumentMirror]


class ReadingCorrection(Model):
    before: str
    after: str
    source_evidence: str


class ReadingTable(Model):
    id: str = Field(pattern=r'^tbl-\d+\.md$')
    content: str = Field(min_length=1)
    format: Literal['markdown'] = 'markdown'


class ReadingRevision(Model):
    changed_at: date
    previous_markdown_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reason: str


class ReadingPage(Model):
    number: int = Field(ge=1)
    markdown: str
    header: str = ''
    footer: str = ''
    warnings: list[str] = Field(default_factory=list)
    native_word_recall: float | None = None
    corrections: list[ReadingCorrection] = Field(default_factory=list)
    ocr_markdown_sha256: str | None = None
    tables: list[ReadingTable] = Field(default_factory=list)


class ReadingEdition(Model):
    schema_version: Literal['1.0'] = '1.0'
    document_id: str
    collection: Literal['programs', 'laws']
    source_pdf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_url: str
    retrieved_from: str | None = None
    processor: str = VERSION
    models: list[str]
    page_count: int = Field(ge=1)
    pages: list[ReadingPage]
    markdown_path: str
    markdown_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    created_at: date
    review_status: Literal['proposed'] = 'proposed'
    revisions: list[ReadingRevision] = Field(default_factory=list)
    evidence_unchanged: Literal[True] = True
    note: str = ('Separate OCR reading edition; not a silently corrected evidence source. '
                 'Existing criterion/law quotations refer to the preserved original extraction. '
                 'Headers and footers remain available. No human OCR approval is implied.')


def native_recall(native: str, text: str) -> float | None:
    def words(value):
        value = re.sub(r'(\w)[\-\u00ad]\s*\n\s*(\w)', r'\1\2', value)
        return {word.casefold() for word in re.findall(r'[^\W\d_]{4,}', value)}
    expected, actual = words(native), words(text)
    return round(len(expected & actual) / len(expected), 3) if len(expected) >= 8 else None


def clean_markdown(text: str) -> str:
    # Never infer missing letters, numbers or conditions. Source-supplied HTML is
    # escaped by the renderer. Only normalise page layout and invisible control glyphs.
    text = re.sub(r'!\[([^\]]*)\]\([^\n)]*\)', r'\1', text)
    text = re.sub(r'^\s*img-\d+\.(?:jpeg|jpg|png)\s*$', '', text, flags=re.M)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.replace('\u00ad\n', '').replace('\u00ad', '')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def expand_tables(text: str, tables: list[ReadingTable]) -> str:
    """Mistral table_format returns sidecars, not inline text. Never fetch their links."""
    by_id = {table.id: table for table in tables}
    if len(by_id) != len(tables):
        raise ValueError('Duplicate OCR table sidecars')
    used = set()
    def replace(match):
        identifier = match[1]
        if identifier not in by_id:
            raise ValueError('OCR page references a missing table sidecar')
        used.add(identifier)
        return '\n\n' + by_id[identifier].content + '\n\n'
    text = TABLE_LINK.sub(replace, text)
    if TABLE_LINK.search(text):
        raise ValueError('Unresolved nested OCR table sidecar')
    if any(table.id not in used and table.content not in text for table in tables):
        raise ValueError('OCR returned an unplaced table; do not silently drop it')
    return clean_markdown(text)


class OCRFailure(RuntimeError):
    def __init__(self, code: int):
        self.status_code = code
        self.retryable = code in (408, 429, 500, 502, 503, 504, 529)
        super().__init__(f'Mistral OCR HTTP {code}; response body omitted')


class MistralOCR:
    def __init__(self, cache: Path, *, client=None, max_pages=5000):
        self.cache = cache
        self.key = os.environ.get('MISTRAL_API_KEY', '')
        self.client = client or httpx.Client(timeout=httpx.Timeout(240, connect=20))
        self.lock = Lock()
        self.rate_lock = Lock()
        self.next_request_at = 0.0
        self.max_pages = max_pages
        self.ledger = cache / 'usage.json'
        import fcntl
        cache.mkdir(parents=True, exist_ok=True)
        self._file_lock = (cache / 'usage.lock').open('a')
        fcntl.flock(self._file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.usage = json.loads(self.ledger.read_text()) if self.ledger.exists() else {
            'calls': 0, 'requested_pages': 0, 'reported_pages': 0, 'unknown_charge_pages': 0,
            'reported_cost_usd': None,
            'note': 'OCR API reports pages, not USD. Charges must be checked in Mistral billing.',
        }
        # Recover an interrupted call conservatively; it may have been billed.
        self.usage['unknown_charge_pages'] += self.usage.pop('in_flight_pages', 0)
        self.usage['in_flight_pages'] = 0
        write_json(self.ledger, self.usage)

    def summary(self):
        with self.lock:
            return dict(self.usage)

    def pages(self, pdf: bytes, indexes: list[int], sha: str, native: list[str]):
        import pymupdf

        paths = {i: self.cache / VERSION / sha / f'{i + 1}.json' for i in indexes}
        found = {}
        for i, path in paths.items():
            if path.exists():
                saved = json.loads(path.read_text())
                page = ReadingPage.model_validate(saved['page'])
                # Older cache entries discarded separate table payloads. They are not
                # valid hits: re-request just those pages and retain the paid ledger.
                if TABLE_LINK.search(page.markdown) and not page.tables:
                    continue
                page.markdown = expand_tables(page.markdown, page.tables)
                if re.search(r'(\w{3,})-\s*\n+\s*\1', page.markdown, re.I):
                    warning = 'Possible repeated hyphenated word; compare with the original PDF.'
                    if warning not in page.warnings:
                        page.warnings.append(warning)
                if page.number != i + 1 or saved['source_sha256'] != sha:
                    raise ValueError('Invalid OCR page checkpoint')
                found[i] = (page, saved['model'])
        pending = [i for i in indexes if i not in found]
        if not pending:
            return [found[i] for i in indexes]
        if not self.key:
            raise RuntimeError('MISTRAL_API_KEY is required for OCR, never for serving the site')
        # Upload only the current pages, not a 40MB full PDF for every request. Original
        # page numbers are restored explicitly below; requests and caches bind to PDF SHA.
        with pymupdf.open(stream=pdf, filetype='pdf') as original, pymupdf.open() as selected:
            for i in pending:
                selected.insert_pdf(original, from_page=i, to_page=i)
            subset = selected.tobytes(garbage=4, deflate=True)
        payload = {'model': 'mistral-ocr-latest', 'document': {'type': 'document_url',
                   'document_url': 'data:application/pdf;base64,' + base64.b64encode(subset).decode()},
                   'include_image_base64': False, 'table_format': 'markdown',
                   'extract_header': True, 'extract_footer': True}
        for attempt in range(6):
            # One shared page-rate gate prevents parallel workers forming a retry storm.
            # 120 pages/minute is deliberately conservative; latency can overlap safely.
            with self.rate_lock:
                delay = max(0, self.next_request_at - time.monotonic())
                self.next_request_at = max(time.monotonic(), self.next_request_at) + max(2, len(pending) / 2)
            if delay:
                time.sleep(delay)
            with self.lock:
                if self.usage['requested_pages'] + len(pending) > self.max_pages:
                    raise RuntimeError('OCR cumulative page limit reached; retained pages are reusable')
                self.usage['calls'] += 1
                self.usage['requested_pages'] += len(pending)
                self.usage['in_flight_pages'] += len(pending)
                write_json(self.ledger, self.usage)
            response, body, code = None, None, 504
            try:
                response = self.client.post('https://api.mistral.ai/v1/ocr', json=payload,
                    headers={'Authorization': 'Bearer ' + self.key})
                code = response.status_code
                if not response.is_error:
                    body = response.json()
            except (httpx.TransportError, ValueError):
                code = 504
            finally:
                with self.lock:
                    self.usage['in_flight_pages'] -= len(pending)
                    used = body.get('usage_info', {}).get('pages_processed') if isinstance(body, dict) else None
                    if type(used) is int and used >= 0:
                        self.usage['reported_pages'] += used
                    else:
                        self.usage['unknown_charge_pages'] += len(pending)
                    write_json(self.ledger, self.usage)
            if code == 200 and isinstance(body, dict):
                pages = body.get('pages', [])
                if (not isinstance(pages, list) or len(pages) != len(pending)
                        or sorted(p.get('index', -1) for p in pages) != list(range(len(pending)))):
                    raise ValueError('OCR response must account for every requested page exactly once')
                model = body.get('model')
                if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9._/-]{1,100}', model):
                    raise ValueError('Missing/invalid OCR model provenance')
                for p in pages:
                    i = pending[p['index']]
                    # Providers may add confidence metadata. Persist the explicit text
                    # contract only, not opaque extras or embedded image material.
                    tables = [ReadingTable.model_validate({k: t[k] for k in ('id', 'content', 'format') if k in t})
                              for t in p.get('tables', [])]
                    text = expand_tables(p['markdown'], tables)
                    header, footer = p.get('header') or '', p.get('footer') or ''
                    recall = native_recall(native[i], '\n'.join([header, text, footer]))
                    warnings = []
                    if not text and len(native[i].strip()) > 100 and not (header or footer):
                        raise ValueError(f'OCR silently omitted text on PDF page {i + 1}')
                    if recall is not None and recall < 0.8:
                        warnings.append('Native/OCR word coverage differs; compare this page with the PDF.')
                    if '\ufffd' in text:
                        warnings.append('Replacement characters remain; source review required.')
                    if re.search(r'(\w{3,})-\s*\n+\s*\1', text, re.I):
                        warnings.append('Possible repeated hyphenated word; compare with the original PDF.')
                    page = ReadingPage(number=i + 1, markdown=text, header=header, footer=footer,
                                       warnings=warnings, native_word_recall=recall, tables=tables)
                    write_json(paths[i], {'source_sha256': sha, 'model': model, 'page': page.model_dump()})
                    found[i] = (page, model)
                return [found[i] for i in indexes]
            error = OCRFailure(code)
            if not error.retryable or attempt == 5:
                raise error
            delay = min(120, 15 * 2 ** attempt)
            if response is not None:
                try:
                    delay = min(120, max(delay, float(response.headers.get('retry-after', '0'))))
                except ValueError:
                    pass
            with self.rate_lock:
                self.next_request_at = max(self.next_request_at, time.monotonic() + delay)
        raise AssertionError('Unreachable OCR retry state')


def download_candidates(root: Path, record) -> list[str]:
    original = str(record.pdf_url)
    registry = root / 'sources/document-mirrors.json'
    if not registry.exists():
        return [original]
    mirrors = DocumentMirrors.model_validate_json(registry.read_text())
    entries = [entry for entry in mirrors.documents if entry.document_id == record.id]
    if len(entries) > 1:
        raise ValueError('Duplicate document mirror entry')
    if not entries:
        return [original]
    entry = entries[0]
    if str(entry.source_url) != original or entry.source_sha256 != record.source.sha256:
        raise ValueError('Mirror registry does not match the pinned original source')
    # These locations were independently checksum-verified. Prefer them during a known
    # publisher outage, then fall back to the publisher; every download is checked again.
    return list(dict.fromkeys([*(str(url) for url in entry.mirror_urls), original]))


def source_pdf(root: Path, record, cache: Path):
    candidates = download_candidates(root, record)
    pdf_path = cache / 'pdfs' / f'{record.source.sha256}.pdf'
    provenance = pdf_path.with_suffix('.json')
    if pdf_path.exists():
        pdf = pdf_path.read_bytes()
        if digest(pdf) != record.source.sha256 or len(pdf) > MAX_DOWNLOAD_BYTES:
            raise ValueError('Cached PDF checksum/size check failed')
        retrieved_from = None
        if provenance.exists():
            metadata = json.loads(provenance.read_text())
            retrieved_from = metadata['retrieved_from']
            if metadata['source_sha256'] != record.source.sha256 or retrieved_from not in candidates:
                raise ValueError('Cached PDF download provenance does not match the source registry')
        return pdf, retrieved_from
    last_error = None
    for url in candidates:
        try:
            pdf = download(url)
            if digest(pdf) != record.source.sha256 or len(pdf) > MAX_DOWNLOAD_BYTES:
                raise ValueError('Downloaded PDF does not match the pinned original SHA-256')
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
            logger.warning('PDF download rejected for %s (%s); trying remaining verified locations',
                           record.id, type(error).__name__)
            continue
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(provenance, {'source_sha256': record.source.sha256, 'retrieved_from': url,
                                'source_url': str(record.pdf_url), 'retrieved_at': str(date.today())})
        temporary = pdf_path.with_suffix('.pdf.tmp')
        temporary.write_bytes(pdf)
        temporary.replace(pdf_path)
        return pdf, url
    raise last_error or ValueError('No usable source PDF location')


def create_reading(root: Path, record, collection: str, ocr: MistralOCR):
    import pymupdf

    path = root / 'live/readings' / f'{record.id}.json'
    current, repair_pages = None, set()
    if path.exists():
        current = ReadingEdition.model_validate_json(path.read_text())
        if current.source_pdf_sha256 != record.source.sha256:
            raise ValueError('Source PDF changed; create an explicit new reading edition, never overwrite')
        repair_pages = {p.number for p in current.pages if TABLE_LINK.search(p.markdown)}
        if not repair_pages:
            validate_reading(current, root, record)
            return {'document_id': record.id, 'status': 'unchanged', 'pages': current.page_count}
        # Explicit parser migration, not an unnoticed replacement of the evidence source.
        validate_reading(current, root, record, allow_legacy_tables=True)
        logger.info('OCR %s: recovering missing table sidecars on %s pages', record.id, len(repair_pages))
    if not record.pdf_url or not record.source.sha256:
        raise ValueError('Reading edition requires an attributed, SHA-pinned original PDF')
    pdf, retrieved_from = source_pdf(root, record, ocr.cache)
    with pymupdf.open(stream=pdf, filetype='pdf') as document:
        if document.is_encrypted or not 1 <= len(document) <= MAX_PDF_PAGES:
            raise ValueError('Invalid/encrypted source PDF')
        native = [p.get_text(sort=True) for p in document]
    pages = {p.number: p for p in current.pages if p.number not in repair_pages} if current else {}
    models = set(current.models) if current else set()
    indexes = [i for i in range(len(native)) if i + 1 not in pages]
    for start in range(0, len(indexes), 16):
        for page, model in ocr.pages(pdf, indexes[start:start + 16], record.source.sha256, native):
            pages[page.number] = page
            models.add(model)
        logger.info('OCR %s: %s/%s pages checkpointed', record.id, len(pages), len(native))
    pages = [pages[i + 1] for i in range(len(native))]
    markdown = '\n\n'.join(f'<!-- page:{p.number} -->\n\n{p.markdown}' for p in pages).rstrip() + '\n'
    relative = f'live/readings/{record.id}.md'
    edition = ReadingEdition(document_id=record.id, collection=collection,
        source_pdf_sha256=record.source.sha256, source_url=str(record.pdf_url),
        retrieved_from=retrieved_from, models=sorted(models), page_count=len(native), pages=pages, markdown_path=relative,
        markdown_sha256=digest(markdown), created_at=current.created_at if current else date.today(),
        revisions=[*current.revisions, ReadingRevision(changed_at=date.today(),
            previous_markdown_sha256=current.markdown_sha256,
            reason=f'Recovered omitted OCR table sidecars on {len(repair_pages)} pages; '
                   'all other pages and original citation evidence preserved.')] if current else [])
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_text(markdown)
    validate_reading(edition, root, record)
    write_json(path, edition)
    logger.info('OCR %s: completed %s pages, %s page warnings', record.id, len(pages),
                sum(bool(p.warnings) for p in pages))
    return {'document_id': record.id, 'status': 'completed', 'pages': len(pages)}


def validate_reading(edition, root, record, *, allow_legacy_tables=False):
    from pipeline.store import safe_markdown

    if edition.document_id != record.id or edition.source_pdf_sha256 != record.source.sha256:
        raise ValueError('Reading edition does not match its source')
    if edition.source_url != str(record.pdf_url):
        raise ValueError('Reading edition source URL differs from its attributed PDF')
    if edition.retrieved_from and edition.retrieved_from not in download_candidates(root, record):
        raise ValueError('Reading edition download location is not a registered source/mirror')
    for page in edition.pages:
        if not allow_legacy_tables and TABLE_LINK.search(page.markdown):
            raise ValueError('Reading edition contains an unresolved OCR table')
        if not allow_legacy_tables:
            expand_tables(page.markdown, page.tables)
    if [p.number for p in edition.pages] != list(range(1, edition.page_count + 1)):
        raise ValueError('Reading edition must retain every PDF page in order')
    text = safe_markdown(root, 'live', edition.markdown_path).read_text()
    expected = '\n\n'.join(f'<!-- page:{p.number} -->\n\n{p.markdown}' for p in edition.pages).rstrip() + '\n'
    if text != expected or digest(text) != edition.markdown_sha256:
        raise ValueError('Reading Markdown differs from the versioned page records')


def run_readings(root, cache, *, workers=4, ids=None, collections=('programs', 'laws'), max_pages=10000):
    if not 1 <= workers <= 8:
        raise ValueError('OCR workers must be 1–8')
    public_progress = root / 'live/processing/readings.json'
    if not (cache / 'usage.json').exists() and public_progress.exists():
        # Local acceptance/backfill charges seed CI's ledger; publication never resets usage.
        write_json(cache / 'usage.json', json.loads(public_progress.read_text())['ocr_usage'])
    ocr = MistralOCR(cache, max_pages=max_pages)
    tasks = [(kind, r) for kind in collections for r in load_records(root, 'live', kind)
             if ids is None or r.id in ids]
    progress_path = cache / 'progress.json'
    result = {'total_documents': len(tasks), 'completed': [], 'failed': [], 'ocr_usage': ocr.summary()}
    def work(task):
        kind, record = task
        try:
            return create_reading(root, record, kind, ocr)
        except Exception as error:
            # No URLs with credentials, provider bodies or model output in error reports.
            return {'document_id': record.id, 'status': 'failed', 'error_type': type(error).__name__,
                    'http_status': getattr(error, 'status_code',
                                           error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        waiting, iterator = set(), iter(tasks)
        for _ in range(workers):
            if task := next(iterator, None):
                waiting.add(pool.submit(work, task))
        while waiting:
            done, waiting = wait(waiting, return_when=FIRST_COMPLETED)
            for future in done:
                item = future.result()
                result['failed' if item['status'] == 'failed' else 'completed'].append(item)
                result['ocr_usage'] = ocr.summary()
                write_json(progress_path, result)
                write_json(public_progress, result)
                logger.info('Reading progress: %s/%s documents, %s errors, %s reported pages',
                            len(result['completed']), len(tasks), len(result['failed']),
                            result['ocr_usage']['reported_pages'])
                # Authentication/funding errors stop new source requests, not the saved results.
                if item.get('http_status') in (401, 402, 403):
                    iterator = iter(())
                if task := next(iterator, None):
                    waiting.add(pool.submit(work, task))
    print(json_text({k: v for k, v in result.items() if k not in ('completed', 'failed')}))
    return result
