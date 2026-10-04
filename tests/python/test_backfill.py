import json
from datetime import date

import pymupdf
import pytest

from pipeline.archive import SEARCH_URL, archive_entries, ingest_archive
from pipeline.catalog import load_catalog
from pipeline.documents import NeedsOCR, extract_pdf, pages_to_markdown
from pipeline.laws import parse_feed, pdf_link
from pipeline.models import Generation
from pipeline.parallel import ordered_map
from pipeline.programs import extract_criteria, ingest_program, structure_paragraphs
from pipeline.store import ROOT, load_records, validate_store

GEN = Generation(model="offline-test", prompt_version="test", input_sha256="0" * 64)


class Stub:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def ask(self, task, data, schema, **kwargs):
        self.calls += 1
        return schema.model_validate(self.answer), GEN


def archive_html(rows, total, next_url=None, modern=False):
    content = f'<p>Suchergebnisse: {total}</p><section class="searchresult">'
    for part, number, day in rows:
        roman = "I" if part == 1 else "II"
        content += (f'<h3>BGBl. 2025 {roman} Nr. {number} vom {day}</h3>'
                    f'<a href="https://www.recht.bund.de/bgbl/{part}/2025/{number}/VO.html">Testgesetz</a>')
    content += '</section>'
    if next_url:
        content += (f'<li class="c-nav-index__item--next"><a href="{next_url}">2</a></li>' if modern
                    else f'<a class="forward button" href="{next_url}">weiter</a>')
    return content.encode()


def mock_archive(monkeypatch, pages):
    responses = iter(pages)
    calls = []
    def download(url, **kwargs):
        calls.append(url)
        return next(responses)
    monkeypatch.setattr("pipeline.archive.public_url", lambda *args: None)
    monkeypatch.setattr("pipeline.archive.download", download)
    return calls


@pytest.mark.parametrize("modern", [False, True])
def test_archive_follows_both_official_pagination_layouts(monkeypatch, modern):
    next_url = SEARCH_URL + '?gtp=196114_list%253D2'
    calls = mock_archive(monkeypatch, [
        archive_html([(1, '100', '30.05.2025')], 2, next_url, modern),
        archive_html([(2, '10a', '01.06.2025')], 2),
    ])
    rows, pages = archive_entries(since=date(2025, 3, 25), until=date(2025, 6, 1))
    assert [r['id'] for r in rows] == ['bgbl-1-2025-100', 'bgbl-2-2025-10a']
    assert rows[1]['citation'] == 'BGBl. 2025 II Nr. 10a'
    assert len(pages) == len(calls) == 2 and calls[1] == next_url


@pytest.mark.parametrize("fault", ["missing_page", "duplicate", "changed_total", "out_of_window", "loop"])
def test_archive_refuses_falsely_complete_inventories(monkeypatch, fault):
    next_url = SEARCH_URL + '?page=2'
    first = archive_html([(1, '100', '30.05.2025')], 2, next_url)
    second = archive_html([(2, '10', '01.06.2025')], 2)
    if fault == 'missing_page':
        first = archive_html([(1, '100', '30.05.2025')], 2)
    elif fault == 'duplicate':
        second = archive_html([(1, '100', '30.05.2025')], 2)
    elif fault == 'changed_total':
        second = archive_html([(2, '10', '01.06.2025')], 3)
    elif fault == 'out_of_window':
        second = archive_html([(2, '10', '01.07.2025')], 2)
    elif fault == 'loop':
        second = archive_html([(2, '10', '01.06.2025')], 2, next_url)
    mock_archive(monkeypatch, [first, second])
    with pytest.raises(ValueError):
        archive_entries(since=date(2025, 3, 25), until=date(2025, 6, 1))


def test_archive_coverage_is_a_noop_without_new_data_and_records_remainder(corpus, monkeypatch):
    root, _, _, law = corpus
    entries = [{'id': law.id}]
    monkeypatch.setattr('pipeline.archive.archive_entries', lambda **kw: (
        entries, [{'url': SEARCH_URL, 'sha256': '0' * 64}]))
    monkeypatch.setattr('pipeline.archive.ingest_entries', lambda **kw: {'new_laws': [], 'notify': False})
    result = ingest_archive(root=root, since=date(2025, 3, 25), until=date(2025, 6, 1))
    assert result['coverage_complete']
    path = root / 'live/coverage/laws-since-2025-03-25.json'
    before = path.read_bytes()
    ingest_archive(root=root, since=date(2025, 3, 25), until=date(2025, 6, 2))
    assert path.read_bytes() == before  # No timestamp-only PR.
    entries.append({'id': 'bgbl-2-2025-10'})
    result = ingest_archive(root=root, since=date(2025, 3, 25), until=date(2025, 6, 2), limit=1)
    assert not result['coverage_complete'] and result['remaining_in_archive'] == 1
    assert json.loads(path.read_text())['pending_ids'] == ['bgbl-2-2025-10']
    validate_store(root)


def test_bgbl_part_two_feed_and_pdf_are_supported():
    feed = b'''<rss xmlns:meta="http://recht.bund.de/rss/meta"><channel><item><title>Vertragsgesetz</title>
    <link>https://www.recht.bund.de/eli/bund/bgbl-2/2025/22</link><pubDate>2025-06-01</pubDate>
    <meta:typ>Gesetz</meta:typ><meta:fundstelle>BGBl. 2025 II Nr. 22</meta:fundstelle></item></channel></rss>'''
    assert parse_feed(feed)[0]['id'] == 'bgbl-2-2025-22'
    pdf = 'https://www.recht.bund.de/bgbl/2/2025/22/regelungstext.pdf?__blob=publicationFile'
    html = f'<a href="{pdf}">PDF</a>'.encode()
    assert pdf_link(html, 'https://www.recht.bund.de/eli/bund/bgbl-2/2025/22') == pdf
    with pytest.raises(ValueError):
        pdf_link(html, 'https://www.recht.bund.de/eli/bund/bgbl-1/2025/22')


def test_inspected_blank_pages_are_preserved_not_silently_dropped():
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), 'A manifesto with an intentionally blank reverse page.')
        doc.new_page()
        pdf = doc.tobytes()
    with pytest.raises(NeedsOCR):
        extract_pdf(pdf)
    pages = extract_pdf(pdf, textless_pages={2})
    markdown, leaves = pages_to_markdown(pages, 'test-program')
    assert len(pages) == 2 and not pages[1]
    assert '<!-- page:2 -->' in markdown and 'no extractable text' in markdown
    assert all(leaf.reference.page == 1 for leaf in leaves)
    with pytest.raises(ValueError, match='outside'):
        extract_pdf(pdf, textless_pages={3})


def test_native_text_fallback_recovers_dropped_chapter_titles(monkeypatch):
    import pymupdf4llm
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), 'Chapter heading preserved by the native PDF text layer.')
        pdf = doc.tobytes()
    monkeypatch.setattr(pymupdf4llm, 'to_markdown', lambda *a, **kw: [{'text': ''}])
    assert 'Chapter heading' in extract_pdf(pdf)[0]


def test_semantic_paragraphs_join_only_source_ranges_and_preserve_all_text():
    markdown, raw = pages_to_markdown(['This is the first half\n\nof a continued sentence.'], 'test-program')
    groups = {'groups': [{'start': 0, 'end': 1, 'sections': ['Section']}]}
    leaves, tree, _ = structure_paragraphs(raw, markdown, 'Title', 'test-program', Stub(groups))
    assert len(leaves) == 1
    assert leaves[0].text == 'This is the first half\n\nof a continued sentence.'
    assert leaves[0].text in markdown and tree.children[0].leaf_ids == [leaves[0].id]
    other_md, other_raw = pages_to_markdown(['First page.', 'Second page.'], 'test-program')
    continued, _, _ = structure_paragraphs(other_raw, other_md, 'Title', 'test-program', Stub(groups))
    assert [p.reference.page for p in continued] == [1, 2]
    assert [p.text for p in continued] == ['First page.', 'Second page.']
    with pytest.raises(ValueError, match='omitted'):
        structure_paragraphs(raw, markdown, 'Title', 'test-program', Stub({
            'groups': [{'start': 0, 'end': 0, 'sections': ['Section']}]}))


def test_model_paragraph_groups_are_split_without_duplicating_long_source_blocks():
    text = 'A long source sentence. ' * 350
    markdown, raw = pages_to_markdown([text], 'test-program')
    assert len(raw) > 1
    groups = {'groups': [{'start': 0, 'end': len(raw) - 1, 'sections': ['Section']}]}
    leaves, _, _ = structure_paragraphs(raw, markdown, 'Title', 'test-program', Stub(groups))
    assert [p.text for p in leaves] == [p.text for p in raw]
    assert all(len(p.text) <= 4500 for p in leaves)
    # Distinct short blocks may be grouped semantically, but their combined citation stays bounded.
    markdown, raw = pages_to_markdown(['A' * 3000 + '\n\n' + 'B' * 3000], 'test-program')
    leaves, _, _ = structure_paragraphs(raw, markdown, 'Title', 'test-program', Stub(groups))
    assert [p.text for p in leaves] == ['A' * 3000, 'B' * 3000]


def test_batched_criteria_cover_every_leaf_and_remain_unassessed(corpus):
    root, program, criterion, _ = corpus
    (root / f'live/criteria/{criterion.id}.json').unlink()
    proposal = {'title': 'Mindestlohn erhöhen', 'description': 'Den Mindestlohn auf 15 Euro anheben.',
                'test': 'Der Mindestlohn beträgt 15 Euro.', 'quote': program.leaves[0].text,
                'tags': ['arbeit'], 'keywords': ['Mindestlohn'], 'deadline': None}
    answers = [{'leaf_id': p.id, 'criteria': [proposal] if i == 0 else [],
                'abstention_reason': None if i == 0 else 'Nur Rhetorik.'} for i, p in enumerate(program.leaves)]
    result = extract_criteria(root=root, program_id=program.id,
                              agent=Stub({'paragraphs': answers}), batch_size=6, workers=2)
    assert result['new_criteria'] == 1 and result['abstained_leaves'] == 1
    assert load_records(root, 'live', 'criteria')[0].assessment.status == 'unassessed'
    assert len(load_records(root, 'live', 'programs')[0].criteria_extraction) == 2
    validate_store(root)


def test_bad_criterion_batch_writes_no_partial_data(corpus):
    root, program, criterion, _ = corpus
    (root / f'live/criteria/{criterion.id}.json').unlink()
    agent = Stub({'paragraphs': [{'leaf_id': program.leaves[1].id, 'criteria': [],
                                 'abstention_reason': 'Nur Rhetorik.'}]})
    with pytest.raises(ValueError, match='every leaf'):
        extract_criteria(root=root, program_id=program.id, agent=agent, batch_size=6)
    assert not load_records(root, 'live', 'criteria')
    assert not load_records(root, 'live', 'programs')[0].criteria_extraction


def test_source_hash_and_reuse_basis_fail_before_pdf_or_model_work(corpus, tmp_path):
    root, *_ = corpus
    pdf = tmp_path / 'changed.pdf'
    pdf.write_bytes(b'%PDF-not-the-inspected-edition')
    kwargs = dict(root=root, agent=Stub({}), pdf=str(pdf), program_id='spd-new', party='spd', year=2025,
                  title='A test programme', source_url='https://example.org/programme', published=date(2025, 1, 1),
                  period_start=date(2025, 3, 25), period_end=None)
    with pytest.raises(ValueError, match='reuse licence'):
        ingest_program(**kwargs)
    kwargs['license_note'] = 'Synthetic test fixture with explicit reuse permission.'
    with pytest.raises(ValueError, match='changed since'):
        ingest_program(**kwargs, expected_sha256='0' * 64)
    assert kwargs['agent'].calls == 0


def test_source_catalog_covers_ssw_and_joint_union_without_implying_permission():
    catalog = load_catalog(ROOT / 'data')
    assert len(catalog.programs) == 6 and sum(len(p.members) for p in catalog.programs) == 7
    assert 'ssw' in {p.party_id for p in catalog.programs}
    blocked = [p for p in catalog.programs if p.rights.status == 'permission-required']
    assert len(blocked) == 5
    for source in blocked:
        with pytest.raises(PermissionError):
            source.require_publication_basis()
    from scripts.backfill_entry import run
    agent = Stub({})
    with pytest.raises(PermissionError):
        run('cdu-csu-2025', agent=agent)
    assert agent.calls == 0


def test_bounded_work_queue_preserves_order_and_none_values():
    assert list(ordered_map(lambda x: x, [3, None, 1], workers=2)) == [3, None, 1]
    with pytest.raises(ValueError):
        list(ordered_map(lambda x: x, [1], workers=5))
