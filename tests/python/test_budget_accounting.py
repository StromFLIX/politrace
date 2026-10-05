"""Provider charges and outstanding reservations are different quantities."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from pipeline.llm import PRICE_CEILINGS, Agent, BudgetExceeded, InvalidModelResponse, ProviderError
from pipeline.models import Model


class Reply(Model):
    value: str


def reply(cost=0.001, *, finish='stop', content='{"value":"ok"}'):
    return httpx.Response(200, json={
        'usage': {'cost': cost, 'prompt_tokens': 100, 'completion_tokens': 20},
        'choices': [{'finish_reason': finish, 'message': {'content': content}}],
    })


def agent(tmp_path, monkeypatch, handler, **kwargs):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    return Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_completed_calls_release_unused_reservations_not_real_charges(tmp_path, monkeypatch):
    a = agent(tmp_path, monkeypatch, lambda _: reply(), max_usd=0.03)
    for i in range(10):
        a.ask('test', {'i': i}, Reply, max_output=256)
    s = a.summary()
    assert s['reported_cost_usd'] == 0.01
    assert s['reported_cost_calls'] == s['calls'] == 10
    assert s['pending_reserved_usd'] == s['unknown_cost_reserved_usd'] == 0
    assert s['budget_exposure_usd'] == 0.01 and s['cost_accounting_complete']
    assert s['prompt_tokens'] == 1000 and s['completion_tokens'] == 200
    a.ask('test', {'i': 0}, Reply, max_output=256)
    assert a.summary()['reported_cost_usd'] == 0.01 and a.cache_hits == 1


@pytest.mark.parametrize('cost', [None, -1, True, '0.001'])
def test_unknown_or_invalid_cost_is_never_treated_as_free(tmp_path, monkeypatch, cost):
    a = agent(tmp_path, monkeypatch, lambda _: reply(cost))
    a.ask('test', {}, Reply, max_output=256)
    s = a.summary()
    assert s['reported_cost_usd'] == 0 and s['reported_cost_calls'] == 0
    assert s['unknown_cost_reserved_usd'] > 0 and s['unknown_cost_calls'] == 1
    assert not s['cost_accounting_complete'] and s['pending_reserved_usd'] == 0


def test_explicit_zero_charge_is_known(tmp_path, monkeypatch):
    a = agent(tmp_path, monkeypatch, lambda _: reply(0))
    a.ask('test', {}, Reply, max_output=256)
    assert a.reported_cost_calls == 1 and a.reserved_usd == 0


@pytest.mark.parametrize('fault', ['truncated', 'invalid_json', 'invalid_quote'])
def test_rejected_outputs_still_count_actual_charges(tmp_path, monkeypatch, fault):
    a = agent(tmp_path, monkeypatch, lambda _: reply(
        0.01, finish='length' if fault == 'truncated' else 'stop',
        content='broken JSON' if fault == 'invalid_json' else '{"value":"wrong quote"}'))
    def reject(_):
        raise ValueError('Quote not in source')
    with pytest.raises(InvalidModelResponse):
        a.ask('test', {}, Reply, subdivide=True,
              validator=reject if fault == 'invalid_quote' else None, max_output=256)
    assert a.reported_cost_usd == 0.01 and a.reserved_usd == 0
    assert not list(tmp_path.glob('*.json'))


def test_http_timeout_keeps_unknown_charge_reservations(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    def timeout(request):
        raise httpx.ReadTimeout('request may have completed remotely', request=request)
    a = agent(tmp_path, monkeypatch, timeout)
    with pytest.raises(ProviderError, match='504'):
        a.ask('test', {}, Reply, max_output=256)
    s = a.summary()
    assert s['unknown_cost_calls'] == 3 and s['unknown_cost_reserved_usd'] > 0
    assert s['pending_reserved_usd'] == s['in_flight_calls'] == 0


def test_reconciled_spend_still_stops_before_next_paid_request(tmp_path, monkeypatch):
    a = agent(tmp_path, monkeypatch, lambda _: reply(0.02), max_usd=0.03)
    a.ask('one', {}, Reply, max_output=256)
    with pytest.raises(BudgetExceeded):
        a.ask('two', {}, Reply, max_output=256)
    assert a.calls == 1 and a.reported_cost_usd == 0.02


def test_parallel_inflight_exposure_is_reserved_atomically(tmp_path, monkeypatch):
    started, release = Event(), Event()
    def blocking(_):
        started.set()
        assert release.wait(5)
        return reply()
    a = agent(tmp_path, monkeypatch, blocking, max_usd=0.024)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(a.ask, 'one', {}, Reply, max_output=256)
        assert started.wait(5)
        try:
            assert a.summary()['in_flight_calls'] == 1
            with pytest.raises(BudgetExceeded):
                a.ask('two', {}, Reply, max_output=256)
        finally:
            release.set()
        pending.result()
    assert a.calls == 1 and a.reserved_usd == 0


def test_provider_error_classifies_nested_reason_without_exposing_raw_text(tmp_path, monkeypatch):
    body = {'error': {'message': 'Provider returned error', 'metadata': {
        'raw': '{"error":{"message":"thinking budget invalid, SECRET-NOT-TO-PRINT"}}'}}}
    a = agent(tmp_path, monkeypatch, lambda _: httpx.Response(400, json=body))
    with pytest.raises(ProviderError) as failure:
        a.ask('test', {}, Reply, max_output=256)
    assert failure.value.status_code == 400 and failure.value.category == 'reasoning_parameters'
    assert 'SECRET' not in str(failure.value)
    assert a.summary()['unknown_cost_calls'] == 1


def test_comparison_does_not_mistake_generic_check_verbs_for_examination_commitments():
    import re

    from scripts.evaluate_models import CONCEPTS

    pattern = CONCEPTS['minimum-wage']['examination, not implementation, of funding criteria']
    assert not re.search(pattern, 'Prüfe, ob ein Mindestlohn eingeführt wurde.', re.I)
    assert re.search(pattern, 'Eine dokumentierte Prüfung liegt vor.', re.I)


def test_current_models_do_not_require_unsupported_temperature(tmp_path, monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert 'temperature' not in body
        assert body['provider']['max_price'] == PRICE_CEILINGS
        assert body['reasoning']['effort'] == 'medium'
        assert body['model'] in ['anthropic/claude-sonnet-5.5', 'openai/gpt-5.6-sol']
        return reply()
    a = agent(tmp_path, monkeypatch, handler)
    a.ask('test', {}, Reply, max_output=256)
    a.ask('test', {}, Reply, review=True, max_output=256)
    assert a.calls == 2
