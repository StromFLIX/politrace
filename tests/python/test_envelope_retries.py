"""An HTTP 200 envelope can contain an upstream error, not a completion."""
import json

import httpx
import pytest

from pipeline.llm import Agent, ProviderError
from pipeline.models import Model


class Reply(Model):
    value: str


@pytest.mark.parametrize('code', [None, 500, '503', 429])
def test_transient_200_envelope_retried_and_accounted(tmp_path, monkeypatch, code):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    calls = []
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'error': {'code': code, 'message': 'upstream failed'}})
        return httpx.Response(200, json={'usage': {'cost': 0.001}, 'choices': [
            {'finish_reason': 'stop', 'message': {'content': json.dumps({'value': 'ok'})}}]})
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(transport)))
    result, _ = agent.ask('test', {}, Reply)
    assert result.value == 'ok' and agent.calls == 2
    assert agent.unknown_cost_calls == 1 and agent.unknown_cost_reserved_usd > 0
    assert agent.reported_cost_usd == 0.001


@pytest.mark.parametrize('code', [400, 401, 402, 403, 422])
def test_permanent_error_inside_200_is_not_blindly_retried(tmp_path, monkeypatch, code):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr(Agent, 'key_status', lambda _: {})
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'error': {'code': code, 'message': 'not retryable'}}))))
    with pytest.raises(ProviderError) as caught:
        agent.ask('test', {}, Reply)
    assert agent.calls == 1 and caught.value.error_code == code


def test_200_error_retries_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'error': {'message': 'temporary'}}))))
    with pytest.raises(ProviderError):
        agent.ask('test', {}, Reply)
    assert agent.calls == 3 and agent.unknown_cost_calls == 3
