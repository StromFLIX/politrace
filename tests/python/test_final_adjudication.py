import json
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from pipeline.adjudication import (
    FINAL_MODEL,
    FinalPair,
    FinalPairs,
    Overall,
    Overalls,
    apply_decision,
    decide,
    final_ask,
)
from pipeline.experiment import Index, Judgments, PairAudit, PairJudgment, complete_link_groups
from pipeline.final_queue import LEGACY_VERSION, load_state, migrate_budget, pair_signature, run_final_slice
from pipeline.llm import Agent, InvalidModelResponse, ProviderError
from pipeline.models import Generation, Impact, LeafExtraction, Review
from pipeline.store import load_records, validate_store, write_json


def gen(model):
    return Generation(model=model, prompt_version='test-final', input_sha256='f' * 64)


def draft(criterion, law):
    judgment = PairJudgment(criterion_id=criterion.id, disposition='proposed_link', supported=True,
        score=2, confidence=.8, rationale='Die neue Vorschrift unterstützt die konkrete Zusage.',
        law_passage_id=law.passages[0].id, law_quote=law.passages[0].text,
        criterion_quote=criterion.reference.quote, caveats=[])
    return PairAudit(criterion_id=criterion.id, disposition='proposed_link', rationale=judgment.rationale,
        input_sha256='a' * 64, generation=[gen('openai/gpt-6-luna')], judgment=judgment)


class Stub:
    model = 'openai/gpt-6-luna'
    review_model = FINAL_MODEL
    flex = True
    def __init__(self, cache, law, criterion):
        self.cache, self.law, self.criterion = cache, law, criterion
        self.calls = []
        self.reject = False
        self.fail = False
    def summary(self):
        return {'model': self.model, 'review_model': self.review_model, 'reported_cost_usd': 0,
                'budget_exposure_usd': 0, 'calls': len(self.calls), 'max_usd': 25}
    def ask(self, task, data, schema, **options):
        self.calls.append((schema, options.get('review', False), data))
        if self.fail:
            raise ProviderError(402, {})
        if schema == Judgments:
            result = Judgments(pairs=[draft(self.criterion.model_copy(update={'id': c['id']}), self.law).judgment
                                     for c in data['criteria']])
        elif schema == FinalPairs:
            assert options['review'] is True
            assert 'supports IN PART' in task
            result = FinalPairs(pairs=[FinalPair(criterion_id=c['id'], outcome='rejected' if self.reject else 'accepted',
                score=None if self.reject else 1, rationale='Die Regelung unterstützt diese Zusage nur teilweise.',
                law_passage_id=self.law.passages[0].id, law_quote=self.law.passages[0].text,
                criterion_quote=self.criterion.reference.quote) for c in data['criteria']])
        elif schema == Overalls:
            assert options['review'] is True
            result = Overalls(criteria=[Overall(criterion_id=c['criterion']['id'], status='partial', score=1,
                rationale='Der gesetzliche Stand setzt einen Teil dieser Zusage um.',
                evidence_ids=[e['id'] for e in c['effects']]) for c in data['criteria']])
        else:
            raise AssertionError(schema)
        options['validator'](result)
        return result, gen(self.review_model if options.get('review') else self.model)


def ready(corpus, monkeypatch):
    root, program, criterion, law = corpus
    program.review = Review()
    criterion.review = Review()
    program.criteria_extraction = [LeafExtraction(leaf_id=leaf.id,
        criterion_ids=[criterion.id] if leaf.id == criterion.leaf_id else [],
        abstention_reason=None if leaf.id == criterion.leaf_id else 'Keine konkrete Zusage.',
        generation=gen('openai/gpt-6-luna')) for leaf in program.leaves]
    write_json(root / 'live/programs' / f'{program.id}.json', program)
    write_json(root / 'live/criteria' / f'{criterion.id}.json', criterion)
    monkeypatch.setattr('pipeline.final_queue.deduplicate', lambda items, _: (complete_link_groups([c.id for c in items], []), []))
    return root, program, criterion, law


def test_full_automatic_path_sol_changes_score_and_overall_without_humans(corpus, tmp_path, monkeypatch):
    root, program, criterion, law = ready(corpus, monkeypatch)
    agent = Stub(tmp_path / 'cache/llm', law, criterion)
    result = run_final_slice(root, agent, workers=2, seconds=30)
    assert result['status'] == 'completed'
    impact = load_records(root, 'live', 'impacts')[0]
    assert impact.score == 1  # Luna proposed 2, Sol is authoritative.
    assert impact.evaluation.status == 'accepted'
    assert impact.review.status == 'proposed'  # NOT a forged human approval.
    assert impact.verification == 'passed' and not impact.caveats
    changed = load_records(root, 'live', 'criteria')[0]
    assert changed.assessment.method == 'agent' and changed.assessment.status == 'partial'
    assert changed.assessment.reviewer is None
    assert changed.assessment.evidence_ids == [impact.id]
    validate_store(root)
    count = len(agent.calls)
    assert run_final_slice(root, agent, workers=2, seconds=30)['status'] == 'completed'
    assert len(agent.calls) == count


def test_rejection_produces_no_impact_or_score(corpus, tmp_path, monkeypatch):
    root, _, criterion, law = ready(corpus, monkeypatch)
    agent = Stub(tmp_path / 'cache/llm', law, criterion)
    agent.reject = True
    result = run_final_slice(root, agent, seconds=30)
    assert result['status'] == 'completed'
    assert load_records(root, 'live', 'impacts') == []
    assert load_records(root, 'live', 'criteria')[0].assessment.status == 'unassessed'
    state = json.loads((agent.cache.parent / 'queue.json').read_text())
    audit = next(iter(state['pairs'].values()))['audit']
    assert audit['disposition'] == 'no_supported_link' and audit['judgment']['score'] is None


def test_final_context_batches_multiple_programmes_with_shared_law(corpus, tmp_path):
    _, _, criterion, law = corpus
    other = criterion.model_copy(update={'id': 'other-criterion', 'program_id': 'other-program'})
    agent = Stub(tmp_path / 'llm', law, criterion)
    result = list(decide(law, [criterion, other], {c.id: draft(c, law) for c in (criterion, other)},
                         agent, Index({p.id: p.text for p in law.passages})))
    assert len(result) == 2 and len(agent.calls) == 1
    assert agent.calls[0][1] is True
    assert len(agent.calls[0][2]['passages']) == 1
    assert len(agent.calls[0][2]['criteria']) == 2


def test_invalid_final_batches_never_fallback_to_luna(corpus, tmp_path):
    _, _, criterion, law = corpus
    agent = Stub(tmp_path / 'llm', law, criterion)
    original = agent.ask
    routes = []
    def ask(task, data, schema, **opts):
        routes.append(opts.get('review'))
        if len(data['criteria']) > 1:
            raise InvalidModelResponse('split')
        return original(task, data, schema, **opts)
    agent.ask = ask
    other = criterion.model_copy(update={'id': 'other-criterion'})
    result = list(decide(law, [criterion, other], {c.id: draft(c, law) for c in (criterion, other)},
                         agent, Index({p.id: p.text for p in law.passages})))
    assert len(result) == 2 and routes == [True, True, True]


def test_final_quote_contract_is_not_weakened(corpus, tmp_path):
    _, _, criterion, law = corpus
    agent = Stub(tmp_path / 'llm', law, criterion)
    def bad(*args, **options):
        response = FinalPairs(pairs=[FinalPair(criterion_id=criterion.id, outcome='accepted', score=1,
            rationale='Diese Aussage hat leider keine echte Textgrundlage.', law_passage_id=law.passages[0].id,
            law_quote='A totally invented source quotation.', criterion_quote=criterion.reference.quote)])
        options['validator'](response)
        return response, gen(FINAL_MODEL)
    agent.ask = bad
    with pytest.raises(ValueError):
        list(decide(law, [criterion], {criterion.id: draft(criterion, law)}, agent, Index({p.id: p.text for p in law.passages})))
    with pytest.raises(ValidationError):
        FinalPair(criterion_id=criterion.id, outcome='rejected', score=0, rationale='Keine belegte Wirkung gefunden.',
                  law_passage_id=None, law_quote=None, criterion_quote=None)


def test_citizen_correction_wins_over_automated_decision(corpus, tmp_path):
    root, _, criterion, law = corpus
    d = draft(criterion, law)
    prior = Impact(id='existing-impact', dataset='live', criterion_id=criterion.id, law_id=law.id,
        score=2, confidence=.8, rationale=d.rationale, law_passage_id=law.passages[0].id,
        law_quote=law.passages[0].text, criterion_quote=criterion.reference.quote, verification='passed',
        generation=d.generation, review=Review(status='reviewed', reviewer='citizen', reviewed_at=date.today()))
    write_json(root / 'live/impacts' / f'{prior.id}.json', prior)
    final = FinalPair(criterion_id=criterion.id, outcome='rejected', score=None,
        rationale='Ein automatischer Vorschlag ersetzt nicht die Korrektur.',
        law_passage_id=None, law_quote=None, criterion_quote=None)
    apply_decision(root, law, criterion, d, final, gen(FINAL_MODEL), {(law.id, criterion.id): prior})
    assert load_records(root, 'live', 'impacts')[0] == prior


def test_provider_credit_failure_retains_draft_and_never_invents_completion(corpus, tmp_path, monkeypatch):
    root, _, criterion, law = ready(corpus, monkeypatch)
    agent = Stub(tmp_path / 'cache/llm', law, criterion)
    agent.fail = True
    result = run_final_slice(root, agent, seconds=30)
    assert result['status'] == 'blocked' and not result['automatic_continue']
    assert result['completed_pairs'] == 0


def test_budget_transition_is_one_time_and_preserves_uncertain_charges(tmp_path):
    path = tmp_path / 'budget.json'
    write_json(path, {'model': 'openai/gpt-6-luna', 'review_model': 'anthropic/claude-sonnet-5.5',
        'max_usd': 25, 'reported_cost_usd': 16, 'unknown_cost_reserved_usd': 1,
        'pending_reserved_usd': .5, 'calls': 2000})
    assert migrate_budget(path, 20) == 37.5
    first = path.read_bytes()
    assert migrate_budget(path, 20) == 37.5 and path.read_bytes() == first
    data = json.loads(first)
    assert data['reported_cost_usd'] == 16 and data['unknown_cost_reserved_usd'] == 1
    assert data['pending_reserved_usd'] == .5 and data['calls'] == 2000
    assert (tmp_path / 'budget-before-sol.json').exists()


def test_legacy_screen_is_reused_but_old_dispute_not_counted_as_final(corpus, tmp_path):
    _, _, criterion, law = corpus
    positive = draft(criterion, law)
    path = tmp_path / 'queue.json'
    key = f'{law.id}:{criterion.id}'
    write_json(path, {'version': LEGACY_VERSION, 'grouped': {}, 'pairs': {key: {
        'signature': pair_signature(law, criterion, version=LEGACY_VERSION, reviewer='anthropic/claude-sonnet-5.5'),
        'audit': positive.model_dump(mode='json')}}})
    state = load_state(path, {law.id: law}, {criterion.id: criterion}, {})
    assert key in state['drafts'] and key not in state['pairs']
    assert (tmp_path / 'queue-before-sol.json').exists()
    negative = positive.model_copy(update={'disposition': 'no_supported_link', 'judgment': None})
    data = json.loads(path.read_text())
    data['pairs'][key]['audit'] = negative.model_dump(mode='json')
    write_json(path, data)
    state = load_state(path, {law.id: law}, {criterion.id: criterion}, {})
    assert key in state['pairs'] and key not in state['drafts']


def test_sol_flex_route_and_stage_costs_are_pinned_and_persistent(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-not-a-real-key')
    monkeypatch.setenv('OPENROUTER_REVIEW_MODEL', FINAL_MODEL)
    def handler(request):
        payload = json.loads(request.content)
        assert payload['model'] == FINAL_MODEL
        assert payload['provider']['only'] == ['openai/flex']
        assert payload['provider']['allow_fallbacks'] is False
        assert payload['provider']['max_price'] == {'prompt': 1, 'completion': 5}
        return httpx.Response(200, json={'usage': {'cost': .004}, 'choices': [{'finish_reason': 'stop',
            'message': {'content': '{"pairs":[]}'}}]})
    agent = Agent(model='openai/gpt-6-luna', cache=tmp_path / 'llm', ledger=tmp_path / 'budget.json', flex=True,
                  client=httpx.Client(transport=httpx.MockTransport(handler)))
    agent.ask('test final decision', {}, FinalPairs, review=True, stage='final_links')
    bucket = agent.summary()['breakdown'][f'{FINAL_MODEL}:final_links']
    assert bucket['reported_cost_usd'] == .004 and bucket['pending_reserved_usd'] == 0
    agent._ledger_lock.close()
    restored = Agent(model='openai/gpt-6-luna', cache=tmp_path / 'llm', ledger=tmp_path / 'budget.json', flex=True)
    assert restored.summary()['breakdown'][f'{FINAL_MODEL}:final_links'] == bucket


def test_unknown_reviewer_cannot_make_final_decision():
    class Wrong:
        review_model = 'another/model'
    with pytest.raises(ValueError, match='Sol'):
        list(final_ask(Wrong(), ['id'], lambda _: None))
