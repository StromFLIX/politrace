import json

import httpx
import pytest
from pydantic import Field

from pipeline.llm import Agent, InvalidModelResponse
from pipeline.models import Model
from pipeline.programs import CriteriaResponse


class Reply(Model):
    value: str = Field(min_length=10)


def completion(content, finish='stop'):
    return httpx.Response(200, json={'usage': {'cost': 0.001}, 'choices': [
        {'finish_reason': finish, 'message': {'content': content}}]})


def test_schema_repairs_are_bounded_and_charge_accounted(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return completion('{"value":"short"}' if len(calls) == 1 else '{"value":"A complete response"}')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result, _ = agent.ask('test', {}, Reply)
    assert result.value == 'A complete response'
    assert len(calls) == 2 and agent.summary()['reported_cost_usd'] == 0.002
    assert 'value: string_too_short' in calls[1]['messages'][-1]['content']
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_schema_diagnostics_do_not_echo_model_values_or_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    reply = completion('{"DO-NOT-LOG-THIS":"private-model-content","value":"x"}')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(lambda _: reply)))
    with pytest.raises(InvalidModelResponse) as error:
        agent.ask('test', {}, Reply)
    message = str(error.value)
    assert 'string_too_short' in message and 'extra_forbidden' in message
    assert 'DO-NOT-LOG-THIS' not in message and 'private-model-content' not in message
    assert agent.calls == 3 and not list(tmp_path.glob('*.json'))


def test_incomplete_reason_is_safe_and_never_repaired_as_complete(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: completion('{"value":"A complete looking response"}', 'length'))))
    with pytest.raises(InvalidModelResponse, match='finish_reason=length'):
        agent.ask('test', {}, Reply)
    assert agent.calls == 1 and not list(tmp_path.glob('*.json'))


def test_dense_source_paragraphs_are_not_limited_to_eight_commitments():
    draft = {'title': 'A testable commitment', 'description': 'A longer description',
             'test': 'An observable acceptance test', 'quote': 'A verbatim source quotation',
             'tags': ['wirtschaft'], 'keywords': [], 'deadline': None}
    response = CriteriaResponse.model_validate({'criteria': [draft] * 16, 'abstention_reason': None})
    assert len(response.criteria) == 16
