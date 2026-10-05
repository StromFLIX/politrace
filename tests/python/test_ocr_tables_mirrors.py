import json

import httpx
import pytest
from pydantic import HttpUrl

from pipeline.reading import (
    MistralOCR,
    ReadingTable,
    download_candidates,
    expand_tables,
    source_pdf,
)
from pipeline.store import digest, write_json
from tests.python.test_reading_editions import client, pdf_bytes, response


def test_table_sidecar_expands_in_place_not_as_broken_relative_link():
    table = ReadingTable(id='tbl-0.md', content='| Betrag |\n| --- |\n| 15 Euro |')
    result = expand_tables('# Gesetz\n\n[tbl-0.md](tbl-0.md)\n\nArtikel 2', [table])
    assert '| 15 Euro |' in result
    assert result.index('15 Euro') < result.index('Artikel 2')
    assert '](' not in result


def test_missing_or_unplaced_tables_are_errors_not_empty_reading_pages():
    with pytest.raises(ValueError, match='missing table'):
        expand_tables('[tbl-9.md](tbl-9.md)', [])
    with pytest.raises(ValueError, match='unplaced table'):
        expand_tables('No table anchor.', [ReadingTable(id='tbl-0.md', content='| Heading |')])


def test_sidecars_survive_cache_and_provider_extra_fields(tmp_path, monkeypatch):
    body = response((0,))
    body['pages'][0].update(markdown='[tbl-0.md](tbl-0.md)', tables=[{
        'id': 'tbl-0.md', 'content': '| Betrag |\n| --- |\n| 15 Euro |', 'format': 'markdown',
        'word_confidence_scores': [{'word': 'Betrag', 'confidence': 0.99}],
    }])
    ocr = MistralOCR(tmp_path, client=client(monkeypatch, lambda _: httpx.Response(200, json=body)))
    pdf = pdf_bytes()
    pages = ocr.pages(pdf, [0], digest(pdf), ['', ''])
    assert '15 Euro' in pages[0][0].markdown
    assert pages[0][0].tables[0].id == 'tbl-0.md'
    assert ocr.pages(pdf, [0], digest(pdf), ['', '']) == pages
    assert ocr.summary()['calls'] == 1
    cache = json.loads(next((tmp_path / 'mistral-reading-v1').rglob('*.json')).read_text())
    assert 'word_confidence_scores' not in cache['page']['tables'][0]


def setup_mirror(root, program, pdf):
    program.source.sha256 = digest(pdf)
    program.pdf_url = HttpUrl('https://publisher.example/programme.pdf')
    write_json(root / 'sources/document-mirrors.json', {'schema_version': '1.0', 'documents': [{
        'document_id': program.id, 'source_url': str(program.pdf_url), 'source_sha256': digest(pdf),
        'mirror_urls': ['https://archive.example/programme.pdf'], 'verified_at': '2026-10-05',
        'note': 'Checksum-verified download mirror; not a licence grant.',
    }]})


def test_mirror_requires_original_checksum_and_retains_download_provenance(corpus, tmp_path, monkeypatch):
    root, program, _, _ = corpus
    pdf = pdf_bytes()
    setup_mirror(root, program, pdf)
    calls = []
    def download(url):
        calls.append(url)
        return pdf
    monkeypatch.setattr('pipeline.reading.download', download)
    result, location = source_pdf(root, program, tmp_path / 'ocr')
    assert result == pdf
    assert location == 'https://archive.example/programme.pdf'
    assert calls == [location]
    assert source_pdf(root, program, tmp_path / 'ocr') == (result, location)
    assert len(calls) == 1


def test_different_document_at_mirror_is_rejected_then_original_used(corpus, tmp_path, monkeypatch):
    root, program, _, _ = corpus
    pdf = pdf_bytes()
    setup_mirror(root, program, pdf)
    monkeypatch.setattr('pipeline.reading.download', lambda url: pdf if 'publisher.' in url else b'%PDF wrong file')
    result, location = source_pdf(root, program, tmp_path / 'ocr')
    assert result == pdf and location == str(program.pdf_url)
    program.source.sha256 = 'a' * 64
    with pytest.raises(ValueError, match='pinned original source'):
        download_candidates(root, program)
