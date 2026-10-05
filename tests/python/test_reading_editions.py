import json

import httpx
import pymupdf
import pytest
from pydantic import HttpUrl

from pipeline.reading import MistralOCR, OCRFailure, clean_markdown, create_reading, native_recall
from pipeline.store import digest, write_json


def pdf_bytes():
    with pymupdf.open() as doc:
        for text in ['First source page with several words.', 'Second source page with different words.']:
            page = doc.new_page()
            page.insert_text((60, 60), text)
        return doc.tobytes()


def response(pages=(0, 1)):
    return {'model': 'mistral-ocr-verified-test', 'pages': [
        {'index': i, 'markdown': f'# Page {i + 1}\n\nReadable source text.', 'header': 'Header', 'footer': 'Footer'}
        for i in pages], 'usage_info': {'pages_processed': len(pages)}}


def client(monkeypatch, handler):
    monkeypatch.setenv('MISTRAL_API_KEY', 'test-only-not-a-real-key')
    monkeypatch.setattr('pipeline.reading.time.sleep', lambda _: None)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_all_pages_cached_no_images_or_credentials_in_cache(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload['extract_header'] and payload['extract_footer']
        assert payload['include_image_base64'] is False
        assert payload['document']['document_url'].startswith('data:application/pdf;base64,')
        return httpx.Response(200, json=response())
    ocr = MistralOCR(tmp_path, client=client(monkeypatch, handler))
    pdf = pdf_bytes()
    pages = ocr.pages(pdf, [0, 1], digest(pdf), ['', ''])
    assert [p.number for p, _ in pages] == [1, 2]
    assert pages[0][0].header == 'Header'
    ocr.pages(pdf, [0, 1], digest(pdf), ['', ''])
    assert len(calls) == 1
    assert ocr.summary()['reported_pages'] == 2
    assert ocr.summary()['reported_cost_usd'] is None
    for path in tmp_path.rglob('*.json'):
        assert 'test-only-not-a-real-key' not in path.read_text()
        assert 'base64' not in path.read_text()


@pytest.mark.parametrize('indexes', [(0,), (0, 0), (1, 2), (0, 1, 2)])
def test_missing_duplicate_or_extra_pages_rejected_after_accounting(tmp_path, monkeypatch, indexes):
    ocr = MistralOCR(tmp_path, client=client(monkeypatch, lambda _: httpx.Response(200, json=response(indexes))))
    with pytest.raises(ValueError, match='every requested page'):
        ocr.pages(pdf_bytes(), [0, 1], 'a' * 64, ['', ''])
    assert ocr.summary()['reported_pages'] == len(indexes)


def test_auth_error_not_retried_and_body_never_exposed(tmp_path, monkeypatch):
    ocr = MistralOCR(tmp_path, client=client(monkeypatch, lambda _: httpx.Response(401, json={'message': 'private-body'})))
    with pytest.raises(OCRFailure) as error:
        ocr.pages(pdf_bytes(), [0], 'a' * 64, ['', ''])
    assert 'private-body' not in str(error.value)
    assert ocr.summary()['calls'] == 1
    assert ocr.summary()['unknown_charge_pages'] == 1


def test_rate_limit_retried_with_retained_usage(tmp_path, monkeypatch):
    responses = [httpx.Response(429), httpx.Response(200, json=response((0,)))]
    ocr = MistralOCR(tmp_path, client=client(monkeypatch, lambda _: responses.pop(0)))
    pages = ocr.pages(pdf_bytes(), [1], 'a' * 64, ['', ''])
    assert pages[0][0].number == 2  # Subset-local index maps to the original PDF.
    assert ocr.summary()['reported_pages'] == 1
    assert ocr.summary()['unknown_charge_pages'] == 1
    assert ocr.next_request_at > 0


def test_cleanup_is_layout_only_and_never_discards_policy_numbers():
    assert clean_markdown('![img-0.jpeg](img-0.jpeg)\n\n# Gesetz\n\n15 Euro; CO2-Preis.') == '# Gesetz\n\n15 Euro; CO2-Preis.'
    assert clean_markdown('[](javascript:evil) <script>evil</script>') == '[](javascript:evil) <script>evil</script>'  # Renderer must escape.
    assert clean_markdown('Verant-\nwortung') == 'Verant-\nwortung'  # No speculative word edits.


def test_native_coverage_is_a_warning_not_approval():
    assert native_recall('short', 'other') is None
    source = 'Land Schule Arbeit Einkommen Steuern Miete Gesundheit Verkehr Menschen Klima Bildung'
    assert native_recall(source, source) == 1
    assert native_recall(source, 'Land Schule') < .3


def test_reading_preserves_evidence_and_checks_pdf_sha(corpus, tmp_path, monkeypatch):
    root, program, _, _ = corpus
    pdf = pdf_bytes()
    program.source.sha256 = digest(pdf)
    program.pdf_url = HttpUrl('https://example.org/source.pdf')
    write_json(root / 'live/programs' / f'{program.id}.json', program)
    before = (root / program.markdown_path).read_bytes()
    monkeypatch.setattr('pipeline.reading.download', lambda _: pdf)
    ocr = MistralOCR(tmp_path / 'ocr', client=client(monkeypatch, lambda _: httpx.Response(200, json=response())))
    assert create_reading(root, program, 'programs', ocr)['status'] == 'completed'
    assert (root / program.markdown_path).read_bytes() == before
    assert create_reading(root, program, 'programs', ocr)['status'] == 'unchanged'
    program.source.sha256 = 'a' * 64
    with pytest.raises(ValueError, match='Source PDF changed'):
        create_reading(root, program, 'programs', ocr)


def test_second_process_cannot_race_the_same_ocr_ledger(tmp_path):
    first = MistralOCR(tmp_path)
    with pytest.raises(BlockingIOError):
        MistralOCR(tmp_path)
    assert first.summary()['calls'] == 0
