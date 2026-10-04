import json

import httpx
import pytest

from pipeline.llm import Agent, ProviderError
from pipeline.models import Model


class Reply(Model):
    value: str


@pytest.mark.parametrize('funded', [True, False, None])
def test_402_retry_requires_positive_account_and_key_capacity(tmp_path, monkeypatch, funded):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    attempts = []
    def handler(request):
        assert request.method == 'POST'
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(402, json={'error': {'message': 'Insufficient credits'}})
        return httpx.Response(200, json={'usage': {'cost': 0.01},
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'value': 'ok'})}}]})
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(agent, 'key_status', lambda: {
        'key_limit_covers_run_budget': True, 'account_credit_covers_run_budget': funded})
    if funded:
        result, _ = agent.ask('test', {}, Reply)
        assert result.value == 'ok' and agent.funded_credit_retries == 1
        assert agent.calls == 2 and agent.reported_cost_usd == 0.01
        assert agent.unknown_cost_reserved_usd > 0  # Do not pretend an unbilled error was reported free.
    else:
        with pytest.raises(ProviderError):
            agent.ask('test', {}, Reply)
        assert agent.calls == 1 and agent.funded_credit_retries == 0


def test_402_retries_are_bounded_even_when_funded(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(402, json={'error': {'message': 'credits'}}))))
    monkeypatch.setattr(agent, 'key_status', lambda: {
        'key_limit_covers_run_budget': True, 'account_credit_covers_run_budget': True})
    with pytest.raises(ProviderError):
        agent.ask('test', {}, Reply)
    assert agent.calls == 3 and agent.funded_credit_retries == 2
    assert agent.unknown_cost_calls == 3
    assert not list(tmp_path.glob('*.json'))
