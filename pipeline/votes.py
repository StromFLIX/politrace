"""Independent, resumable Bundestag voting enrichment. No model calls or human-review fiction."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from pipeline.models import LawVotingCoverage, Vote, VoteEvidence, VotingCoverage
from pipeline.parliament import (
    BT,
    DIP,
    BundestagClient,
    SourceError,
    ballot_inventory,
    document_numbers,
    group_tallies,
    normalized,
    parse_ballots,
    roll_call_detail,
    roll_call_inventory,
)
from pipeline.store import digest, json_text, load_records, write_json
from pipeline.transcripts import TranscriptProvider
from pipeline.vote_crosscheck import AbgeordnetenwatchClient, VoteCrossChecker
from pipeline.vote_protocols import (
    STAGES,
    decision_passage,
    decision_scope,
    group_positions,
    law_decisions,
)


def publication_matches(law, entry: dict) -> bool:
    match = re.fullmatch(r'bgbl-([12])-(\d{4})-(\d+[a-z]?)', law.id)
    if not match:
        return False
    part, year, number = match.groups()
    eli = f'/eli/bund/BGBl_{part}/{year}/{number}'
    if re.search(re.escape(eli) + r'(?:/|$)', entry.get('pdf_url', '')):
        return entry.get('verkuendungsdatum') == str(law.published_at)
    return (entry.get('jahrgang') == year and entry.get('heftnummer') == number
            and entry.get('verkuendungsblatt_kuerzel') == ('BGBl I' if part == '1' else 'BGBl II')
            and entry.get('verkuendungsdatum') == str(law.published_at))


def resolve_procedure(client, law):
    match = re.fullmatch(r'bgbl-([12])-(\d{4})-(\d+[a-z]?)', law.id)
    candidates = []
    if match:
        part, year, number = match.groups()
        found = client.listing('vorgang', {'f.vorgangstyp': 'Gesetzgebung',
            'f.verkuendung_fundstelle': f'BGBl {"I" if part == "1" else "II"} {year}, {number}'})
        candidates = [item for item in found if item.get('vorgangstyp') == 'Gesetzgebung'
                      and any(publication_matches(law, entry) for entry in item.get('verkuendung', []))]
    if candidates:
        return candidates, 'official_reference'
    found = client.listing('vorgang', {'f.vorgangstyp': 'Gesetzgebung', 'f.titel': law.official_title})
    # Today's promulgation may not yet be indexed by DIP. An exact unique title is
    # explicitly provisional and never enters programme-comparison statistics.
    candidates = [item for item in found if item.get('vorgangstyp') == 'Gesetzgebung'
                  and normalized(item['titel']) == normalized(law.official_title)
                  and item.get('beratungsstand') not in {
                      'Erledigt durch Ablauf der Wahlperiode', 'Zurückgezogen', 'Abgelehnt',
                  }
                  and not item.get('verkuendung')]
    return candidates, 'exact_title'


def whole_law_roll_call(entry: dict, numbers: set[str]) -> bool:
    text = entry['motion']
    if not numbers or not numbers <= document_numbers(text) or 'Gesetzentwurf' not in text:
        return False
    return not re.search(r'Entschließungsantrag|Änderungsantrag|Artikel\s+\w|\bArt\.\s*\d|'
                         r'Einzel(?:plan|abstimmung)|\bZiffer\s+\d|\bTeile\b|übrige', entry['title'] + ' ' + text, re.I)


class VoteImporter:
    def __init__(self, client, cross_checker=None):
        self.client, self.cross_checker = client, cross_checker
        self.transcripts = TranscriptProvider(client)
        self.roll_calls = self.ballot_links = None
        self.inventory_since = None
        self.details = {}

    def named_ballots(self, position, decision, stage):
        if (decision.get('abstimmungsart') != 'Namentliche Abstimmung'
                or stage not in ('final_passage', 'second_reading') or decision_scope(decision) != 'whole_law'):
            return None
        stamp = date.fromisoformat(position['datum'])
        if self.inventory_since is None or stamp < self.inventory_since:
            self.roll_calls = roll_call_inventory(self.client, stamp)
            self.ballot_links = ballot_inventory(self.client, stamp)
            self.inventory_since = stamp
        numbers = document_numbers(decision.get('dokumentnummer', ''))
        dated_entries = [row for row in self.roll_calls if row['date'] == stamp]
        entries = []
        for row in dated_entries:
            if not whole_law_roll_call(row, numbers):
                continue
            if row['id'] not in self.details:
                downloaded = self.client.get(BT + '/parlament/plenum/abstimmung/abstimmung', {'id': row['id']})
                self.details[row['id']] = roll_call_detail(downloaded, row)
            entries.append(self.details[row['id']])
        # Confirm full headings and motion references, never title similarity. This
        # also separates bills sharing a committee recommendation. Unrelated detail
        # pages aren't required when the complete dated index already rules them out.
        matches = [entry for entry in entries if whole_law_roll_call(entry, numbers)]
        if len(matches) != 1:
            return None
        entry = matches[0]
        document = position['fundstelle']['dokumentnummer']
        if not re.fullmatch(r'\d+/\d+', document):
            raise SourceError('Unexpected roll-call sitting identifier')
        term, sitting = map(int, document.split('/'))
        dated = [sheet for sheet in self.ballot_links if sheet['date'] == stamp]
        # The XLSX contains term, sitting and ballot number. Match all five choices
        # for EVERY faction against the official structured result, not just totals.
        # Prefer exact titles PLUS all faction counts. Otherwise, overall counts must
        # be unique in the complete day's official index, and the full faction result
        # must select exactly one dated workbook. Collisions stay unknown.
        titled_sheets = [s for s in dated if normalized(s['title']) == normalized(entry['title'])]
        unique_result = sum(e['totals'] == entry['totals'] for e in dated_entries) == 1
        if not titled_sheets and not unique_result:
            return None
        matches = []
        for candidate in titled_sheets or dated:
            titled = bool(titled_sheets)
            sheet = self.client.get(candidate['url'])
            members, groups, ballot_number = parse_ballots(sheet.content, term=term, sitting=sitting)
            if group_tallies(groups) != entry['group_totals']:
                if titled:
                    raise SourceError('Officially titled workbook disagrees with official faction results')
                continue
            matches.append(({**candidate, 'ballot': ballot_number}, sheet, members, groups,
                            'official_title_and_tallies' if titled else 'unique_official_tallies'))
        if len(matches) != 1:
            return None
        return entry, *matches[0]

    def record(self, law, procedure, positions, position, index, decision, stage, match):
        pd = self.client.get(f'{DIP}/vorgang/{procedure["id"]}')
        vd = self.client.get(f'{DIP}/vorgangsposition/{position["id"]}')
        fresh = vd.json()
        if (fresh.get('vorgang_id') != procedure['id'] or fresh.get('datum') != position['datum']
                or fresh.get('beschlussfassung') != position.get('beschlussfassung')):
            raise SourceError('DIP decision changed during import')
        if match == 'official_reference' and not any(publication_matches(law, v) for v in pd.json().get('verkuendung', [])):
            raise SourceError('DIP publication identity changed during import')
        evidence = VoteEvidence(procedure_id=procedure['id'], position_id=position['id'],
            decision_index=index, law_match=match, procedure_source=pd.source(procedure['titel']),
            position_source=vd.source(position['vorgangsposition']), protocol_page=decision.get('seite'),
            document_numbers=sorted(document_numbers(decision.get('dokumentnummer', ''))),
            text=json_text(fresh), quote=decision['beschlusstenor'])
        finals = [p['datum'] for p, _, _, s in law_decisions(positions, law.published_at) if s == 'final_passage']
        mediation = any((p.get('zuordnung') == 'VA' or 'Vermittlung' in p.get('vorgangsposition', ''))
                        and p['datum'] >= position['datum'] for p in positions)
        scope = decision_scope(decision)
        comparable = (match == 'official_reference' and stage == 'final_passage' and scope == 'whole_law'
                      and position['datum'] == max(finals, default='') and not mediation
                      and decision['beschlusstenor'].startswith('Annahme'))
        record = Vote(id=f'vote-{law.id}-{position["id"]}-{index}', dataset='live', law_id=law.id,
            date=position['datum'], motion=f'{STAGES[stage]}: {procedure["titel"]}', stage=stage,
            decision=decision['beschlusstenor'] + (f' ({decision["abstimm_ergebnis_bemerkung"]})'
                if scope == 'partial_law' and decision.get('abstimm_ergebnis_bemerkung') else ''),
            scope=scope, compares_to_law=comparable, type='plenary_record',
            source=vd.source(position['vorgangsposition']), evidence=evidence,
            note='Beschluss belegt. Fraktions- oder Einzelstimmen sind noch nicht eindeutig erschlossen.')
        named = self.named_ballots(position, decision, stage)
        if named:
            entry, candidate, sheet, members, groups, ballot_match = named
            record.type, record.members, record.groups = 'roll_call', members, groups
            record.source = sheet.source(entry['title'])
            evidence.roll_call_id = entry['id']
            evidence.roll_call_source = entry['download'].source(entry['title'])
            evidence.ballot_index_source = candidate['index_source']
            evidence.ballot_number, evidence.ballot_match = candidate['ballot'], ballot_match
            evidence.position_status = 'roll_call_found'
            # Quote the actual official motion, not synthetic spreadsheet prose.
            # Individual-ballot provenance is each original XLSX source row.
            evidence.text = entry['title'] + '\n' + entry['motion']
            evidence.quote = entry['motion']
            record.note = 'Einzelstimmen und Fraktionssummen mit den amtlichen Ergebnissen abgeglichen. Fraktionszugehörigkeit zum Abstimmungszeitpunkt.'
            if self.cross_checker and stage == 'final_passage':
                evidence.cross_check = self.cross_checker.check(
                    term=int(position['fundstelle']['dokumentnummer'].split('/')[0]), stamp=record.date,
                    numbers=set(evidence.document_numbers), accepted=decision['beschlusstenor'].startswith('Annahme'),
                    members=members)
                if evidence.cross_check.status == 'mismatch':
                    record.compares_to_law = False
                    record.note += ' Der ergänzende JSON-Abgleich weicht ab; bis zur Klärung kein Programmvergleich.'
        elif decision.get('abstimmungsart') == 'Namentliche Abstimmung':
            evidence.position_status = 'roll_call_unmatched'
        elif scope == 'whole_law':
            protocol = self.transcripts.get(position)
            evidence.position_status = 'no_structured_transcript'
            if protocol:
                downloaded, transcript, fallback = protocol
                evidence.protocol_fallback = fallback
                evidence.protocol_source = downloaded.source(f'Plenarprotokoll {position["fundstelle"]["dokumentnummer"]} (XML)')
                evidence.protocol_format = 'xml'
                candidates = [(block, passage) for block in transcript.blocks
                              if (passage := decision_passage(block.text, set(evidence.document_numbers), stage,
                                                              block.comment_spans))]
                evidence.position_status = 'ambiguous_passage' if candidates else 'passage_not_found'
                if len(candidates) == 1:
                    block, (quote, start, end) = candidates[0]
                    evidence.text, evidence.quote = block.text, quote
                    evidence.protocol_agenda, evidence.protocol_block = block.agenda, block.index
                    evidence.protocol_comment_spans = list(block.comment_spans)
                    comments = [(max(a, start) - start, min(b, end) - start) for a, b in block.comment_spans
                                if a < end and b > start]
                    record.groups = group_positions(quote, comments)
                    evidence.position_status = 'groups_found' if record.groups else 'no_explicit_groups'
                    record.type = 'group_record' if record.groups else 'plenary_record'
                    record.source = evidence.protocol_source
                    if record.groups:
                        record.note = 'Nur ausdrücklich im amtlichen XML-Protokoll genannte Fraktionspositionen. Keine Einzelstimmen oder Stimmenzahlen; nicht genannte Gruppen bleiben unbekannt.'
        if scope == 'partial_law':
            evidence.position_status = 'partial_decision'
            record.note = 'Teilabstimmung, nicht über das ganze Gesetz. Keine Übertragung auf die Schlussabstimmung oder den Programmvergleich.'
        if match == 'exact_title':
            record.note += ' Vorläufige Zuordnung über den exakten Titel; die BGBl-Verknüpfung in DIP fehlt noch. Kein Programmvergleich.'
        record = Vote.model_validate(record.model_dump())
        record.import_sha256 = import_fingerprint(record)
        return record


def import_fingerprint(record: Vote) -> str:
    return digest(json_text(record.model_dump(mode='json', exclude={'import_sha256'})))


def save_import(root: Path, record: Vote) -> str:
    path = root / 'live/votes' / f'{record.id}.json'
    if path.exists():
        raw = json.loads(path.read_text())
        previous = Vote.model_validate(raw)
        # Hash the saved representation, not newly introduced model defaults. Schema
        # additions must not mistake every untouched import for a citizen correction.
        saved_fingerprint = digest(json_text({key: value for key, value in raw.items() if key != 'import_sha256'}))
        if previous.review.status != 'proposed' or previous.import_sha256 != saved_fingerprint:
            return 'preserved'  # Including unsigned citizen edits, never silently overwritten.
        prior_check = previous.evidence.cross_check if previous.evidence else None
        fresh_check = record.evidence.cross_check if record.evidence else None
        if (prior_check and prior_check.status == 'mismatch' and record.evidence
                and previous.members == record.members
                and (not fresh_check or fresh_check.status not in ('matched', 'mismatch'))):
            # Skipping the secondary API, an outage or an incomplete name match is
            # not a resolution of a known disagreement for these same ballots.
            # Keep the dated conflicting source until a complete match or an
            # explicit editorial correction resolves it.
            record.evidence.cross_check = prior_check.model_copy(deep=True)
            record.compares_to_law = False
            warning = 'Ein früherer ergänzender JSON-Abgleich bleibt ungeklärt; kein Programmvergleich.'
            if warning not in record.note:
                record.note = f'{record.note} {warning}'.strip()
            record.import_sha256 = import_fingerprint(record)
        if previous.model_dump() == record.model_dump():
            return 'unchanged'
    write_json(path, record)
    return 'written'


def ingest_votes(root: Path, *, cache: Path, law_ids=None, since=None, limit=None, refresh=False,
                 client=None, crosscheck=True, crosscheck_client=None):
    laws = sorted(load_records(root, 'live', 'laws'), key=lambda law: (law.published_at, law.id), reverse=True)
    if law_ids and not set(law_ids) <= {law.id for law in laws}:
        raise ValueError('Unknown law ID in voting import scope')
    laws = [law for law in laws if (not law_ids or law.id in law_ids) and (not since or law.published_at >= since)]
    if limit is not None:
        if limit < 1:
            raise ValueError('Voting import limit must be positive')
        laws = laws[:limit]
    coverage_path = root / 'live/voting/coverage.json'
    coverage = VotingCoverage.model_validate_json(coverage_path.read_text()) if coverage_path.exists() else VotingCoverage(items=[])
    by_law = {item.law_id: item for item in coverage.items}
    own_client = client is None
    client = client or BundestagClient(cache, refresh=refresh)
    own_crosscheck = crosscheck and crosscheck_client is None
    if own_crosscheck:
        crosscheck_client = AbgeordnetenwatchClient(cache, refresh=refresh)
    checker = VoteCrossChecker(crosscheck_client) if crosscheck and crosscheck_client else None
    importer, failed, written = VoteImporter(client, checker), [], 0
    try:
        for law in laws:
            row = LawVotingCoverage(law_id=law.id, checked_at=date.today(), status='not_found',
                reason='Noch kein eindeutig zugeordneter Bundestagsbeschluss gefunden. Das ist kein Beleg für eine fehlende Abstimmung.')
            try:
                procedures, match = resolve_procedure(client, law)
                row.procedure_ids = [p['id'] for p in procedures]
                if len(procedures) > 1:
                    row.status, row.reason = 'ambiguous', 'Mehrere passende DIP-Vorgänge; keine automatische Zuordnung von Stimmen.'
                elif len(procedures) == 1:
                    procedure = procedures[0]
                    positions = client.listing('vorgangsposition', {'f.vorgang': procedure['id']})
                    imported = []
                    for position, index, decision, stage in law_decisions(positions, law.published_at):
                        record = importer.record(law, procedure, positions, position, index, decision, stage, match)
                        written += save_import(root, record) == 'written'
                        actual = Vote.model_validate_json((root / 'live/votes' / f'{record.id}.json').read_text())
                        imported.append(actual)
                    row.vote_ids = [record.id for record in imported]
                    if imported:
                        has_positions = any(v.type != 'plenary_record' and v.review.status != 'rejected'
                                            and (v.review.status == 'reviewed' or v.evidence) for v in imported)
                        row.status = 'recorded' if has_positions else 'decision_only'
                        row.reason = ('Amtliche Abstimmungen erschlossen; die Belegart ist je Abstimmung ausgewiesen.' if has_positions else
                                      'Amtlicher Beschluss gefunden; Fraktions- oder Einzelstimmen noch nicht eindeutig zugeordnet.')
                        if match == 'exact_title':
                            row.reason += ' Titelzuordnung ist vorläufig, bis DIP die BGBl-Fundstelle verknüpft.'
                    else:
                        row.reason = 'DIP-Vorgang gefunden, aber noch kein eindeutig erschlossener Gesetzesbeschluss des Bundestags.'
                prior = by_law.get(law.id)
                if prior and set(prior.vote_ids) - set(row.vote_ids):
                    row.status, row.reason = 'source_changed', 'Amtliche Zuordnung geändert; frühere Belege bleiben erhalten und müssen abgeglichen werden.'
                    row.vote_ids = sorted(set(prior.vote_ids) | set(row.vote_ids))
                    failed.append(law.id)
            except Exception as error:
                row.status = 'source_error'
                row.reason = str(error) if isinstance(error, SourceError) else f'Voting source validation failed ({type(error).__name__})'
                row.vote_ids = [v.id for v in load_records(root, 'live', 'votes') if v.law_id == law.id]
                failed.append(law.id)
            by_law[law.id] = row
            coverage.items = sorted(by_law.values(), key=lambda item: item.law_id)
            write_json(coverage_path, coverage)
    finally:
        if own_client:
            client.close()
        if own_crosscheck:
            crosscheck_client.close()
    if failed:
        raise SourceError(f'Voting enrichment incomplete for {len(failed)} laws; see data/live/voting/coverage.json. Successful records retained.')
    return {'checked': len(laws), 'written': written,
            'with_positions': sum(by_law[law.id].status == 'recorded' for law in laws),
            'decision_only': sum(by_law[law.id].status == 'decision_only' for law in laws)}
