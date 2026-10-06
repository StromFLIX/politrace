"""Offline structured-source regressions; all parliamentary people/cases here are fictional."""
import io
import json
from datetime import date
from urllib.parse import urlencode

import httpx
import pytest
from openpyxl import Workbook

from pipeline.models import MemberVote
from pipeline.parliament import (
    BALLOT_INDEX,
    BT,
    BundestagClient,
    Download,
    SourceError,
    parse_ballot_links,
    roll_call_detail,
)
from pipeline.transcripts import TranscriptProvider, parse_protocol_links, parse_transcript
from pipeline.vote_crosscheck import (
    AW,
    AbgeordnetenwatchClient,
    VoteCrossChecker,
    compare_members,
    poll_matches,
    supplementary_url,
)
from pipeline.vote_protocols import decision_passage, decision_quote, group_positions
from pipeline.votes import VoteImporter

STAMP = date(2025, 5, 29)
TOTALS = {'yes': 1, 'no': 0, 'abstain': 0, 'absent': 0, 'invalid': 0}
ENTRY = {'id': '123', 'date': STAMP, 'title': 'Testgesetz',
         'motion': 'Gesetzentwurf auf Drucksachen 21/1 und 21/2', 'totals': TOTALS}
POSITION = {'datum': str(STAMP), 'fundstelle': {'id': '99', 'dokumentnummer': '21/12',
            'xml_url': 'https://dserver.bundestag.de/btp/21/21012.xml'}}
DECISION = {'beschlusstenor': 'Annahme', 'dokumentnummer': '21/1, 21/2',
            'abstimmungsart': 'Namentliche Abstimmung'}
PROTOCOL = '''Wir kommen zur Abstimmung über den Gesetzentwurf auf Drucksachen 21/1 und 21/2.
Ich bitte diejenigen, die zustimmen wollen, um das Handzeichen. – SPD.
Wer stimmt dagegen? – Die Linke. Enthaltung? – Die AfD.
Damit ist der Gesetzentwurf in zweiter Beratung angenommen.
Dritte Beratung und Schlussabstimmung. Ich bitte diejenigen, die zustimmen wollen, sich zu erheben.
Wer stimmt dagegen? – Die Linke. Enthaltung? – Die AfD. Der Gesetzentwurf ist angenommen.'''


def xml(body, *, term=21, sitting=12, stamp='29.05.2025'):
    return (f'<dbtplenarprotokoll wahlperiode="{term}" sitzung-nr="{sitting}" sitzung-datum="{stamp}">'
            f'<inhaltsverzeichnis><p>{PROTOCOL}</p></inhaltsverzeichnis><sitzungsverlauf>'
            f'<tagesordnungspunkt top-id="TOP 2">{body}</tagesordnungspunkt>'
            '</sitzungsverlauf></dbtplenarprotokoll>').encode()


def positions(quote):
    return {g.party_id: g.position for g in group_positions(quote)}


def test_xml_uses_chair_blocks_not_toc_speeches_or_ballot_rosters():
    body = f'<rede><p>{PROTOCOL}</p></rede><p>Chair procedural remarks.</p><p klasse="AL_Namen">SPD</p>'
    transcript = parse_transcript(xml(body))
    assert len(transcript.blocks) == 1
    assert transcript.blocks[0].text == 'Chair procedural remarks.'
    assert not decision_quote(transcript.blocks[0].text, {'21/1'}, 'final_passage')
    actual = parse_transcript(xml(f'<p>{PROTOCOL}</p>')).blocks[0]
    quote = decision_quote(actual.text, {'21/1', '21/2'}, 'final_passage')
    assert positions(quote) == {'linke': 'no', 'afd': 'abstain'}  # Not the second reading's SPD vote.


def test_xml_does_not_turn_interjections_into_chair_answers():
    body = '<p>Gesetzentwurf auf Drucksache 21/1. Dritte Beratung und Schlussabstimmung. Wer stimmt dafür?</p><kommentar>SPD</kommentar><p>Der Gesetzentwurf ist angenommen.</p>'
    blocks = parse_transcript(xml(body)).blocks
    assert len(blocks) == 1 and len(blocks[0].comment_spans) == 1
    block = blocks[0]
    quote, start, end = decision_passage(block.text, {'21/1'}, 'final_passage', block.comment_spans)
    comments = [(a - start, b - start) for a, b in block.comment_spans]
    assert quote == block.text[start:end] and 'SPD' in quote  # Source text remains verbatim.
    assert group_positions(quote, comments) == []  # The interjection is not a chair announcement.


def test_xml_rejects_entities_and_missing_proceedings():
    with pytest.raises(SourceError, match='structured'):
        parse_transcript(b'<!DOCTYPE doc [<!ENTITY x SYSTEM "file:///etc/passwd">]><doc>&x;</doc>')
    with pytest.raises(SourceError, match='structured'):
        parse_transcript(b'<html>Not a protocol</html>')


def protocol_index(sitting=12):
    row = f'<tr><td><a href="/resource/blob/123/21{sitting:03}.xml">XML</a></td></tr>'
    return f'<template data-js-document-results="table">{row}</template><template data-js-document-results="list">{row}</template>'.encode()


def documentation():
    return b'''<div x-data='documents({"endpoint":"/ajax/filterlist/de/services/opendata/21-21"})'><h2>Plenarprotokolle der 21. Wahlperiode</h2></div>
    <div x-data='documents({"endpoint":"/ajax/filterlist/de/services/opendata/20-20"})'><h2>Plenarprotokolle der 20. Wahlperiode</h2></div>'''


class XmlClient:
    def __init__(self, primary=None, *, unavailable=False):
        self.primary = primary or xml(f'<p>{PROTOCOL}</p>')
        self.unavailable = unavailable
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if url.endswith('/services/opendata'):
            content = documentation()
        elif '/ajax/' in url:
            content = protocol_index()
        elif '/resource/blob/' in url:
            if self.unavailable:
                raise SourceError('Interactive browser challenge')
            content = self.primary
        else:
            assert url == POSITION['fundstelle']['xml_url']
            content = xml('<p>Incomplete alternative copy.</p>')
        return Download(url, content, STAMP)


def test_open_data_copy_is_preferred_to_incomplete_dip_link_and_own_heading_identifies_term():
    client = XmlClient()
    provider = TranscriptProvider(client)
    assert provider._endpoints()[21].endswith('/21-21')
    downloaded, transcript, fallback = provider.get(POSITION)
    assert downloaded.url == BT + '/resource/blob/123/21012.xml'
    assert fallback is None and decision_quote(transcript.blocks[0].text, {'21/1'}, 'final_passage')
    assert all(url != POSITION['fundstelle']['xml_url'] for url, _ in client.calls)


def test_xml_fallback_is_explicit_and_never_a_pdf():
    client = XmlClient(unavailable=True)
    downloaded, transcript, fallback = TranscriptProvider(client).get(POSITION)
    assert fallback == 'opendata_unavailable'
    assert downloaded.url == POSITION['fundstelle']['xml_url']
    assert not decision_quote(transcript.blocks[0].text, {'21/1'}, 'final_passage')
    assert all('.pdf' not in url for url, _ in client.calls)


@pytest.mark.parametrize('change', [{'term': 20}, {'sitting': 13}, {'stamp': '30.05.2025'}])
def test_xml_metadata_must_match_exact_dip_decision(change):
    client = XmlClient(primary=xml('<p>Chair</p>', **change))
    with pytest.raises(SourceError, match='sitting/date'):
        TranscriptProvider(client).get(POSITION)


def test_protocol_index_ignores_duplicate_list_template_and_detects_stalled_pagination():
    assert len(parse_protocol_links(protocol_index(), 21)) == 1
    client = XmlClient()
    with pytest.raises(SourceError, match='Repeated'):
        TranscriptProvider(client).xml_url(21, 11)
    assert [params['offset'] for url, params in client.calls if '/ajax/' in url] == [0, 1]


def test_exact_singular_abstention_and_presidential_standing_instructions():
    quote = '''Dritte Beratung und Schlussabstimmung. Ich bitte diejenigen, die zustimmen wollen, sich zu erheben.
    – Das ist die Unionsfraktion und die SPD. Sie dürfen sich wieder setzen.
    Wer dagegenstimmen möchte, möge sich bitte erheben. – Die Grünen und Die Linke.
    Auch Sie dürfen sich wieder setzen. Enthaltung? – Die AfD. Ich sage Herzlichen Dank.
    Damit ist der Gesetzentwurf angenommen.'''
    assert positions(quote) == {'cdu-csu': 'yes', 'spd': 'yes', 'gruene': 'no', 'linke': 'no', 'afd': 'abstain'}
    quote = 'Wer stimmt dafür? Wer stimmt dagegen? Enthaltung? Der Gesetzentwurf ist angenommen worden mit den Stimmen von SPD bei Enthaltung der Fraktion Die Linke.'
    assert positions(quote) == {'spd': 'yes', 'linke': 'abstain'}


def test_bill_identity_can_follow_final_marker_but_still_requires_all_references():
    quote = '''Zweite Beratung und Schlussabstimmung. Der Ausschuss empfiehlt auf Drucksache 21/2,
    den Gesetzentwurf auf Drucksache 21/1 anzunehmen. Ich bitte diejenigen, die zustimmen wollen, sich zu erheben.
    – SPD. Wer stimmt dagegen? – Die Linke. Der Gesetzentwurf ist angenommen.'''
    assert decision_quote(quote, {'21/1', '21/2'}, 'final_passage')
    assert not decision_quote(quote, {'21/3', '21/2'}, 'final_passage')


def test_explicit_next_reading_can_identify_previous_result_but_not_transfer_its_votes():
    text = PROTOCOL.replace('in zweiter Beratung angenommen', 'angenommen')
    quote = decision_quote(text, {'21/1', '21/2'}, 'final_passage')
    assert quote and positions(quote) == {'linke': 'no', 'afd': 'abstain'}
    assert not positions('Wer stimmt dafür? – Die Koalition. Wer stimmt dagegen? – Der Rest des Hauses. Der Gesetzentwurf ist angenommen.')
    assert not positions('Wer stimmt dafür? – Alle Fraktionen. Der Gesetzentwurf ist einstimmig angenommen.')
    assert not positions('Dritte Beratung und Schlussabstimmung. Der Gesetzentwurf ist bei gleichem Stimmergebnis wie zuvor angenommen.')


@pytest.mark.parametrize('summary', [
    'Alle Teile des Gesetzentwurfs sind in zweiter Beratung angenommen.',
    'Alle Teile des Gesetzentwurfs sind damit in zweiter Beratung angenommen.',
])
def test_partial_reading_summary_carries_only_bill_identity_into_the_final(summary):
    text = f'''Der Ausschuss empfiehlt auf Drucksache 21/2, den Gesetzentwurf auf Drucksache 21/1 anzunehmen.
    Ich bitte diejenigen, die den übrigen Teilen des Gesetzentwurfs zustimmen wollen, um das Handzeichen.
    – AfD. Wer stimmt dagegen? – SPD. Damit sind die übrigen Teile des Gesetzentwurfs angenommen.
    {summary}
    Dritte Beratung und Schlussabstimmung. Ich bitte diejenigen, die zustimmen wollen, sich zu erheben.
    – SPD. Wer stimmt dagegen? – Die Linke. Der Gesetzentwurf ist angenommen.'''
    quote = decision_quote(text, {'21/1', '21/2'}, 'final_passage')
    assert quote and positions(quote) == {'spd': 'yes', 'linke': 'no'}
    assert 'AfD' not in quote and summary not in quote
    assert not decision_quote(text, {'21/3', '21/2'}, 'final_passage')
    assert not decision_quote(text, {'21/1', '21/2'}, 'second_reading')
    # An intervening item or new motion breaks the immediate identity chain.
    unrelated = text.replace(summary, 'Zusatzpunkt 4. Ein anderer Gesetzentwurf. ' + summary)
    assert not decision_quote(unrelated, {'21/1', '21/2'}, 'final_passage')


def test_explicit_second_reading_result_overrides_another_bills_pending_final_marker():
    text = '''Dritte Beratung und Schlussabstimmung. Die namentliche Abstimmung über Drucksache 21/9 läuft.
    Zusatzpunkt 3. Der Ausschuss empfiehlt auf Drucksache 21/2, den Gesetzentwurf auf Drucksache 21/1 anzunehmen.
    Ich bitte diejenigen, die zustimmen wollen, um das Handzeichen. Wer stimmt dagegen?
    Der Gesetzentwurf ist in zweiter Lesung angenommen.
    Dritte Beratung und Schlussabstimmung. Ich bitte diejenigen, die zustimmen wollen, sich zu erheben.
    – SPD. Wer stimmt dagegen? – Die Linke. Der Gesetzentwurf ist angenommen.'''
    quote = decision_quote(text, {'21/1', '21/2'}, 'final_passage')
    assert quote and positions(quote) == {'spd': 'yes', 'linke': 'no'}
    assert not decision_quote(text, {'21/9'}, 'final_passage')


def detail(*, json_result=False, wrong_total=False):
    data = {k: v for k, v in TOTALS.items() if k != 'invalid'}
    content = '''<article><span class="bt-date">29. Mai 2025</span><h1 class="bt-artikel__title">Testgesetz</h1>
    <p>Gesetzentwurf auf Drucksachen 21/1 und 21/2</p></article>
    <canvas data-chart-type="bar" data-chart-values="1,0,0,0"></canvas>
    <div class="bt-teaser-chart-solo" data-value="SPD"><canvas data-chart-values="1,0,0,0"></canvas></div>'''
    if json_result:
        content += '<script type="application/json"><![CDATA[' + json.dumps({
            'href': '/parlament/plenum/abstimmung/abstimmung?id=123', 'date': str(STAMP),
            'votes': {**data, 'yes': 9} if wrong_total else data,
        }) + ']]></script>'
    return Download(BT + '/parlament/plenum/abstimmung/abstimmung?id=123', content.encode(), STAMP)


@pytest.mark.parametrize('embedded', [True, False])
def test_official_chart_counts_and_optional_embedded_json_are_structured_evidence(embedded):
    result = roll_call_detail(detail(json_result=embedded), ENTRY)
    assert result['group_totals'] == {'spd': TOTALS}


def test_disagreement_in_embedded_json_is_not_silently_ignored():
    with pytest.raises(SourceError, match='JSON result'):
        roll_call_detail(detail(json_result=True, wrong_total=True), ENTRY)


def workbook(choice='ja'):
    book = Workbook()
    sheet = book.active
    fields = ['Wahlperiode', 'Sitzungnr', 'Abstimmnr', 'Fraktion/Gruppe', 'Name', 'Vorname',
              'ja', 'nein', 'Enthaltung', 'nichtabgegeben', 'ungültig']
    sheet.append(fields)
    sheet.append([21, 12, 1, 'SPD', 'Testperson', 'Erika', *[int(f == choice) for f in fields[6:]]])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def named_importer(*, title='Testgesetz', same_result=False, duplicate_sheet=False, choice='ja'):
    class Client:
        calls = []

        def get(self, url, params=None):
            self.calls.append(url)
            if '/abstimmung/abstimmung' in url:
                return detail()
            return Download(url, workbook(choice), STAMP)

    importer = VoteImporter(Client())
    importer.inventory_since = STAMP
    importer.roll_calls = [ENTRY, *([{**ENTRY, 'id': '124', 'motion': 'Antrag auf Drucksache 21/3'}] if same_result else [])]
    index = Download(BALLOT_INDEX + '?limit=30&offset=0', b'official index', STAMP).source('Index')
    sheet = {'date': STAMP, 'title': title, 'url': BT + '/resource/blob/123/20250529_9_xls.xlsx', 'index_source': index}
    importer.ballot_links = [sheet, *([{**sheet, 'url': BT + '/resource/blob/124/20250529_xls.xlsx'}] if duplicate_sheet else [])]
    return importer


def test_named_join_never_downloads_pdfs_or_treats_filename_suffix_as_ballot_identity():
    importer = named_importer()
    matched = importer.named_ballots(POSITION, DECISION, 'final_passage')
    assert matched[1]['ballot'] == 1 and matched[-1] == 'official_title_and_tallies'
    assert not any('.pdf' in url for url in importer.client.calls)
    # A single division may also have no sequence in its filename.
    html = '<template data-js-document-results="table"><tr><td><a href="/resource/blob/1/20250529.pdf">Test</a><a href="/resource/blob/2/20250529_xls.xlsx">XLSX</a></td></tr></template>'
    assert parse_ballot_links(html.encode())[0]['date'] == STAMP


def test_title_variation_requires_a_unique_complete_result_not_fuzzy_matching():
    importer = named_importer(title='Anderer amtlicher Kurztitel')
    assert importer.named_ballots(POSITION, DECISION, 'final_passage')[-1] == 'unique_official_tallies'
    importer = named_importer(title='Anderer amtlicher Kurztitel', same_result=True)
    assert importer.named_ballots(POSITION, DECISION, 'final_passage') is None
    importer = named_importer(title='Anderer amtlicher Kurztitel', duplicate_sheet=True)
    assert importer.named_ballots(POSITION, DECISION, 'final_passage') is None


def test_exact_title_cannot_override_a_different_ballot_result():
    with pytest.raises(SourceError, match='disagrees'):
        named_importer(choice='nein').named_ballots(POSITION, DECISION, 'final_passage')


def poll(*, vote='yes', label='Erika Testperson'):
    return {'id': 5, 'label': 'Testgesetz', 'field_poll_date': str(STAMP), 'field_accepted': True,
            'field_legislature': {'label': 'Bundestag 2025 - 2029'},
            'abgeordnetenwatch_url': 'https://www.abgeordnetenwatch.de/bundestag/21/abstimmungen/test',
            'field_intro': '<p>Abstimmung zum <a href="https://dserver.bundestag.de/btd/21/000/2100001.pdf">Gesetzentwurf</a>.</p>',
            'related_data': {'votes': [{'id': 7, 'poll': {'id': 5}, 'mandate': {'id': 8, 'label': label + ' (Bundestag 2025 - 2029)'},
                                       'fraction': {'label': 'SPD (Bundestag 2025 - 2029)'}, 'vote': vote}]}}


def member(name='Erika Testperson', vote='yes', row=2):
    return MemberVote(name=name, vote=vote, group='SPD', source_row=row)


def test_secondary_poll_matching_requires_bill_term_date_and_acceptance_not_background_links():
    kwargs = {'term': 21, 'stamp': STAMP, 'numbers': {'21/1', '21/2'}, 'accepted': True}
    assert poll_matches(poll(), **kwargs)
    for change in [{'term': 20}, {'stamp': date(2025, 5, 30)}, {'numbers': {'21/2'}}, {'accepted': False}]:
        assert not poll_matches(poll(), **{**kwargs, **change})
    p = poll()
    p['field_intro'] = p['field_intro'].replace('Gesetzentwurf', 'Änderungsantrag')
    assert not poll_matches(p, **kwargs)


def test_member_check_is_exact_not_a_party_majority_or_name_similarity_check():
    assert compare_members(poll(), [member()]) == (1, 1)
    assert compare_members(poll(vote='no'), [member()]) == (1, 0)
    assert compare_members(poll(vote='no_show'), [member(vote='absent')]) == (1, 1)
    assert compare_members(poll(label='Erika Maria Testperson'), [member()]) is None
    p = poll()
    p['related_data']['votes'] *= 2
    with pytest.raises(SourceError, match='identity'):
        compare_members(p, [member()])


@pytest.mark.parametrize('choice,status', [('yes', 'matched'), ('no', 'mismatch')])
def test_cross_check_is_separately_attributed_and_preserves_official_members(choice, status):
    class Client:
        def get(self, url, params):
            data = [poll()] if url.endswith('/polls') else poll(vote=choice)
            return Download(url + '?' + urlencode(params), json.dumps({
                'meta': {'status': 'ok', 'result': {'count': 1, 'total': 1}}, 'data': data,
            }).encode(), STAMP)
    members = [member()]
    check = VoteCrossChecker(Client()).check(term=21, stamp=STAMP, numbers={'21/1'}, accepted=True, members=members)
    assert check.status == status and check.total_members == check.compared_members == 1
    assert check.source.publisher == 'abgeordnetenwatch.de' and check.source.license_note.startswith('CC0')
    assert members[0].vote == 'yes'  # The supplementary result never replaces the official ballot.


def test_secondary_failure_is_explicit_but_does_not_erase_official_ballots():
    class Client:
        def get(self, *args):
            raise SourceError('Unavailable')
    members = [member()]
    check = VoteCrossChecker(Client()).check(term=21, stamp=STAMP, numbers={'21/1'}, accepted=True, members=members)
    assert check.status == 'source_error' and check.source is None and members[0].vote == 'yes'


def test_supplementary_pagination_cannot_silently_change_its_total():
    class Client:
        def get(self, url, params):
            total = 2 if params['page'] == 0 else 3
            return Download(url, json.dumps({'meta': {'status': 'ok', 'result': {'count': 1, 'total': total}},
                                             'data': [{'id': params['page'] + 1}]}).encode(), STAMP)
    with pytest.raises(SourceError, match='changed during pagination'):
        VoteCrossChecker(Client()).polls(STAMP)


def test_malformed_secondary_api_is_a_check_failure_not_a_failed_official_import():
    class Client:
        def get(self, url, params):
            return Download(url, b'{"meta": null, "data": null}', STAMP)
    check = VoteCrossChecker(Client()).check(term=21, stamp=STAMP, numbers={'21/1'}, accepted=True,
                                           members=[member()])
    assert check.status == 'source_error' and check.source is None


@pytest.mark.parametrize('url', ['https://evil.example/api/v2/polls', 'http://www.abgeordnetenwatch.de/api/v2/polls',
                                 AW + '/polls?apiKey=secret', 'https://user:pass@www.abgeordnetenwatch.de/api/v2/polls'])
def test_supplementary_allowlist_and_credentials(url):
    with pytest.raises(SourceError):
        supplementary_url(url)


def test_supplementary_rate_limit_and_429_retry_never_use_dip_authorization(tmp_path):
    now, calls = [0.0], []

    def sleep(seconds):
        now[0] += seconds

    def handle(request):
        assert 'Authorization' not in request.headers
        calls.append(now[0])
        return httpx.Response(429, headers={'Retry-After': '3'}) if len(calls) == 2 else httpx.Response(200, json={})

    client = AbgeordnetenwatchClient(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handle)),
                                    sleep=sleep, clock=lambda: now[0])
    client.get(AW + '/polls/1')
    client.get(AW + '/polls/2')
    assert calls == [0, 2.1, 5.1]


def test_browser_challenges_are_not_followed_or_retried_for_every_law(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(303, headers={'Location': '/.enodia/challenge?redirect=example'})

    client = BundestagClient(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handle)))
    for _ in range(2):
        with pytest.raises(SourceError, match='interactive browser challenge'):
            client.get(BT + '/resource/blob/1/21012.xml')
    assert len(calls) == 1 and not list(tmp_path.iterdir())
