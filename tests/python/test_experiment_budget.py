import json

import httpx
import pytest

from pipeline.llm import Agent, BudgetExceeded, SliceExpired
from pipeline.models import Model


class Reply(Model):
    value: str


def make_agent(tmp_path, monkeypatch, handler, **kwargs):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-not-a-credential')
    return Agent(cache=tmp_path / 'llm', model='openai/gpt-6-luna', flex=True,
                 ledger=tmp_path / 'budget.json',
                 client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def reply(_):
    return httpx.Response(200, json={'usage': {'cost': 0.001},
        'choices': [{'finish_reason': 'stop', 'message': {'content': '{"value":"ok"}'}}]})


def test_flex_is_explicit_pinned_and_reserves_before_network(tmp_path, monkeypatch):
    def handler(request):
        payload = json.loads(request.content)
        assert payload['provider']['only'] == ['openai/flex']
        assert payload['provider']['allow_fallbacks'] is False
        assert payload['provider']['max_price'] == {'prompt': 0.05, 'completion': 0.25}
        before = json.loads((tmp_path / 'budget.json').read_text())
        assert before['pending_reserved_usd'] > 0 and before['in_flight_calls'] == 1
        return reply(request)
    a = make_agent(tmp_path, monkeypatch, handler)
    a.ask('test', {}, Reply)
    assert a.summary()['reported_cost_usd'] == 0.001
    saved = json.loads((tmp_path / 'budget.json').read_text())
    assert saved['pending_reserved_usd'] == 0 and saved['reported_cost_usd'] == 0.001


def test_resume_counts_previous_charges_and_cannot_raise_cap(tmp_path, monkeypatch):
    a = make_agent(tmp_path, monkeypatch, reply, max_usd=0.0025)
    a.ask('test', {}, Reply)
    a._ledger_lock.close()
    b = make_agent(tmp_path, monkeypatch, reply, max_usd=0.0025)
    assert b.calls == 1 and b.reported_cost_usd == 0.001
    with pytest.raises(BudgetExceeded):
        b.ask('another', {}, Reply)
    b._ledger_lock.close()
    with pytest.raises(ValueError, match='raise'):
        make_agent(tmp_path, monkeypatch, reply, max_usd=1)


def test_killed_inflight_call_keeps_exposure_on_resume(tmp_path, monkeypatch):
    a = make_agent(tmp_path, monkeypatch, reply)
    a.pending_reserved_usd = 0.25
    a.in_flight_calls = 2
    a._persist_ledger()
    a._ledger_lock.close()
    b = make_agent(tmp_path, monkeypatch, reply)
    assert b.unknown_cost_reserved_usd == 0.25 and b.unknown_cost_calls == 2
    assert b.in_flight_calls == 0 and b.pending_reserved_usd == 0


def test_same_ledger_cannot_be_used_by_two_agents(tmp_path, monkeypatch):
    a = make_agent(tmp_path, monkeypatch, reply)
    with pytest.raises(BlockingIOError):
        make_agent(tmp_path, monkeypatch, reply)
    a._ledger_lock.close()


def test_slice_deadline_allows_cached_results_but_never_new_paid_calls(tmp_path, monkeypatch):
    a = make_agent(tmp_path, monkeypatch, reply)
    a.ask('already done', {}, Reply)
    a.request_deadline = 0
    a.ask('already done', {}, Reply)
    with pytest.raises(SliceExpired):
        a.ask('new task', {}, Reply)
    assert a.summary()['calls'] == 1 and a.summary()['in_flight_calls'] == 0
    assert a.summary()['reported_cost_usd'] == 0.001


def test_unsupported_model_cannot_claim_flex_prices(tmp_path):
    with pytest.raises(ValueError, match='only verified'):
        Agent(cache=tmp_path, model='other/model', flex=True)
