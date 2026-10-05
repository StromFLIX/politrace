"""Transient infrastructure errors are not model judgments or negative legal evidence."""
import json

import httpx
import pytest
from test_experiment import OfflineAgent, finish_source

from pipeline.experiment import Experiment, analyse
from pipeline.llm import Agent, ProviderError
from pipeline.models import Model
from pipeline.store import write_json


class Reply(Model):
    value: str


@pytest.mark.parametrize('subdivide', [True, False])
def test_finish_error_retries_without_poisoning_subdivision_cache(tmp_path, monkeypatch, subdivide):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    calls = []
    def transport(request):
        calls.append(json.loads(request.content))
        if len(calls) < 3:
            return httpx.Response(200, json={'usage': {'cost': 0.001}, 'choices': [
                {'finish_reason': 'error', 'message': {'content': 'not a completion'}}]})
        return httpx.Response(200, json={'usage': {'cost': 0.001}, 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{"value":"ok"}'}}]})
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(transport)))
    result, _ = agent.ask('test', {}, Reply, subdivide=subdivide)
    assert result.value == 'ok' and agent.calls == 3
    assert agent.reported_cost_usd == pytest.approx(0.003)
    assert not (tmp_path / 'subdivisions').exists()
    assert all(call == calls[0] for call in calls)


@pytest.mark.parametrize('code', [401, 402, 403, 422, 502])
def test_choice_error_preserves_credit_and_auth_stop(tmp_path, monkeypatch, code):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    monkeypatch.setattr(Agent, 'key_status', lambda _: {})
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'choices': [{'finish_reason': 'error',
            'error': {'code': code, 'message': 'private provider data'}}]}))))
    with pytest.raises(ProviderError) as error:
        agent.ask('test', {}, Reply, subdivide=True)
    assert error.value.error_code == code
    assert agent.calls == (3 if code == 502 else 1)
    assert not (tmp_path / 'subdivisions').exists()
    assert 'private provider data' not in str(error.value)


def test_transport_retries_are_deferred_provider_errors(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    def timeout(_):
        raise httpx.ReadTimeout('private transport details')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(timeout)))
    with pytest.raises(ProviderError) as error:
        agent.ask('test', {}, Reply)
    assert error.value.retryable and agent.calls == 3 and agent.unknown_cost_calls == 3


@pytest.mark.parametrize('persistent', [True, False])
def test_failed_law_does_not_discard_other_results_and_retries_are_bounded(corpus, monkeypatch, persistent):
    import pipeline.experiment as experiment
    root, program, criterion, law = corpus
    finish_source(root, program, criterion)
    other = law.model_copy(deep=True, update={'id': 'zz-other-law'})
    write_json(root / f'live/laws/{other.id}.json', other)
    original = experiment.analyze_law
    calls = []
    def work(current, *args, **kwargs):
        calls.append(current.id)
        if current.id == law.id and (persistent or calls.count(law.id) == 1):
            raise ProviderError(200, {'error': {'code': 502}})
        return original(current, *args, **kwargs)
    monkeypatch.setattr(experiment, 'analyze_law', work)
    if persistent:
        with pytest.raises(RuntimeError, match='1 laws still have provider failures'):
            analyse(root=root, program_id=program.id, agent=OfflineAgent(root, supported=False))
    else:
        result = analyse(root=root, program_id=program.id, agent=OfflineAgent(root, supported=False))
        assert result['laws'] == 2
    assert calls.count(law.id) == 2 and calls.count(other.id) == 1
    report = Experiment.model_validate_json((root / f'live/experiments/{program.id}.json').read_text())
    assert {a.law_id for a in report.laws} == ({other.id} if persistent else {law.id, other.id})
    failures = json.loads((root / 'cache/law-failures.json').read_text())
    assert bool(failures) == persistent


def test_credit_error_is_not_deferred(corpus, monkeypatch):
    root, program, criterion, _ = corpus
    finish_source(root, program, criterion)
    calls = []
    def failed(*args):
        calls.append(1)
        raise ProviderError(402, {'error': {'message': 'credits'}})
    monkeypatch.setattr('pipeline.experiment.analyze_law', failed)
    with pytest.raises(ProviderError):
        analyse(root=root, program_id=program.id, agent=OfflineAgent(root))
    assert len(calls) == 1
