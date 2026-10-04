"""Resume paid batches without replaying invalid parents or weakening source checks."""
import json
import subprocess

import httpx
import pytest

from pipeline.llm import Agent, BudgetExceeded, InvalidModelResponse
from pipeline.models import Model
from pipeline.programs import extract_criteria
from pipeline.store import ROOT, load_records, validate_store


class Reply(Model):
    value: str


def response(value):
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
        'content': json.dumps(value)}}]})


def test_split_hints_skip_paid_failures_but_never_approve_results(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: response({'value': 'bad quote'}))))
    def reject(_):
        raise ValueError('Quote not in source')
    for _ in range(2):
        with pytest.raises(InvalidModelResponse):
            agent.ask('same task', {}, Reply, validator=reject, subdivide=True)
    assert agent.calls == 1 and agent.subdivision_cache_hits == 1
    assert not list(tmp_path.glob('*.json'))
    hint = next((tmp_path / 'subdivisions').glob('*.json'))
    assert set(json.loads(hint.read_text())) == {'version', 'input_sha256'}
    assert 'bad quote' not in hint.read_text() and 'unit-test-only' not in hint.read_text()
    with pytest.raises(InvalidModelResponse):
        agent.ask('different task', {}, Reply, validator=reject, subdivide=True)
    assert agent.calls == 2  # A different fingerprint is not poisoned by an old hint.


@pytest.mark.parametrize('failure', ['budget', 'auth', 'network'])
def test_nonsemantic_failures_are_never_saved_as_subdivision_hints(tmp_path, monkeypatch, failure):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    def handler(request):
        if failure == 'network':
            raise httpx.ConnectError('Test transport failure', request=request)
        return httpx.Response(401)
    agent = Agent(cache=tmp_path, max_usd=0.00001 if failure == 'budget' else 5,
                  client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError):
        agent.ask('task', {}, Reply, subdivide=True)
    assert not list(tmp_path.iterdir())


def test_corrupt_cache_is_a_miss_and_lookup_never_spends(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: response({'value': 'valid'}))))
    assert not agent.has_cached('task', {}, Reply)
    assert agent.calls == 0
    agent.ask('task', {}, Reply)
    assert agent.has_cached('task', {}, Reply)
    path = next(tmp_path.glob('*.json'))
    path.write_text('{broken JSON')
    assert not agent.has_cached('task', {}, Reply)
    assert agent.calls == 1
    agent.ask('task', {}, Reply)
    assert agent.calls == 2


def test_budget_resume_reuses_legacy_subbatch_cache_without_repaying_parent(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    (root / f'live/criteria/{criterion.id}.json').unlink()
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        data = json.loads(payload['messages'][1]['content'])['data']
        leaves = data['paragraphs']
        calls.append([leaf['leaf_id'] for leaf in leaves])
        return response({'paragraphs': [] if len(leaves) > 1 else [
            {'leaf_id': leaves[0]['leaf_id'], 'criteria': [], 'abstention_reason': 'Nur Rhetorik.'}]})
    cache = tmp_path / 'llm'
    client = httpx.Client(transport=httpx.MockTransport(handler))
    first = Agent(cache=cache, max_calls=2, client=client)
    with pytest.raises(BudgetExceeded):
        extract_criteria(root=root, program_id=program.id, agent=first, batch_size=6)
    assert not load_records(root, 'live', 'criteria')
    assert not load_records(root, 'live', 'programs')[0].criteria_extraction
    # Simulate a cache saved by the old importer, which retained no invalid-parent hints.
    for hint in (cache / 'subdivisions').glob('*.json'):
        hint.unlink()
    resumed = Agent(cache=cache, max_calls=1, client=client)
    result = extract_criteria(root=root, program_id=program.id, agent=resumed, batch_size=6)
    assert result['abstained_leaves'] == 2
    assert resumed.calls == 1 and resumed.cache_hits == 1
    assert [len(batch) for batch in calls] == [2, 1, 1]
    validate_store(root)
    again = extract_criteria(root=root, program_id=program.id, agent=resumed, batch_size=6)
    assert again['preserved_leaves'] == 2 and resumed.calls == 1


def test_permuted_complete_batches_are_canonicalized_by_id_not_position(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    (root / f'live/criteria/{criterion.id}.json').unlink()
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    rows = [dict(leaf_id=leaf.id, criteria=[], abstention_reason='Nur Rhetorik.')
            for leaf in reversed(program.leaves)]
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: response({'paragraphs': rows}))))
    extract_criteria(root=root, program_id=program.id, agent=agent, batch_size=6)
    saved = load_records(root, 'live', 'programs')[0]
    assert [a.leaf_id for a in saved.criteria_extraction] == [leaf.id for leaf in program.leaves]
    assert agent.calls == 1
    validate_store(root)


def test_explicit_sample_preserves_real_neighbour_context_and_reports_remainder(corpus, tmp_path, monkeypatch):
    root, program, criterion, _ = corpus
    (root / f'live/criteria/{criterion.id}.json').unlink()
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    def handler(request):
        data = json.loads(json.loads(request.content)['messages'][1]['content'])['data']
        assert len(data['paragraphs']) == 1
        leaf = data['paragraphs'][0]
        assert leaf['next_context'] == program.leaves[1].text[:1000]
        return response({'paragraphs': [{'leaf_id': leaf['leaf_id'], 'criteria': [],
                                         'abstention_reason': 'Test abstention.'}]})
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = extract_criteria(root=root, program_id=program.id, agent=agent, batch_size=6,
                              leaf_ids=[program.leaves[0].id])
    assert result['processed_leaves'] == result['remaining_leaves'] == 1
    assert len(load_records(root, 'live', 'programs')[0].criteria_extraction) == 1
    for selected in [[program.leaves[0].id] * 2, ['unknown-leaf']]:
        with pytest.raises(ValueError, match='unique existing'):
            extract_criteria(root=root, program_id=program.id, agent=agent, leaf_ids=selected)
    assert agent.calls == 1
    validate_store(root)


def test_canonical_coverage_is_not_ignored_as_test_output():
    for path, expected in [('data/live/coverage/laws-since-2025-03-25.json', 1),
                           ('coverage/lcov.info', 0)]:
        result = subprocess.run(['git', 'check-ignore', '--no-index', path], cwd=ROOT,
                                capture_output=True, text=True)
        assert result.returncode == expected, result.stdout + result.stderr
