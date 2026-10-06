"""Separately attributed, optional member-level check against abgeordnetenwatch JSON.

This never supplies official votes or fills unnamed faction/MP positions. Polls
must explicitly link the same bill, Bundestag term and decision date. Matching
uses unique normalized names + historical factions, not current party membership.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from pipeline.models import VoteCrossCheck
from pipeline.parliament import BundestagClient, SourceError, group_key, normalized

AW = 'https://www.abgeordnetenwatch.de/api/v2'


def supplementary_url(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != 'www.abgeordnetenwatch.de'
            or parts.port not in (None, 443) or parts.username or parts.password
            or parts.fragment or not parts.path.startswith('/api/v2/')
            or re.search(r'key|token|auth|secret|password', parts.query, re.I)):
        raise SourceError('Refusing an unexpected supplementary API URL')
    return url


class AbgeordnetenwatchClient(BundestagClient):
    checked_url = staticmethod(supplementary_url)
    request_interval = 2.1  # API fair use: at most 30 requests/minute, including retries.


def poll_matches(poll, *, term, stamp, numbers, accepted):
    if (poll.get('field_poll_date') != str(stamp) or poll.get('field_accepted') is not accepted
            or not poll.get('field_legislature', {}).get('label', '').startswith('Bundestag ')):
        return False
    public = urlsplit(poll.get('abgeordnetenwatch_url', ''))
    if public.hostname != 'www.abgeordnetenwatch.de' or not public.path.startswith(f'/bundestag/{term}/abstimmungen/'):
        return False
    intro = BeautifulSoup(poll.get('field_intro', ''), 'html.parser').find('p')
    if intro is None:
        return False
    # Exact printed-paper identity in the lead paragraph's first official link;
    # later background links and related motions are not the voted-on bill.
    for link in intro.select('a[href]'):
        url = urlsplit(link['href'])
        if url.scheme != 'https' or url.hostname != 'dserver.bundestag.de':
            continue
        match = re.fullmatch(r'/btd/(\d{2})/\d{3}/\1(\d{5})\.pdf', url.path)
        return bool(match and f'{int(match[1])}/{int(match[2])}' in numbers
                    and re.search(r'Gesetzentwurf', link.get_text(), re.I))
    return False


def name_key(name):
    name = re.sub(r'\s*\([^)]*\)', '', name)
    name = re.sub(r'\b(?:Prof|Dr|h\.\s*c)\.\s*', '', name, flags=re.I)
    return normalized(name)


def compare_members(poll, members):
    rows = poll.get('related_data', {}).get('votes')
    if not isinstance(rows, list) or not rows or len(rows) >= 1000:
        raise SourceError('Supplementary related votes are missing or possibly truncated')
    ids, mandates, actual = set(), set(), {}
    choices = {'yes': 'yes', 'no': 'no', 'abstain': 'abstain', 'no_show': 'absent'}
    for row in rows:
        mandate = row.get('mandate') or {}
        fraction = row.get('fraction') or {}
        if (row.get('poll', {}).get('id') != poll['id'] or row.get('id') in ids
                or mandate.get('id') in mandates or not row.get('id') or not mandate.get('id')
                or row.get('vote') not in choices or not mandate.get('label') or not fraction.get('label')):
            raise SourceError('Invalid supplementary poll/member identity or choice')
        ids.add(row['id'])
        mandates.add(mandate['id'])
        key = (group_key(re.sub(r'\s*\(Bundestag.*$', '', fraction['label'])), name_key(mandate['label']))
        if key in actual:
            return None  # An ambiguous name is not a verified MP match.
        actual[key] = choices[row['vote']]
    expected = {(group_key(m.group), name_key(m.name)): m.vote for m in members}
    if len(expected) != len(members):
        return None
    common = set(expected) & set(actual)
    if not common or len(rows) != len(members):
        return None
    return len(common), sum(expected[key] == actual[key] for key in common)


class VoteCrossChecker:
    def __init__(self, client):
        self.client = client
        self.days = {}

    def polls(self, stamp):
        if stamp in self.days:
            return self.days[stamp]
        rows, seen, expected_total = [], set(), None
        for page in range(100):
            downloaded = self.client.get(AW + '/polls', {
                'field_poll_date': str(stamp), 'page': page, 'pager_limit': 100,
            })
            data = downloaded.json()
            result = data.get('meta', {}).get('result', {})
            items = data.get('data')
            if (data.get('meta', {}).get('status') != 'ok' or not isinstance(items, list)
                    or result.get('count') != len(items) or not isinstance(result.get('total'), int)
                    or result['total'] < 0):
                raise SourceError('Invalid supplementary poll pagination')
            expected_total = result['total'] if expected_total is None else expected_total
            if result['total'] != expected_total:
                raise SourceError('Supplementary poll inventory changed during pagination')
            for poll in items:
                if poll.get('id') in seen or not isinstance(poll.get('id'), int):
                    raise SourceError('Repeated supplementary poll page')
                seen.add(poll['id'])
                rows.append(poll)
            if len(rows) == result['total']:
                self.days[stamp] = rows
                return rows
            if not items or len(rows) > result['total']:
                raise SourceError('Incomplete supplementary poll pagination')
        raise SourceError('Supplementary poll pagination limit reached')

    def check(self, *, term, stamp, numbers, accepted, members):
        today = date.today()
        try:
            matches = [p for p in self.polls(stamp)
                       if poll_matches(p, term=term, stamp=stamp, numbers=numbers, accepted=accepted)]
            if len(matches) != 1:
                return VoteCrossCheck(status='ambiguous' if matches else 'not_found', checked_at=today,
                                      total_members=len(members),
                                      note='Kein eindeutig über Datum, Wahlperiode und Gesetzesvorlage zuordenbarer JSON-Abgleich.')
            poll_id = str(matches[0]['id'])
            downloaded = self.client.get(f'{AW}/polls/{poll_id}', {'related_data': 'votes'})
            payload = downloaded.json()
            poll = payload.get('data')
            if (payload.get('meta', {}).get('status') != 'ok' or not isinstance(poll, dict)
                    or str(poll.get('id')) != poll_id
                    or not poll_matches(poll, term=term, stamp=stamp, numbers=numbers, accepted=accepted)):
                raise SourceError('Supplementary poll detail identity changed')
            comparison = compare_members(poll, members)
            source = downloaded.source('abgeordnetenwatch: ' + poll.get('label', poll_id))
            if comparison is None:
                return VoteCrossCheck(status='unmatched', checked_at=downloaded.retrieved_at,
                                      total_members=len(members), poll_id=poll_id, source=source,
                                      note='Mitgliedsidentitäten oder historische Fraktionen nicht vollständig eindeutig abgleichbar; keine Stimmen übernommen.')
            compared, matched = comparison
            status = 'mismatch' if compared != matched else 'matched' if compared == len(members) else 'partial'
            return VoteCrossCheck(status=status, total_members=len(members),
                                  checked_at=downloaded.retrieved_at, poll_id=poll_id, source=source,
                                  compared_members=compared, matched_members=matched,
                                  note='Ergänzender, nicht amtlicher Einzelstimmenabgleich; die angezeigten Stimmen stammen weiterhin aus der Bundestags-XLSX.')
        except (SourceError, ValueError, KeyError, TypeError, AttributeError):
            # The secondary provider must not delete verified primary evidence.
            # Its failure is explicit, never called a successful match or a no-op.
            return VoteCrossCheck(status='source_error', checked_at=today, total_members=len(members),
                                  note='Ergänzende JSON-Quelle konnte nicht verlässlich geprüft werden; amtliche Stimmen unverändert.')
