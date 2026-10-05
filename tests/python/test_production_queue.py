import json
from pathlib import Path

import pytest

from pipeline.experiment import (
    Judgments,
    LawAudit,
    PairAudit,
    PairJudgment,
    analyze_law,
    complete_link_groups,
)
from pipeline.llm import InvalidModelResponse, ProviderError, SliceExpired
from pipeline.models import Generation, LeafExtraction
from pipeline.production import retrieve, run_slice, safe_failure
from pipeline.store import digest, load_records, write_json
from scripts.production_checkpoint import merge_live

GEN = Generation(model='test-primary', prompt_version='test-v1', input_sha256='a' * 64)


class Agent:
    model = 'test-primary'
    review_model = 'test-review'
    reported_cost_usd = 0
    reserved_usd = 0

    def __init__(self, cache):
        self.cache = cache
        self.calls = 0

    def summary(self):
        return {'model': self.model, 'review_model': self.review_model, 'reported_cost_usd': 0,
                'budget_exposure_usd': 0, 'max_usd': 25, 'calls': self.calls}


def complete_source(root, program, criteria):
    program.criteria_extraction = [LeafExtraction(leaf_id=leaf.id,
        criterion_ids=[c.id for c in criteria if c.leaf_id == leaf.id],
        abstention_reason=None if any(c.leaf_id == leaf.id for c in criteria) else 'Keine messbare Zusage.',
        generation=GEN) for leaf in program.leaves]
    write_json(root / 'live/programs' / f'{program.id}.json', program)


def no_link(law, criteria, candidates, eligible_count, agent, existing, root, corpus_hash, **kwargs):
    agent.calls += 1
    return LawAudit(law_id=law.id, analysis_sha256='b' * 64, status='completed', eligible_count=eligible_count,
        candidate_ids=candidates, omitted_count=eligible_count-len(candidates), pairs=[PairAudit(
            criterion_id=cid, disposition='no_supported_link', rationale='Keine hinreichend belegte Wirkung.',
            input_sha256='c' * 64, generation=[GEN]) for cid in candidates])


def mock_grouping(monkeypatch):
    monkeypatch.setattr('pipeline.production.deduplicate', lambda items, _: (complete_link_groups([c.id for c in items], []), []))


def test_no_silent_analysis_of_unfinished_programme(corpus, tmp_path):
    with pytest.raises(ValueError, match='extraction incomplete'):
        run_slice(corpus[0], Agent(tmp_path / 'llm'), seconds=30)


def test_all_programme_quota_and_temporal_eligibility(corpus):
    _, program, criterion, law = corpus
    other = program.model_copy(deep=True, update={'id': 'other-2025'})
    c2 = criterion.model_copy(update={'id': 'other-criterion', 'program_id': other.id})
    selected, _ = retrieve([law], [criterion, c2], [program, other])
    assert selected[law.id] == {criterion.id, c2.id}
    other.period_start = law.published_at.replace(year=2026)
    selected, _ = retrieve([law], [criterion, c2], [program, other])
    assert selected[law.id] == {criterion.id}


def test_resume_does_not_pay_again_and_completed_run_is_noop(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', no_link)
    agent = Agent(tmp_path / 'cache/llm')
    result = run_slice(root, agent, workers=2, seconds=30)
    assert result['status'] == 'completed'
    assert result['completed_pairs'] == 1
    before = (root / 'live/analysis/overview.json').read_bytes()
    second = run_slice(root, agent, workers=2, seconds=30)
    assert agent.calls == 1
    assert not second['automatic_continue']
    assert before == (root / 'live/analysis/overview.json').read_bytes()


def test_provider_failure_deferred_not_converted_to_no_link(corpus, tmp_path, monkeypatch):
    root, program, criterion, law = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    def fail(*args, **kwargs):
        raise ProviderError(200, {'error': {'code': 502, 'message': 'private upstream response'}})
    monkeypatch.setattr('pipeline.production.analyze_law', fail)
    agent = Agent(tmp_path / 'cache/llm')
    result = run_slice(root, agent, seconds=30, clock=lambda: 1000)
    assert result['status'] == 'continuing'
    assert result['pending_pairs'] == 1
    assert result['completed_pairs'] == 0
    assert 'private upstream' not in json.dumps(result)
    assert result['programmes'][0]['laws_completed'] == 0
    monkeypatch.setattr('pipeline.production.analyze_law', no_link)
    result = run_slice(root, agent, seconds=30, clock=lambda: 2000)
    assert result['status'] == 'completed'
    report = json.loads((root / 'live/analyses' / f'{program.id}.json').read_text())
    assert report['laws'][0]['pairs'][0]['disposition'] == 'no_supported_link'


def test_credit_failure_stops_automatic_continuation(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', lambda *a, **k: (_ for _ in ()).throw(ProviderError(402, {})))
    result = run_slice(root, Agent(tmp_path / 'cache/llm'), seconds=30)
    assert result['status'] == 'blocked'
    assert result['automatic_continue'] is False
    assert result['pending_pairs'] == 1


def test_poisoned_batch_is_quarantined_after_bounded_retries(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', lambda *a, **k: (_ for _ in ()).throw(InvalidModelResponse('unsafe output')))
    agent = Agent(tmp_path / 'cache/llm')
    for now in (1000, 3000, 9000):
        result = run_slice(root, agent, seconds=30, clock=lambda: now)
    assert result['status'] == 'needs_attention'
    assert result['pending_pairs'] == 1
    assert all(e['attempts'] == 3 for e in result['errors'].values())


def test_quarantined_law_does_not_block_other_retryable_work(corpus, tmp_path, monkeypatch):
    root, program, criterion, law = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', lambda *a, **k: (_ for _ in ()).throw(InvalidModelResponse('bad output')))
    agent = Agent(tmp_path / 'cache/llm')
    for now in (1000, 3000, 9000):
        result = run_slice(root, agent, seconds=30, clock=lambda: now)
    assert result['status'] == 'needs_attention'
    other = law.model_copy(update={'id': 'bgbl-1-2025-101'})
    write_json(root / 'live/laws' / f'{other.id}.json', other)
    result = run_slice(root, agent, seconds=30, clock=lambda: 20000)
    assert result['status'] == 'continuing'  # Other law still has its own retries.
    assert result['pending_pairs'] == 2
    monkeypatch.setattr('pipeline.production.analyze_law', no_link)
    result = run_slice(root, agent, seconds=30, clock=lambda: 30000)
    assert result['status'] == 'needs_attention'  # Only the quarantined item remains.
    assert result['completed_pairs'] == 1


def test_slice_boundary_preserves_retry_allowance(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', lambda *a, **k: (_ for _ in ()).throw(SliceExpired()))
    agent = Agent(tmp_path / 'cache/llm')
    result = run_slice(root, agent, seconds=30)
    assert result['status'] == 'continuing' and not result['errors']
    queue = json.loads((agent.cache.parent / 'queue.json').read_text())
    assert not any(queue['attempts'].values())
    monkeypatch.setattr('pipeline.production.analyze_law', no_link)
    assert run_slice(root, agent, seconds=30)['status'] == 'completed'


def test_source_change_invalidates_published_audits_not_only_cache(corpus, tmp_path, monkeypatch):
    root, program, criterion, law = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', no_link)
    agent = Agent(tmp_path / 'cache/llm')
    run_slice(root, agent, seconds=30)
    law.official_title = 'Corrected official law title'
    write_json(root / 'live/laws' / f'{law.id}.json', law)
    result = run_slice(root, agent, seconds=30)
    assert result['status'] == 'completed' and agent.calls == 2


def test_new_law_without_candidates_still_refreshes_coverage(corpus, tmp_path, monkeypatch):
    root, program, criterion, law = corpus
    complete_source(root, program, [criterion])
    mock_grouping(monkeypatch)
    monkeypatch.setattr('pipeline.production.analyze_law', no_link)
    agent = Agent(tmp_path / 'cache/llm')
    run_slice(root, agent, seconds=30)
    from datetime import date
    other = law.model_copy(update={'id': 'bgbl-1-2020-1', 'published_at': date(2020, 1, 1)})
    write_json(root / 'live/laws' / f'{other.id}.json', other)
    result = run_slice(root, agent, seconds=30)
    assert agent.calls == 1
    assert result['total_laws'] == 2 and result['programmes'][0]['laws_completed'] == 2


def test_incremental_law_batch_checkpoint_survives_later_failure(corpus, tmp_path):
    root, _, criterion, law = corpus
    criteria = [criterion.model_copy(update={'id': f'criterion-{n}'}) for n in range(8)]
    class Stub(Agent):
        fail = True
        def ask(self, task, data, schema, **options):
            self.calls += 1
            if self.fail and self.calls == 2:
                raise ProviderError(503, {})
            result = Judgments(pairs=[PairJudgment(criterion_id=c['id'], supported=False,
                disposition='missing_context', score=None, confidence=0.2,
                rationale='Es fehlt notwendiger Rechtskontext.', law_passage_id=None,
                law_quote=None, criterion_quote=None, caveats=[]) for c in data['criteria']])
            return result, GEN
    agent = Stub(tmp_path / 'cache/llm')
    args = (law, criteria, [c.id for c in criteria], len(criteria), agent, {}, root, 'd' * 64)
    with pytest.raises(ProviderError):
        analyze_law(*args)
    saved = json.loads((agent.cache.parent / 'laws' / f'{law.id}.json').read_text())
    assert saved['status'] == 'partial' and len(saved['pairs']) == 6
    agent.fail = False
    result = analyze_law(*args)
    assert len(result.pairs) == 8 and agent.calls == 3


def test_merge_preserves_citizen_criterion_and_source_corrections(corpus, tmp_path):
    root, program, criterion, _ = corpus
    incoming = tmp_path / 'incoming'
    modified = criterion.model_copy(update={'test': 'A replacement test should not overwrite the current test.'})
    write_json(incoming / 'criteria' / f'{criterion.id}.json', modified)
    merge_live(incoming, root / 'live')
    assert load_records(root, 'live', 'criteria')[0].test == criterion.test
    program.source.title = 'Changed source'
    write_json(incoming / 'programs' / f'{program.id}.json', program)
    with pytest.raises(ValueError, match='Changed source'):
        merge_live(incoming, root / 'live')


def test_safe_failures_do_not_leak_source_or_provider_bodies():
    assert safe_failure(ValueError('private content')) == {'type': 'ValueError', 'retryable': False}
    assert safe_failure(InvalidModelResponse('private model output')) == {'type': 'validation', 'retryable': True}


def test_production_recurs_at_requested_time_and_always_preserves_checkpoint():
    workflow = Path('.github/workflows/production.yml').read_text()
    assert "cron: '0 6 * * *'" in workflow and 'timezone: Europe/Berlin' in workflow
    assert 'cancel-in-progress: false' in workflow
    assert 'gh' in Path('scripts/production_checkpoint.py').read_text()
    assert "if: always() && hashFiles('.cache/production/budget.json')" in workflow
    assert 'MISTRAL_API_KEY: ${{ secrets.MISTRAL_API_KEY }}' in workflow
    assert 'gh\', \'workflow\', \'run\', \'production.yml\'' in workflow
    assert digest(workflow)
