"""Official structured plenary XML, never PDF layout reconstruction.

The Open Data copy can be more complete than the XML linked by DIP. Discover its
index from Bundestag's Open Data page, validate sitting/date, and isolate chair
paragraphs by XML structure. Speeches, TOC entries and ballot tables are not
chair-announced faction positions.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from pipeline.parliament import BT, SourceError, official_url


@dataclass(frozen=True)
class ChairBlock:
    agenda: str
    index: int
    text: str
    comment_spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Transcript:
    term: int
    sitting: int
    date: str
    blocks: tuple[ChairBlock, ...]


def paragraph_text(element) -> str:
    # XML contains inline links plus editorial footnotes and speaker metadata.
    # Keep the actual paragraph text exactly, not the duplicated metadata.
    parts = [element.text or '']
    for child in element:
        if child.tag not in {'redner', 'fussnote', 'sup'} and child.get('typ') != 'druckseitennummer':
            parts.append(paragraph_text(child))
        parts.append(child.tail or '')
    return ''.join(parts)


@lru_cache(maxsize=4)
def parse_transcript(content: bytes) -> Transcript:
    try:
        root = ElementTree.fromstring(content)
        if root.tag != 'dbtplenarprotokoll':
            raise ValueError('root')
        term, sitting = int(root.attrib['wahlperiode']), int(root.attrib['sitzung-nr'])
        stamp = datetime.strptime(root.attrib['sitzung-datum'], '%d.%m.%Y').date().isoformat()
        proceedings = root.find('sitzungsverlauf')
        if proceedings is None:
            raise ValueError('proceedings')
    except (ValueError, KeyError, ElementTree.ParseError, DefusedXmlException) as error:
        raise SourceError('Invalid structured Bundestag plenary XML') from error
    blocks = []
    for agenda in proceedings.findall('tagesordnungspunkt'):
        paragraphs = []

        def flush():
            if paragraphs:
                spans, offset = [], 0
                for text, comment in paragraphs:
                    if comment:
                        spans.append((offset, offset + len(text)))
                    offset += len(text) + 1
                blocks.append(ChairBlock(agenda.get('top-id', ''), len(blocks),
                                         '\n'.join(text for text, _ in paragraphs), tuple(spans)))
                paragraphs.clear()

        for child in agenda:
            if child.tag == 'rede':
                flush()  # A speaker's promise/voting intention is not a chair's result.
            elif child.tag == 'p' and not child.get('klasse', '').startswith(('AL_', 'redner')):
                paragraphs.append((paragraph_text(child).strip(), False))
            elif child.tag == 'kommentar':
                # Retain the exact source text, but mark interjections so matching
                # and group interpretation cannot mistake them for chair answers.
                paragraphs.append((paragraph_text(child).strip(), True))
        flush()
    if not blocks:
        raise SourceError('Structured transcript has no identifiable plenary proceedings')
    return Transcript(term, sitting, stamp, tuple(blocks))


def parse_protocol_links(content: bytes, term: int) -> dict[int, str]:
    soup = BeautifulSoup(content, 'html.parser')
    table = soup.select_one('template[data-js-document-results="table"]')
    if table is None:
        raise SourceError('Bundestag Open Data protocol index format changed')
    result = {}
    for row in table.select('tr'):
        links = row.select('a[href$=".xml"]')
        if len(links) != 1:
            raise SourceError('Missing or ambiguous Open Data XML link')
        url = official_url(urljoin(BT, links[0]['href']))
        match = re.search(r'/(\d{2})(\d{3})\.xml$', url)
        if not match or int(match[1]) != term or int(match[2]) in result:
            raise SourceError('Invalid or duplicate Open Data sitting identity')
        result[int(match[2])] = url
    return result


class TranscriptProvider:
    def __init__(self, client):
        self.client = client
        self.endpoints = None
        self.indices = {}

    def _endpoints(self):
        if self.endpoints is not None:
            return self.endpoints
        soup = BeautifulSoup(self.client.get(BT + '/services/opendata').content, 'html.parser')
        result = {}
        for node in soup.select('[x-data]'):
            match = re.fullmatch(r'documents\((\{.*\})\)', node['x-data'], re.S)
            if not match:
                continue
            heading = node.find(['h2', 'h3'])
            term = re.search(r'Plenarprotokolle der (\d+)\. Wahlperiode',
                             heading.get_text(' ', strip=True) if heading else '')
            if term:
                config = json.loads(match[1])
                url = official_url(urljoin(BT, config['endpoint']))
                if not url.startswith(BT + '/ajax/filterlist/de/services/opendata/') or int(term[1]) in result:
                    raise SourceError('Ambiguous Bundestag Open Data index')
                result[int(term[1])] = url
        if not result:
            raise SourceError('Bundestag Open Data XML indices unavailable')
        self.endpoints = result
        return result

    def xml_url(self, term: int, sitting: int) -> str | None:
        endpoint = self._endpoints().get(term)
        if not endpoint:
            return None
        state = self.indices.setdefault(term, {'links': {}, 'offset': 0, 'ended': False})
        for _ in range(150):
            if sitting in state['links'] or state['ended']:
                return state['links'].get(sitting)
            rows = parse_protocol_links(self.client.get(endpoint, {'limit': 10, 'offset': state['offset']}).content, term)
            if set(rows) & set(state['links']):
                raise SourceError('Repeated Bundestag Open Data index page')
            state['links'].update(rows)
            state['offset'] += len(rows)  # The server may ignore a requested page size.
            state['ended'] = not rows
        raise SourceError('Bundestag Open Data protocol pagination limit reached')

    def get(self, position):
        fund = position['fundstelle']
        document = fund.get('dokumentnummer', '')
        if not re.fullmatch(r'\d{1,2}/\d{1,3}', document):
            raise SourceError('Unexpected DIP plenary sitting identifier')
        term, sitting = map(int, document.split('/'))
        if not fund.get('xml_url') and not fund.get('id'):
            return None
        # Never guess a dserver URL or return to PDFs. The source must actually be
        # indexed by Bundestag or explicitly linked in the DIP position.
        fallback = None
        try:
            url = self.xml_url(term, sitting)
            if url:
                downloaded = self.client.get(url)
            else:
                fallback = 'not_listed'
        except SourceError:
            fallback = 'opendata_unavailable'
        if fallback:
            url = fund.get('xml_url')
            if not url:
                if fallback == 'opendata_unavailable':
                    raise SourceError('Open Data XML unavailable and DIP provides no structured alternative')
                return None
            downloaded = self.client.get(url)
        transcript = parse_transcript(downloaded.content)
        if (transcript.term, transcript.sitting, transcript.date) != (term, sitting, position['datum']):
            raise SourceError('Structured transcript does not belong to the DIP sitting/date')
        return downloaded, transcript, fallback
