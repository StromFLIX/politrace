"""Luna screens; Sol Flex decides. No human gate and no model-voting metric.

One shared rubric, source-validated final judgments, batched by law. Screening,
final decisions and criterion-level synthesis have separate cache/provenance stages.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from pipeline.citations import source_quote
from pipeline.experiment import (
    Judgments,
    PairAudit,
    PairJudgment,
    compact,
    exact_ids,
    legal_context,
    split_ask,
)
from pipeline.llm import InvalidModelResponse
from pipeline.models import Assessment, FinalEvaluation, Impact, Model
from pipeline.store import digest, json_text, stable_id, write_json

VERSION = 'sol-final-v1'
FINAL_MODEL = 'openai/gpt-6-sol'
RUBRIC = ('Score -2 directly contradicts the narrow criterion; -1 impedes it; 0 is a demonstrably '
          'mixed effect, NEVER missing evidence; +1 supports IN PART (does NOT require full fulfilment); '
          '+2 directly implements the specific criterion. A partial sector/population measure may be +1 '
          'for a broader promise: lack of complete fulfilment alone is NOT grounds to reject it. '
          'Topic similarity, hypothetical consequences, party responsibility and votes are not legal effects. '
          'Missing necessary base legislation, exceptions or applicability requires abstention. '
          'Use only supplied sources. Write concise German reasons describing the actual legal effect '
          'and any material scope or date condition, not model disagreement or review disclaimers. ')


class FinalPair(Model):
    criterion_id: str
    outcome: Literal['accepted', 'rejected', 'missing_context']
    score: Literal[-2, -1, 0, 1, 2] | None
    rationale: str = Field(min_length=15)
    law_passage_id: str | None
    law_quote: str | None
    criterion_quote: str | None

    @model_validator(mode='after')
    def evidence(self):
        if self.outcome == 'accepted':
            if self.score is None or not self.law_passage_id or not self.law_quote or not self.criterion_quote:
                raise ValueError('Accepted final decisions need a score and two exact source quotes')
        elif self.score is not None:
            raise ValueError('Abstentions and rejected links have no score, not zero')
        return self


class FinalPairs(Model):
    pairs: list[FinalPair]


class Overall(Model):
    criterion_id: str
    status: Literal['unassessed', 'partial', 'fulfilled', 'contradicted', 'mixed']
    score: Literal[-2, -1, 0, 1, 2] | None
    rationale: str = Field(min_length=15)
    evidence_ids: list[str] = Field(min_length=1)


class Overalls(Model):
    criteria: list[Overall]


def final_ask(agent, items, query):
    """A malformed batch splits, but the FINAL evaluator never falls back to Luna."""
    if agent.review_model != FINAL_MODEL:
        raise ValueError('Final judgments require GPT-6 Sol, not a substitute evaluator')
    task, data, schema, options = query(items)
    if len(json_text({'task': task, 'data': data}).encode()) > 100_000 and len(items) > 1:
        mid = len(items) // 2
        yield from final_ask(agent, items[:mid], query)
        yield from final_ask(agent, items[mid:], query)
        return
    try:
        result, generation = agent.ask(task, data, schema, review=True,
                                       subdivide=len(items) > 1, **options)
        options['validator'](result)
        if generation.model != FINAL_MODEL:
            raise ValueError('Wrong final evaluator provenance')
        yield result, generation
    except InvalidModelResponse:
        if len(items) == 1:
            raise
        mid = len(items) // 2
        yield from final_ask(agent, items[:mid], query)
        yield from final_ask(agent, items[mid:], query)


def screen(law, criteria, agent, index):
    by_id = {c.id: c for c in criteria}
    def query(ids):
        selected = [by_id[i] for i in ids]
        passages, partial = legal_context(law, selected, index, max_chars=24000)
        texts = {p.id: p.text for p in passages}
        def check(response):
            exact_ids(response.pairs, ids, 'criterion_id')
            for pair in response.pairs:
                if pair.supported != (pair.disposition == 'proposed_link'):
                    raise ValueError('Supported flag must agree with disposition')
                if pair.supported:
                    pair.law_quote = source_quote(pair.law_quote, texts.get(pair.law_passage_id, ''))
                    pair.criterion_quote = source_quote(pair.criterion_quote,
                                                       by_id[pair.criterion_id].reference.quote)
                elif pair.score is not None:
                    raise ValueError('No supported effect means no score')
        return (VERSION + ': Screen EACH criterion independently. ' + RUBRIC +
                'Return proposed_link with exact evidence, missing_context when interpretation requires '
                'unavailable sources, otherwise no_supported_link. One short rationale per item.',
                {'law_title': law.official_title, 'published_at': str(law.published_at),
                 'partial_law_context': partial, 'criteria': [compact(c) for c in selected],
                 'passages': [{'id': p.id, 'text': p.text} for p in passages]}, Judgments,
                {'validator': check, 'max_output': 12000, 'stage': 'screening'})
    for result, generation in split_ask(agent, list(by_id), query):
        for pair in result.pairs:
            yield PairAudit(criterion_id=pair.criterion_id, disposition=pair.disposition,
                rationale=pair.rationale, judgment=pair, input_sha256=generation.input_sha256,
                generation=[generation])


def decide(law, criteria, drafts, agent, index):
    by_id = {c.id: c for c in criteria}
    def query(ids):
        passages, partial = legal_context(law, [by_id[i] for i in ids], index, max_chars=32000)
        required = {drafts[i].judgment.law_passage_id for i in ids if drafts[i].judgment}
        passages = list({p.id: p for p in [*passages, *(p for p in law.passages if p.id in required)]}.values())
        texts = {p.id: p.text for p in passages}
        def check(response):
            exact_ids(response.pairs, ids, 'criterion_id')
            for pair in response.pairs:
                if pair.outcome == 'accepted':
                    pair.law_quote = source_quote(pair.law_quote, texts.get(pair.law_passage_id, ''))
                    pair.criterion_quote = source_quote(pair.criterion_quote,
                                                       by_id[pair.criterion_id].reference.quote)
        return (VERSION + ': You are the FINAL evaluator, not a yes/no challenger. ' + RUBRIC +
                'For every draft independently decide accepted, rejected, or missing_context. '
                'You may correct direction, magnitude, quoted provision and explanation. Your decision '
                'replaces the draft and is automatically published and used for criterion assessment. '
                'Judge the evidence rather than whether you agree with the earlier model. Do not produce '
                'review warnings or model-disagreement commentary.',
                {'law_title': law.official_title, 'published_at': str(law.published_at),
                 'partial_law_context': partial, 'criteria': [compact(by_id[i]) for i in ids],
                 'drafts': [drafts[i].judgment.model_dump(mode='json') for i in ids],
                 'passages': [{'id': p.id, 'text': p.text} for p in passages]}, FinalPairs,
                {'validator': check, 'max_output': 12000, 'stage': 'final_links'})
    for response, generation in final_ask(agent, list(drafts), query):
        for pair in response.pairs:
            yield pair, generation


def apply_decision(root, law, criterion, draft, final, generation, existing):
    """Keep record IDs; corrections win. Rejected historical links remain only in the audit/API."""
    key = (law.id, criterion.id)
    prior = existing.get(key)
    if prior and prior.review.status != 'proposed':
        return PairAudit(criterion_id=criterion.id, disposition='preserved_link',
            rationale='Gespeicherte Korrektur beibehalten.', impact_id=prior.id,
            input_sha256=generation.input_sha256, generation=prior.generation)
    accepted = final.outcome == 'accepted'
    generations = [*draft.generation[:1], generation]
    evaluation = FinalEvaluation(status=final.outcome, input_sha256=generation.input_sha256,
                                 decided_at=date.today(),
                                 previous_sha256=digest(json_text(prior)) if prior else None)
    impact = None
    if accepted:
        impact = Impact(id=prior.id if prior else stable_id('impact', law.id + ':' + criterion.id),
            dataset='live', criterion_id=criterion.id, law_id=law.id, score=final.score,
            confidence=draft.judgment.confidence if draft.judgment else 0,
            rationale=final.rationale, law_passage_id=final.law_passage_id,
            law_quote=final.law_quote, criterion_quote=final.criterion_quote,
            caveats=[], verification='passed', evaluation=evaluation, generation=generations,
            **({'review': prior.review} if prior else {}))
    elif prior:
        impact = prior.model_copy(update={'evaluation': evaluation, 'generation': generations})
    if impact:
        write_json(root / 'live/impacts' / f'{impact.id}.json', impact)
        existing[key] = impact
    # Never leave a stale overall score visible while its evidence has changed.
    if criterion.assessment.method == 'agent':
        criterion.assessment = Assessment()
        write_json(root / 'live/criteria' / f'{criterion.id}.json', criterion)
    return PairAudit(criterion_id=criterion.id,
        disposition='proposed_link' if accepted else 'missing_context' if final.outcome == 'missing_context'
                    else 'no_supported_link',
        rationale=final.rationale, input_sha256=generation.input_sha256, generation=generations,
        impact_id=impact.id if impact else None,
        judgment=PairJudgment(criterion_id=criterion.id, supported=accepted, score=final.score,
            confidence=draft.judgment.confidence if draft.judgment else 0,
            rationale=final.rationale, law_passage_id=final.law_passage_id, law_quote=final.law_quote,
            criterion_quote=final.criterion_quote, caveats=[],
            disposition='proposed_link' if accepted else 'missing_context' if final.outcome == 'missing_context'
                        else 'no_supported_link'))


def assessment_context(criterion, impacts, laws):
    accepted = [i for i in impacts if i.criterion_id == criterion.id and i.review.status != 'rejected'
                and i.evaluation and i.evaluation.status == 'accepted']
    accepted.sort(key=lambda i: (laws[i.law_id].published_at, i.law_id, i.id))
    return {'criterion': compact(criterion), 'effects': [
        {'id': i.id, 'law_id': i.law_id, 'law_title': laws[i.law_id].official_title,
         'published_at': str(laws[i.law_id].published_at), 'score': i.score,
         'effect': i.rationale, 'law_quote': i.law_quote, 'criterion_quote': i.criterion_quote,
         'evaluation': i.evaluation.model_dump(mode='json')} for i in accepted]}


def assessment_signature(context):
    return digest(json_text({'version': VERSION, **context}))


def assess(criteria, impacts, laws, agent):
    contexts = {c.id: assessment_context(c, impacts, laws) for c in criteria}
    def query(ids):
        def check(response):
            exact_ids(response.criteria, ids, 'criterion_id')
            for value in response.criteria:
                allowed = {i['id'] for i in contexts[value.criterion_id]['effects']}
                if (not value.evidence_ids or len(set(value.evidence_ids)) != len(value.evidence_ids)
                        or not set(value.evidence_ids) <= allowed):
                    raise ValueError('Overall assessment must cite this criterion\'s accepted evidence only')
                expected = {'fulfilled': {2}, 'partial': {1}, 'contradicted': {-2, -1},
                            'mixed': {0}, 'unassessed': {None}}
                if value.score not in expected[value.status]:
                    raise ValueError('Overall status and signed score must agree')
        return (VERSION + ': Assess the OVERALL STATUTORY POSITION of each criterion using all its '
                'accepted legal effects in chronological order. ' + RUBRIC +
                'Do not sum per-law scores. Consider reversals, conditions, scope and dates. '
                'fulfilled/2 requires statutory implementation of the exact narrow test, not real-world '
                'outcomes or an inferred government achievement. partial/1 means limited statutory support; '
                'contradicted/-1 or -2 means impeded or contradicted; mixed/0 is evidenced opposing effects; '
                'unassessed/null if supplied evidence cannot establish the overall legal position. '
                'Cite the IDs that actually support your final assessment. You make the final automatic '
                'assessment; no human approval or model disagreement commentary.',
                {'as_of': str(date.today()), 'criteria': [contexts[i] for i in ids]}, Overalls,
                {'validator': check, 'max_output': 8000, 'stage': 'overall_assessments'})
    for response, generation in final_ask(agent, list(contexts), query):
        for value in response.criteria:
            yield value.criterion_id, Assessment(status=value.status, rationale=value.rationale,
                method='agent', score=value.score, assessed_at=date.today(), evidence_ids=value.evidence_ids,
                generation=generation, input_sha256=assessment_signature(contexts[value.criterion_id]))
