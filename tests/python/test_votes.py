"""Offline, fictional parliamentary cases. No synthetic record is written to public data."""
import io
import json
from datetime import date

import httpx
import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from pipeline.models import GroupVote, MemberVote, Source, Vote, VoteCrossCheck, VoteEvidence
from pipeline.parliament import (
    DIP,
    DIP_HELP,
    BundestagClient,
    Download,
    SourceError,
    official_url,
    parse_ballot_links,
    parse_ballots,
    parse_roll_calls,
)
from pipeline.store import json_text, validate_store, write_json
from pipeline.vote_protocols import (
    decision_quote,
    decision_stage,
    group_positions,
    law_decisions,
)
from pipeline.votes import (
    import_fingerprint,
    ingest_votes,
    publication_matches,
    resolve_procedure,
    save_import,
    whole_law_roll_call,
)


@pytest.fixture
def official_source():
    return Source(url=DIP + '/vorgangsposition/123', title='Test protocol', publisher='Test fixture',
                  retrieved_at=date(2025, 6, 1), sha256='a' * 64)


@pytest.fixture
def documented_vote(official_source):
    quote = 'Wer stimmt dafür? – Die SPD. Der Gesetzentwurf ist angenommen.'
    return Vote(id='vote-bgbl-1-2025-100-123-0', dataset='live', law_id='bgbl-1-2025-100',
        date=date(2025, 5, 29), stage='final_passage', compares_to_law=True,
        motion='Test bill', type='group_record', decision='Annahme', source=official_source,
        groups=[GroupVote(group='SPD', party_id='spd', position='yes', evidence_quote=quote)],
        evidence=VoteEvidence(method='bundestag-dip-v1', procedure_id='12', position_id='123', decision_index=0,
            law_match='official_reference', procedure_source=official_source, position_source=official_source,
            text=quote, quote=quote))


def workbook_bytes(*, choice=0, term=21, sitting=12, duplicate=False, formula=False):
    book = Workbook()
    sheet = book.active
    sheet.append(['Wahlperiode', 'Sitzungnr', 'Abstimmnr', 'Fraktion/Gruppe', 'Name', 'Vorname',
                  'ja', 'nein', 'Enthaltung', 'nichtabgegeben', 'ungültig'])
    flags = [0] * 5
    flags[choice] = '=1' if formula else 1
    row = [term, sitting, 1, 'SPD', 'Testperson', 'Erika', *flags]
    sheet.append(row)
    if duplicate:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize('choice', range(5))
def test_all_ballot_categories_reconcile_and_do_not_infer_absences(choice):
    expected = dict.fromkeys(('yes', 'no', 'abstain', 'absent', 'invalid'), 0)
    expected[list(expected)[choice]] = 1
    members, groups, ballot = parse_ballots(workbook_bytes(choice=choice), term=21, sitting=12, expected=expected)
    assert ballot == 1
    assert members[0].vote == list(expected)[choice]
    assert members[0].source_row == 2
    assert groups[0].party_id == 'spd'
    assert groups[0].yes == int(choice == 0)


@pytest.mark.parametrize('change', [{'sitting': 99}, {'term': 20}, {'duplicate': True}, {'formula': True}])
def test_wrong_sitting_duplicate_member_and_formula_cells_fail_closed(change):
    with pytest.raises(SourceError):
        parse_ballots(workbook_bytes(**change), term=21, sitting=12,
                      expected={'yes': 1, 'no': 0, 'abstain': 0, 'absent': 0, 'invalid': 0})


def test_ballot_totals_must_match_all_five_categories():
    with pytest.raises(SourceError, match='disagree'):
        parse_ballots(workbook_bytes(), term=21, sitting=12,
                      expected={'yes': 1, 'no': 0, 'abstain': 0, 'absent': 1, 'invalid': 0})


def test_template_download_list_does_not_duplicate_or_drop_its_text():
    row = '<tr><td><a href="https://www.bundestag.de/resource/blob/1/20250529_1.pdf"><span><span>Testgesetz</span></span></a><a href="https://www.bundestag.de/resource/blob/2/20250529_1_xls.xlsx">XLSX</a></td></tr>'
    result = parse_ballot_links(f'<template data-js-document-results="table">{row}</template><template data-js-document-results="list">{row}</template>'.encode())
    assert len(result) == 1
    assert result[0]['title'] == 'Testgesetz'
    assert result[0]['date'] == date(2025, 5, 29)


def test_roll_call_pagination_uses_the_official_next_offset_not_requested_limit():
    html = b'''<div class="meta-slider" data-hits="31" data-nextoffset="10"></div>
    <div class="bt-slide"><canvas id="canvas-na-123" data-chart-values="1,2,3,4"></canvas>
    <span class="bt-date">29.05.2025</span><div class="bt-teaser-text"><h3><span class="bt-dachzeile">Voting</span>Test bill</h3></div>
    <div class="bt-teaser-haupttext">Gesetzentwurf (21/1)</div></div>'''
    rows, offset, total = parse_roll_calls(html)
    assert (offset, total) == (10, 31)
    assert rows[0]['title'] == 'Test bill'
    assert rows[0]['totals']['absent'] == 4
    assert rows[0]['totals']['invalid'] == 0


def test_document_match_requires_bill_not_only_a_shared_committee_report():
    entry = {'title': 'Testgesetz', 'motion': 'Gesetzentwurf auf Drucksachen 21/2 und 21/3 Buchstabe b'}
    assert not whole_law_roll_call(entry, {'21/1', '21/3'})
    assert whole_law_roll_call(entry, {'21/2', '21/3'})
    for name in ('Änderungsantrag', 'Entschließungsantrag', 'Artikel eins', 'Teile des Gesetzentwurfs'):
        assert not whole_law_roll_call({**entry, 'title': name}, {'21/2', '21/3'})


PROTOCOL = '''Wir kommen zur Abstimmung über den Gesetzentwurf auf Drucksachen 21/1 und 21/2.
Ich bitte diejenigen, die zustimmen wollen, um das Handzeichen. – SPD und CDU/CSU.
Wer stimmt dagegen? – Die Linke. Enthaltungen? – Die AfD.
Damit ist der Gesetzentwurf in zweiter Beratung angenommen.
Dritte Beratung
und Schlussabstimmung. Ich bitte diejenigen, die zustimmen wollen, sich zu erheben. –
Wer stimmt dagegen? – Die Linke. Enthaltungen? – Die AfD.
Der Gesetzentwurf ist damit angenommen.
Entschließungsantrag auf Drucksache 21/3. Wer stimmt dafür? – Die Linke.
'''


def test_second_reading_and_resolution_never_supply_unknown_final_votes():
    second = decision_quote(PROTOCOL, {'21/1'}, 'second_reading')
    final = decision_quote(PROTOCOL, {'21/1'}, 'final_passage')
    assert second and 'Schlussabstimmung' not in second
    assert final and 'Entschließungsantrag' not in final
    assert {g.party_id: g.position for g in group_positions(second)} == {
        'spd': 'yes', 'cdu-csu': 'yes', 'linke': 'no', 'afd': 'abstain'}
    assert {g.party_id: g.position for g in group_positions(final)} == {'linke': 'no', 'afd': 'abstain'}
    assert all(g.yes is None for g in group_positions(final))


def test_other_bill_on_same_page_and_duplicate_blocks_are_not_attached():
    assert decision_quote(PROTOCOL.replace('21/1', '21/9'), {'21/1'}, 'final_passage') is None
    assert decision_quote(PROTOCOL + PROTOCOL, {'21/1'}, 'final_passage') is None


@pytest.mark.parametrize('answer', ['einige Abgeordnete der SPD', 'die Mehrheit der SPD', 'SPD mit einer Ausnahme',
                                    'SPD und eine unbekannte Gruppe', 'die Koalition'])
def test_partial_factions_or_coalition_names_do_not_become_party_positions(answer):
    assert not group_positions(f'Wer stimmt dafür? – {answer}. Der Gesetzentwurf ist angenommen.')


def test_resolution_including_german_sharp_s_and_amendments_have_distinct_stages():
    p = {'vorgangsposition': '3. Beratung'}
    assert decision_stage(p, {'beschlusstenor': 'Annahme einer Entschließung'}) == 'resolution'
    assert decision_stage(p, {'beschlusstenor': 'Ablehnung des Änderungsantrags'}) == 'amendment'
    assert decision_stage(p, {'beschlusstenor': 'Annahme in Ausschussfassung'}) == 'final_passage'


def test_unknown_counts_stay_null_and_counts_cannot_be_invented_for_protocols(documented_vote):
    assert documented_vote.groups[0].yes is None
    with pytest.raises(ValidationError, match='complete'):
        GroupVote(group='SPD', yes=3)
    payload = documented_vote.model_dump()
    payload['groups'][0].update(yes=1, no=0, abstain=0, absent=0)
    with pytest.raises(ValidationError, match='cannot invent'):
        Vote.model_validate(payload)


def test_fictional_review_or_unsupported_quote_cannot_enter_the_record(documented_vote):
    assert documented_vote.review.status == 'proposed'
    payload = documented_vote.model_dump()
    payload['groups'][0]['evidence_quote'] = 'Made up'
    with pytest.raises(ValidationError, match='quote'):
        Vote.model_validate(payload)
    payload = documented_vote.model_dump()
    payload['evidence']['law_match'] = 'exact_title'
    with pytest.raises(ValidationError, match='confirmed final'):
        Vote.model_validate(payload)


@pytest.mark.parametrize('url', ['http://www.bundestag.de/file', 'https://evil.example/file',
                                'https://www.bundestag.de/file?apiKey=secret', 'https://user:pass@www.bundestag.de/file'])
def test_source_allowlist_and_no_query_auth(url):
    with pytest.raises(SourceError):
        official_url(url)


def test_import_is_idempotent_and_citizen_edits_win(tmp_path, documented_vote):
    documented_vote.import_sha256 = import_fingerprint(documented_vote)
    assert save_import(tmp_path, documented_vote) == 'written'
    assert save_import(tmp_path, documented_vote) == 'unchanged'
    edited = documented_vote.model_copy(deep=True)
    edited.note = 'Citizen correction, without changing the review flag'
    write_json(tmp_path / 'live/votes' / f'{edited.id}.json', edited)
    assert save_import(tmp_path, documented_vote) == 'preserved'
    assert Vote.model_validate_json((tmp_path / 'live/votes' / f'{edited.id}.json').read_text()).note == edited.note


@pytest.mark.parametrize('status', [None, 'source_error', 'not_found', 'partial', 'matched'])
def test_unresolved_supplementary_conflicts_survive_skips_outages_and_partial_checks(
        tmp_path, documented_vote, official_source, status):
    source = Source(url='https://www.abgeordnetenwatch.de/api/v2/polls/5?related_data=votes',
                    title='Fictional JSON poll', publisher='abgeordnetenwatch.de',
                    retrieved_at=date(2025, 6, 1), sha256='b' * 64)
    prior = VoteCrossCheck(status='mismatch', checked_at=date(2025, 6, 1), poll_id='5', source=source,
                          total_members=2, compared_members=2, matched_members=1)
    payload = documented_vote.model_dump()
    payload.update(type='roll_call', compares_to_law=False,
                   members=[MemberVote(name=name, group='SPD', vote='yes', source_row=row)
                            for row, name in enumerate(['Erika Testperson', 'Max Beispiel'], 2)],
                   groups=[GroupVote(group='SPD', party_id='spd', yes=2, no=0, abstain=0, absent=0, invalid=0)])
    payload['evidence'].update(roll_call_source=official_source, cross_check=prior)
    previous = Vote.model_validate(payload)
    previous.import_sha256 = import_fingerprint(previous)
    assert save_import(tmp_path, previous) == 'written'
    latest = None if status is None else VoteCrossCheck(
        status=status, checked_at=date(2025, 6, 2), total_members=2,
        source=source if status in ('matched', 'partial') else None,
        poll_id='5' if status in ('matched', 'partial') else None,
        compared_members=2 if status == 'matched' else 1 if status == 'partial' else 0,
        matched_members=2 if status == 'matched' else 1 if status == 'partial' else 0)
    refreshed = previous.model_copy(deep=True)
    refreshed.evidence.cross_check, refreshed.compares_to_law = latest, True
    refreshed.import_sha256 = import_fingerprint(refreshed)
    assert save_import(tmp_path, refreshed) == 'written'
    stored = Vote.model_validate_json((tmp_path / 'live/votes' / f'{previous.id}.json').read_text())
    assert stored.compares_to_law == (status == 'matched')
    assert stored.evidence.cross_check.status == ('matched' if status == 'matched' else 'mismatch')
    assert stored.import_sha256 == import_fingerprint(stored)
    assert save_import(tmp_path, refreshed) == 'unchanged'


def test_future_vote_and_missing_coverage_ids_are_rejected(corpus, documented_vote):
    root, _, _, law = corpus
    documented_vote.date = date(2025, 6, 1)
    write_json(root / 'live/votes' / f'{documented_vote.id}.json', documented_vote)
    with pytest.raises(ValueError, match='after the promulgated'):
        validate_store(root)
    documented_vote.date = date(2025, 5, 29)
    write_json(root / 'live/votes' / f'{documented_vote.id}.json', documented_vote)
    write_json(root / 'live/voting/coverage.json', {'items': [{'law_id': law.id, 'checked_at': '2025-06-01',
        'status': 'recorded', 'vote_ids': ['vote-missing'], 'reason': 'Test fixture'}]})
    with pytest.raises(ValueError, match='wrong vote'):
        validate_store(root)


class FixtureClient:
    def __init__(self, law):
        self.procedure = {'id': '12', 'titel': law.official_title, 'vorgangstyp': 'Gesetzgebung',
            'verkuendung': [{'pdf_url': 'https://www.recht.bund.de/eli/bund/BGBl_1/2025/100',
                            'verkuendungsdatum': str(law.published_at)}]}
        self.position = {'id': '123', 'vorgang_id': '12', 'zuordnung': 'BT', 'datum': '2025-05-29',
            'dokumentart': 'Plenarprotokoll', 'vorgangstyp': 'Gesetzgebung', 'vorgangsposition': '3. Beratung',
            'fundstelle': {'dokumentnummer': '21/12'},
            'beschlussfassung': [{'beschlusstenor': 'Annahme', 'dokumentnummer': '21/1', 'seite': '1234A'}]}

    def listing(self, resource, params):
        return [self.procedure] if resource == 'vorgang' else [self.position]

    def get(self, url, params=None):
        value = self.position if '/vorgangsposition/' in url else self.procedure
        return Download(url, json_text(value).encode(), date(2025, 6, 1))


def test_official_publication_match_requires_exact_issue_and_date(corpus):
    _, _, _, law = corpus
    entry = FixtureClient(law).procedure['verkuendung'][0]
    assert publication_matches(law, entry)
    assert not publication_matches(law, {**entry, 'verkuendungsdatum': '2025-05-31'})
    assert not publication_matches(law, {**entry, 'pdf_url': entry['pdf_url'] + '1'})


def test_ingest_checkpoints_a_decision_without_fabricating_a_group(corpus, tmp_path):
    root, _, _, law = corpus
    result = ingest_votes(root, cache=tmp_path / 'cache', client=FixtureClient(law))
    assert result == {'checked': 1, 'written': 1, 'with_positions': 0, 'decision_only': 1}
    record = Vote.model_validate_json(next((root / 'live/votes').glob('*.json')).read_text())
    assert record.type == 'plenary_record' and not record.groups and record.compares_to_law
    assert record.review.status == 'proposed'
    validate_store(root)
    assert ingest_votes(root, cache=tmp_path / 'cache', client=FixtureClient(law))['written'] == 0


def test_source_failure_is_not_a_successful_no_vote_result(corpus, tmp_path):
    root, _, _, law = corpus
    client = FixtureClient(law)
    client.get = lambda *a, **kw: (_ for _ in ()).throw(SourceError('Official source unavailable'))
    with pytest.raises(SourceError, match='incomplete'):
        ingest_votes(root, cache=tmp_path / 'cache', client=client)
    coverage = json.loads((root / 'live/voting/coverage.json').read_text())
    assert coverage['items'][0]['status'] == 'source_error'
    assert coverage['items'][0]['reason'] == 'Official source unavailable'


def test_old_discontinued_identical_title_does_not_create_false_ambiguity(corpus):
    _, _, _, law = corpus
    client = FixtureClient(law)
    recent = {**client.procedure, 'verkuendung': []}
    old = {**recent, 'id': '11', 'beratungsstand': 'Erledigt durch Ablauf der Wahlperiode'}
    client.listing = lambda _, params: [] if 'f.verkuendung_fundstelle' in params else [old, recent]
    records, match = resolve_procedure(client, law)
    assert [r['id'] for r in records] == ['12'] and match == 'exact_title'
    client.listing = lambda _, params: [] if 'f.verkuendung_fundstelle' in params else [recent, {**recent, 'id': '13'}]
    assert len(resolve_procedure(client, law)[0]) == 2


def test_law_decisions_exclude_bundesrat_future_resolutions_and_partial_votes(corpus):
    _, _, _, law = corpus
    p = FixtureClient(law).position
    assert len(law_decisions([p], law.published_at)) == 1
    assert not law_decisions([{**p, 'zuordnung': 'BR'}, {**p, 'datum': '2026-01-01'}], law.published_at)
    for tenor in ('Annahme einer Entschließung', 'Annahme Artikel 3', 'Überweisung'):
        assert not law_decisions([{**p, 'beschlussfassung': [{'beschlusstenor': tenor}]}], law.published_at)


def test_dip_key_stays_in_memory_and_authorization_header_only(tmp_path, monkeypatch):
    monkeypatch.delenv('DIP_API_KEY', raising=False)
    key = 'example.' + 'x' * 34  # Fictional public-key documentation fixture, not a credential.
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if str(request.url) == DIP_HELP:
            return httpx.Response(200, text='Public access key: ' + key)
        assert request.headers['Authorization'] == 'ApiKey ' + key
        return httpx.Response(200, json={'id': '12'})

    client = BundestagClient(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handle)))
    client.get(DIP + '/vorgang/12')
    client.get(DIP + '/vorgang/12')
    assert len(calls) == 2  # Help never cached; record fetched once.
    assert all(key not in url for url in calls)
    assert all(key.encode() not in p.read_bytes() for p in tmp_path.iterdir())


def test_pagination_refuses_repeated_or_incomplete_cursors(tmp_path, monkeypatch):
    monkeypatch.setenv('DIP_API_KEY', 'test-key')
    body = {'numFound': 2, 'documents': [{'id': '1'}], 'cursor': 'unchanged'}
    client = BundestagClient(tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body))))
    with pytest.raises(SourceError, match='Duplicate'):
        client.listing('vorgang', {})
