"""Auditable, bounded programme-wide extraction/grouping and bidirectional all-law retrieval.

All outputs are proposals. Full law coverage does NOT imply all-pair semantic recall.
The raw criteria and prior impacts are preserved; grouping never changes reviewed statistics.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from threading import local
from typing import Literal

import snowballstemmer
from pydantic import Field

from pipeline.citations import source_quote
from pipeline.llm import Agent, InvalidModelResponse
from pipeline.matching import STOP, Judgment, Verification, criterion_text, eligible_criteria
from pipeline.models import Generation, Impact, MatchAudit, Model
from pipeline.parallel import ordered_map
from pipeline.store import digest, json_text, load_records, save_record, stable_id, write_json

logger = logging.getLogger(__name__)
VERSION = 'gruene-wide-v1'
_STEMMERS = local()


@lru_cache(maxsize=100_000)
def _stem(word):
    # Snowball stemmers mutate internal state: never share one across law workers.
    if not hasattr(_STEMMERS, 'german'):
        _STEMMERS.german = snowballstemmer.stemmer('german')
    return _STEMMERS.german.stemWord(word)


def tokens(text):
    return [_stem(word) for word in re.findall(r'[\wäöüß]+', text.casefold())
            if len(word) > 2 and word not in STOP]


def corpus_fingerprint(criteria):
    return digest(json_text([{**compact(c), 'search': criterion_text(c),
                              'program_id': c.program_id, 'party_id': c.party_id}
                             for c in sorted(criteria, key=lambda c: c.id)]))


class Equivalent(Model):
    pair_id: str
    equivalent: bool
    rationale: str = Field(min_length=15)
    left_quote: str | None
    right_quote: str | None


class Equivalences(Model):
    pairs: list[Equivalent]


class Group(Model):
    id: str
    canonical_criterion_id: str
    member_ids: list[str] = Field(min_length=1)
    status: Literal['proposed'] = 'proposed'


class DedupDecision(Model):
    left_id: str
    right_id: str
    decision: Equivalent
    generation: Generation


class PairJudgment(Judgment):
    criterion_id: str
    disposition: Literal['proposed_link', 'no_supported_link', 'missing_context']


class Judgments(Model):
    pairs: list[PairJudgment]


class PairVerification(Verification):
    criterion_id: str


class Verifications(Model):
    pairs: list[PairVerification]


class PairAudit(Model):
    criterion_id: str
    disposition: Literal['proposed_link', 'no_supported_link', 'missing_context', 'preserved_link']
    rationale: str
    input_sha256: str
    generation: list[Generation]
    impact_id: str | None = None
    judgment: PairJudgment | None = None
    verification: PairVerification | None = None


class LawAudit(Model):
    law_id: str
    analysis_sha256: str
    status: Literal['completed', 'needs_ocr']
    eligible_count: int = Field(ge=0)
    candidate_ids: list[str]
    omitted_count: int = Field(ge=0)
    pairs: list[PairAudit]


class Experiment(Model):
    schema_version: Literal['1.0'] = '1.0'
    dataset: Literal['live'] = 'live'
    program_id: str
    version: str = VERSION
    criteria_sha256: str
    law_ids: list[str]
    processed_leaves: int = Field(ge=0)
    total_leaves: int = Field(ge=0)
    groups: list[Group]
    deduplication: list[DedupDecision]
    laws: list[LawAudit] = Field(default_factory=list)
    cost: dict = Field(default_factory=dict)
    note: str = ('Proposed equivalence groups, not a verified unique-promise denominator. '
                 'All selected laws are screened using whole-law, provision-window and reverse BM25 retrieval. '
                 'Unselected pairs are unknown; recall is not measured. Missing base-law context is explicit. '
                 'No human approval, inferred votes or automatic fulfilment.')


class Index:
    """Tokenise once, use postings, avoid repeated full-corpus stemming for every pair."""
    def __init__(self, documents):
        terms = {key: Counter(tokens(text)) for key, text in documents.items()}
        average = max(1, sum(sum(t.values()) for t in terms.values()) / max(1, len(terms)))
        frequency = Counter(term for counts in terms.values() for term in counts)
        self.postings = defaultdict(list)
        for key, counts in terms.items():
            norm = 1.5 * (0.25 + 0.75 * sum(counts.values()) / average)
            for term, count in counts.items():
                idf = math.log(1 + (len(terms) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                self.postings[term].append((key, idf * count * 2.5 / (count + norm)))

    def rank(self, query):
        scores = defaultdict(float)
        for term in set(tokens(query)):
            for key, weight in self.postings.get(term, []):
                scores[key] += weight
        return sorted(scores, key=lambda key: (-scores[key], key))


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def compact(criterion):
    return {'id': criterion.id, 'title': criterion.title, 'test': criterion.test,
            'quote': criterion.reference.quote, 'deadline': str(criterion.deadline) if criterion.deadline else None}


def exact_ids(results, ids, field):
    found = [getattr(r, field) for r in results]
    if len(found) != len(ids) or set(found) != set(ids):
        raise ValueError('Response must contain each supplied ID exactly once')


def split_ask(agent, items, query):
    """Retries share the experiment budget. Failed parents are cached as subdivision hints."""
    task, data, schema, options = query(items)
    # Preserve an already validated fallback rather than pay for the invalid primary again.
    cached_review = (len(items) == 1 and hasattr(agent, 'has_cached')
                     and agent.has_cached(task, data, schema, review=True, **options))
    try:
        result, generation = agent.ask(task, data, schema, **options,
                                       review=cached_review, subdivide=len(items) > 1)
        options['validator'](result)
        return [(result, generation)]
    except InvalidModelResponse:
        if len(items) == 1:
            if cached_review:
                raise
            logger.warning('Single analysis item exhausted primary validation; bounded stronger-model '
                           'retry with unchanged source checks and the same spending ledger')
            result, generation = agent.ask(task, data, schema, **options, review=True)
            options['validator'](result)
            return [(result, generation)]
        middle = len(items) // 2
        return split_ask(agent, items[:middle], query) + split_ask(agent, items[middle:], query)


def deduplicate(criteria, agent):
    by_id = {c.id: c for c in criteria}
    index = Index({c.id: c.test for c in criteria})
    token_sets = {c.id: set(tokens(c.test)) for c in criteria}
    # Differing stated numbers/dates are never merged. Examination and implementation are
    # also distinguished in adjudication; lexical similarity alone cannot approve a merge.
    numbers = {c.id: set(re.findall(r'\d+(?:[.,]\d+)?', c.test)) for c in criteria}
    candidates = set()
    for c in criteria:
        for other_id in index.rank(c.test)[:7]:
            if other_id == c.id:
                continue
            other = by_id[other_id]
            left, right = token_sets[c.id], token_sets[other_id]
            if (c.program_id != other.program_id or c.party_id != other.party_id
                    or c.deadline != other.deadline or numbers[c.id] != numbers[other_id]
                    or len(left & right) / max(1, len(left | right)) < 0.25):
                continue
            candidates.add(tuple(sorted([c.id, other_id])))
    pairs = {stable_id('pair', ':'.join(pair)): pair for pair in sorted(candidates)}

    def query(ids):
        def check(result):
            exact_ids(result.pairs, ids, 'pair_id')
            for p in result.pairs:
                left, right = (by_id[i] for i in pairs[p.pair_id])
                if p.equivalent:
                    p.left_quote = source_quote(p.left_quote, left.reference.quote)
                    p.right_quote = source_quote(p.right_quote, right.reference.quote)
        return ('Assess each pair for STRICT semantic equivalence, not topic similarity. Both commitments '
                'must have exactly the same independently testable action, target, beneficiaries, scope, '
                'amount, deadline, conditions, legal level and commitment strength in BOTH source quotes. '
                'Examine is not implement. Broader/narrower/related or compound commitments are NOT '
                'equivalent. If any material condition is uncertain or omitted, equivalent=false. '
                'Do not repair the tests or make new promises. Cite exact substrings of both quotes for '
                'equivalence. This proposes grouping, never human approval.',
                {'pairs': [{'pair_id': i, 'left': compact(by_id[pairs[i][0]]),
                            'right': compact(by_id[pairs[i][1]])} for i in ids]}, Equivalences,
                {'validator': check, 'max_output': 7000})
    decisions = []
    for replies in ordered_map(lambda ids: split_ask(agent, ids, query), list(batches(list(pairs), 8)), workers=4):
        for response, generation in replies:
            for decision in response.pairs:
                left, right = pairs[decision.pair_id]
                decisions.append(DedupDecision(left_id=left, right_id=right,
                                                decision=decision, generation=generation))
    groups = complete_link_groups(list(by_id), decisions)
    logger.info('Grouping: %s criteria, %s checked duplicate pairs, %s proposed groups',
                len(criteria), len(decisions), len(groups))
    return groups, decisions


def complete_link_groups(ids, decisions):
    equivalent = {frozenset([d.left_id, d.right_id]) for d in decisions if d.decision.equivalent}
    members = []
    for identifier in sorted(ids):
        group = next((g for g in members if all(frozenset([identifier, i]) in equivalent for i in g)), None)
        if group is None:
            members.append([identifier])
        else:
            group.append(identifier)
    return [Group(id=stable_id('commitment', group[0]), canonical_criterion_id=group[0], member_ids=group)
            for group in members]


def retrieve_all(laws, criteria, programs):
    """Union of three searches, not the old six-candidate cap. All omissions stay explicit."""
    index = Index({c.id: criterion_text(c) for c in criteria})
    candidates = {law.id: set() for law in laws}
    eligible = {law.id: {c.id for c in eligible_criteria(law, criteria, programs)} for law in laws}
    for law in laws:
        if law.text_status != 'available':
            continue
        text = ' '.join(p.text for p in law.passages)
        candidates[law.id].update(index.rank(law.title + ' ' + text)[:12])
        # Overlapping bounded windows preserve small fragments and give omnibus provisions
        # their own searches. Do NOT truncate a million-character law to its introduction.
        for start in range(0, len(text), 6000):
            candidates[law.id].update(index.rank(law.title + ' ' + text[start:start + 8000])[:2])
        candidates[law.id] &= eligible[law.id]
    reverse = Index({law.id: law.title + ' ' + ' '.join(p.text for p in law.passages)
                     for law in laws if law.text_status == 'available'})
    for criterion in criteria:
        for law_id in reverse.rank(criterion_text(criterion))[:3]:
            if criterion.id in eligible[law_id]:
                candidates[law_id].add(criterion.id)
    return {key: sorted(value) for key, value in candidates.items()}, eligible


def legal_context(law, criteria, index, max_chars=24000):
    size, selected = 0, set()
    positions = {p.id: i for i, p in enumerate(law.passages)}
    ranked = [index.rank(c.test + ' ' + c.reference.quote) for c in criteria]
    # Round-robin each test's ranked provisions, retaining neighbours for short PDF blocks.
    for offset in range(max((len(r) for r in ranked), default=0)):
        for ranking in ranked:
            if offset >= len(ranking):
                continue
            position = positions[ranking[offset]]
            for i in range(max(0, position - 2), min(len(law.passages), position + 3)):
                if i not in selected and size + len(law.passages[i].text) <= max_chars:
                    selected.add(i)
                    size += len(law.passages[i].text)
        if size >= max_chars - 500:
            break
    # Include commencement / territorial applicability clauses if they fit; still disclose
    # partial context and require abstention when interpretation needs missing base law.
    for p in law.passages:
        i = positions[p.id]
        if i not in selected and size + len(p.text) <= max_chars and (
                re.search(r'Inkrafttreten|In-Kraft-Treten|tritt.*Kraft|Geltungsbereich', p.text, re.I)):
            selected.add(i)
            size += len(p.text)
    passages = [law.passages[i] for i in sorted(selected)]
    return passages, len(passages) < len(law.passages)


def analyze_law(law, criteria, candidates, eligible_count, agent, existing, root, corpus_hash):
    by_id = {c.id: c for c in criteria}
    signature = digest(json_text({'version': VERSION, 'law': law.model_dump(mode='json', exclude={'matching'}),
                                 'criteria': corpus_hash, 'candidates': candidates,
                                 'model': agent.model, 'review_model': agent.review_model}))
    checkpoint = agent.cache.parent / 'laws' / f'{law.id}.json'
    if checkpoint.exists():
        audit = LawAudit.model_validate_json(checkpoint.read_text())
        if audit.analysis_sha256 == signature:
            return audit
    audit = LawAudit(law_id=law.id, analysis_sha256=signature,
                    status='completed' if law.text_status == 'available' else 'needs_ocr',
                    eligible_count=eligible_count, candidate_ids=candidates,
                    omitted_count=eligible_count - len(candidates), pairs=[])
    index = Index({p.id: p.text for p in law.passages})
    pending = []
    for identifier in candidates:
        if (prior := existing.get((law.id, identifier))) is not None:
            audit.pairs.append(PairAudit(criterion_id=identifier, disposition='preserved_link',
                rationale='Previously published record preserved, not re-approved by this experiment.',
                input_sha256=signature, generation=prior.generation, impact_id=prior.id))
        else:
            pending.append(identifier)

    def query(ids):
        selected = [by_id[i] for i in ids]
        passages, partial = legal_context(law, selected, index)
        texts = {p.id: p.text for p in passages}
        def check(result):
            exact_ids(result.pairs, ids, 'criterion_id')
            for pair in result.pairs:
                if pair.supported != (pair.disposition == 'proposed_link'):
                    raise ValueError('Supported flag and disposition must agree')
                if pair.supported:
                    pair.law_quote = source_quote(pair.law_quote, texts.get(pair.law_passage_id, ''))
                    pair.criterion_quote = source_quote(pair.criterion_quote,
                                                       by_id[pair.criterion_id].reference.quote)
        return ('For EACH criterion independently judge an actual effect of this law. Topic similarity '
                'does not establish an effect. Output proposed_link only with direct source evidence and '
                'verbatim quotes from a supplied passage and that criterion quote. score -2 directly '
                'contradicts, -1 impedes, 0 demonstrably mixed, +1 supports in part, +2 directly implements '
                'the narrow test (not overall fulfilment). Return missing_context if absent base legislation, '
                'dates, exceptions or unclear scope prevent interpretation. Otherwise return no_supported_link '
                'for unrelated or unsupported effects, never proof of no impact. Be conservative and write '
                'German rationales. Do not infer votes, responsibility or complete fulfilment.',
                {'law_title': law.official_title, 'published_at': str(law.published_at),
                 'partial_law_context': partial, 'criteria': [compact(c) for c in selected],
                 'passages': [{'id': p.id, 'text': p.text} for p in passages]}, Judgments,
                {'validator': check, 'max_output': 7000})

    for batch in batches(pending, 6):
        for result, generation in split_ask(agent, batch, query):
            supported = [p for p in result.pairs if p.supported]
            verifications, review_generation = {}, None
            if supported:
                passages, partial = legal_context(law, [by_id[p.criterion_id] for p in result.pairs], index)
                # Always retain cited passages even if the batch was subdivided/selection changes.
                required = {p.law_passage_id for p in supported}
                passages = list({p.id: p for p in [*passages, *(p for p in law.passages if p.id in required)]}.values())
                def check_review(response):
                    exact_ids(response.pairs, [p.criterion_id for p in supported], 'criterion_id')
                review, review_generation = agent.ask(
                    'Challenge each proposed legal impact independently. Reject unsupported direction, '
                    'magnitude, missing conditions/exceptions/base legislation and topic-only matches. '
                    'Check BOTH supplied programme and legal evidence. This is a second-model check, '
                    'not human review or fulfilment. Write German reasons.',
                    {'proposals': [p.model_dump(mode='json') for p in supported],
                     'criteria': [compact(by_id[p.criterion_id]) for p in supported],
                     'law_title': law.official_title, 'published_at': str(law.published_at),
                     'partial_law_context': partial,
                     'passages': [{'id': p.id, 'text': p.text} for p in passages]}, Verifications,
                    # If the primary needed the stronger model, challenge with Luna instead:
                    # never misrepresent two calls to the same model as an independent model check.
                    review=generation.model != agent.review_model, validator=check_review, max_output=4000)
                check_review(review)
                verifications = {v.criterion_id: v for v in review.pairs}
            for pair in result.pairs:
                generations = [generation]
                impact_id = None
                verification = verifications.get(pair.criterion_id)
                if verification:
                    generations.append(review_generation)
                    caveats = [*pair.caveats, *verification.caveats,
                               'Automatischer Vorschlag; Auswahlkontext, keine vollständige Rechtsprüfung.']
                    if not verification.accepted:
                        caveats.append('Zweite Modellprüfung widerspricht: ' + verification.rationale)
                    impact = Impact(id=stable_id('impact', law.id + ':' + pair.criterion_id), dataset='live',
                        criterion_id=pair.criterion_id, law_id=law.id, score=pair.score, confidence=pair.confidence,
                        rationale=pair.rationale, law_passage_id=pair.law_passage_id, law_quote=pair.law_quote,
                        criterion_quote=pair.criterion_quote, caveats=caveats,
                        verification='passed' if verification.accepted else 'needs_review', generation=generations)
                    save_record(root, 'impacts', impact)
                    existing[(law.id, pair.criterion_id)] = impact
                    impact_id = impact.id
                audit.pairs.append(PairAudit(criterion_id=pair.criterion_id, disposition=pair.disposition,
                    rationale=pair.rationale, input_sha256=generation.input_sha256,
                    generation=generations, impact_id=impact_id, judgment=pair, verification=verification))
    write_json(checkpoint, audit)
    law.matching = MatchAudit(status='needs_ocr' if law.text_status != 'available' else
        ('proposed' if any(p.impact_id for p in audit.pairs) else 'no_supported_links'),
        retrieval_version=VERSION, candidate_ids=candidates, eligible_count=eligible_count,
        omitted_count=audit.omitted_count, criteria_sha256=corpus_hash, analysis_sha256=signature,
        note='Whole-law + overlapping provision windows + reverse retrieval. Unselected criteria unknown. '
             'See the programme experiment API for pair-level abstentions and context gaps. Unreviewed proposals.')
    write_json(root / 'live/laws' / f'{law.id}.json', law)
    logger.info('%s: %s candidates, %s links, %s missing-context abstentions', law.id, len(candidates),
                sum(bool(p.impact_id) for p in audit.pairs),
                sum(p.disposition == 'missing_context' for p in audit.pairs))
    return audit


def analyse(*, root: Path, agent: Agent, program_id: str):
    programs = load_records(root, 'live', 'programs')
    program = next(p for p in programs if p.id == program_id)
    if {a.leaf_id for a in program.criteria_extraction} != {leaf.id for leaf in program.leaves}:
        raise ValueError('Freeze a fully processed programme before all-law matching')
    criteria = [c for c in load_records(root, 'live', 'criteria')
                if c.program_id == program_id and c.review.status != 'rejected']
    corpus_hash = corpus_fingerprint(criteria)
    laws = sorted(load_records(root, 'live', 'laws'), key=lambda law: law.id)
    path = root / 'live/experiments' / f'{program_id}.json'
    if path.exists():
        report = Experiment.model_validate_json(path.read_text())
        if report.criteria_sha256 != corpus_hash or report.version != VERSION:
            raise ValueError('Existing frozen analysis differs: retain it and create an explicit new version')
    else:
        groups, decisions = deduplicate(criteria, agent)
        report = Experiment(program_id=program_id, criteria_sha256=corpus_hash,
            law_ids=[law.id for law in laws], processed_leaves=len(program.criteria_extraction),
            total_leaves=len(program.leaves), groups=groups, deduplication=decisions, cost=agent.summary())
        write_json(path, report)
    candidates, eligible = retrieve_all(laws, criteria, programs)
    existing = {(i.law_id, i.criterion_id): i for i in load_records(root, 'live', 'impacts')}
    # Never reuse a law/group verdict for another member automatically: all source-specific
    # conditions are checked. Grouped UI avoids duplicate counting, IDs remain independent.
    logger.info('All-law plan: %s laws, %s criteria, %s candidate pairs (not exhaustive semantic recall)',
                len(laws), len(criteria), sum(len(c) for c in candidates.values()))
    completed = {audit.law_id for audit in report.laws}
    def work(law):
        return analyze_law(law, criteria, candidates[law.id], len(eligible[law.id]), agent,
                           existing, root, corpus_hash)
    try:
        for audit in ordered_map(work, [law for law in laws if law.id not in completed], workers=4):
            report.laws.append(audit)
            report.cost = agent.summary()
            write_json(path, report)
            logger.info('Completed %s/%s laws; reported $%.4f, exposure $%.4f', len(report.laws),
                        len(laws), agent.reported_cost_usd, agent.reported_cost_usd + agent.reserved_usd)
    finally:
        report.cost = agent.summary()
        write_json(path, report)
    return {'laws': len(report.laws), 'expected_laws': len(report.law_ids), 'criteria': len(criteria),
            'proposed_groups': len(report.groups), 'candidate_pairs': sum(len(law.pairs) for law in report.laws),
            'grouping_pairs': len(report.deduplication), 'report': str(path.relative_to(root))}


def validate_experiment(report, data):
    program = data['programs'].get(report.program_id)
    if not program or report.total_leaves != len(program.leaves):
        raise ValueError('Experiment references a missing programme or wrong leaf count')
    if report.processed_leaves != len(program.criteria_extraction):
        raise ValueError('Experiment source coverage is stale')
    criteria = {c.id: c for c in data['criteria'].values()
                if c.program_id == program.id and c.review.status != 'rejected'}
    if report.criteria_sha256 != corpus_fingerprint(criteria.values()):
        raise ValueError('Experiment criterion snapshot is stale')
    all_members = [i for group in report.groups for i in group.member_ids]
    if len(all_members) != len(set(all_members)) or set(all_members) != set(criteria):
        raise ValueError('Groups must partition every eligible criterion exactly once')
    equal = set()
    for item in report.deduplication:
        if item.left_id not in criteria or item.right_id not in criteria or item.left_id == item.right_id:
            raise ValueError('Duplicate decision references unknown/same criterion')
        if item.decision.equivalent:
            for identifier, quote in [(item.left_id, item.decision.left_quote),
                                      (item.right_id, item.decision.right_quote)]:
                if not quote or len(quote) < 10 or quote not in criteria[identifier].reference.quote:
                    raise ValueError('Invalid equivalence source citation')
            equal.add(frozenset([item.left_id, item.right_id]))
    if len({g.id for g in report.groups}) != len(report.groups):
        raise ValueError('Duplicate group IDs')
    for group in report.groups:
        if group.canonical_criterion_id not in group.member_ids:
            raise ValueError('Group representative must belong to group')
        if any(frozenset(pair) not in equal for pair in combinations(group.member_ids, 2)):
            raise ValueError('Grouping requires complete-link equivalence, not transitive similarity')
    if len(set(report.law_ids)) != len(report.law_ids) or not set(report.law_ids) <= data['laws'].keys():
        raise ValueError('Experiment law scope contains absent/duplicate laws')
    if len({law.law_id for law in report.laws}) != len(report.laws):
        raise ValueError('Duplicate law audits')
    for law in report.laws:
        if law.law_id not in report.law_ids or not set(law.candidate_ids) <= criteria.keys():
            raise ValueError('Audit outside selected scope')
        found = [pair.criterion_id for pair in law.pairs]
        if len(set(found)) != len(found) or set(found) != set(law.candidate_ids):
            raise ValueError('Completed law audit must cover every candidate exactly once')
        if law.omitted_count != law.eligible_count - len(law.candidate_ids):
            raise ValueError('Inconsistent retrieval coverage')
        for pair in law.pairs:
            if pair.impact_id:
                impact = data['impacts'].get(pair.impact_id)
                if not impact or (impact.law_id, impact.criterion_id) != (law.law_id, pair.criterion_id):
                    raise ValueError('Pair audit points to missing/wrong impact')
            if pair.disposition in ('proposed_link', 'preserved_link') and not pair.impact_id:
                raise ValueError('Proposed/preserved pair needs an impact record')
