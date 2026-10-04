import json

import httpx
import pytest

from pipeline.llm import Agent, ProviderError


def test_credit_error_reports_only_safe_affordability_integers():
    error = ProviderError(402, {'error': {'message':
        'This request requires more credits. You requested up to 9,000 tokens, '
        'but can only afford 1,234. PRIVATE provider credential: do-not-print'}})
    assert error.safe_details() == {'http_status': 402, 'error_code': None, 'category': 'credits',
                                    'upstream_provider_error': False,
                                    'requested_output_tokens': 9000, 'affordable_output_tokens': 1234}
    assert 'PRIVATE' not in str(error) + json.dumps(error.safe_details())
    nested = ProviderError(402, {'error': {'metadata': {'raw':
        'credits; requested 4000 tokens but can afford 1000. PRIVATE'}}})
    assert nested.affordable_output_tokens == 1000
    assert 'PRIVATE' not in str(nested) + json.dumps(nested.safe_details())


@pytest.mark.parametrize('remaining,exhausted,covers', [(0, True, False), (2, False, False),
                                                       (20, False, True), (None, None, None)])
def test_key_status_never_exposes_financial_or_secret_values(tmp_path, monkeypatch, remaining, exhausted, covers):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'private-unit-test-only')
    def handler(request):
        assert request.method == 'GET'
        if request.url.path == '/api/v1/credits':
            return httpx.Response(200, json={'data': {'total_credits': 200000, 'total_usage': 123456.789}})
        assert request.url.path == '/api/v1/key'
        return httpx.Response(200, json={'data': {'label': 'private-key-label',
            'key': 'do-not-print', 'usage': 123456.789, 'limit': 100,
            'limit_remaining': remaining, 'limit_reset': 'daily'}})
    agent = Agent(cache=tmp_path, max_usd=12, client=httpx.Client(transport=httpx.MockTransport(handler)))
    status = agent.key_status()
    assert status['key_limit_exhausted'] is exhausted
    assert status['key_limit_covers_run_budget'] is covers
    assert status['limit_reset'] == 'daily'
    assert status['account_credit_covers_run_budget'] is True
    for secret in ('private', 'do-not-print', '123456.789'):
        assert secret not in json.dumps(status)
    assert agent.calls == 0


def test_key_diagnostics_do_not_block_generation_on_unavailable_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'private-unit-test-only')
    agent = Agent(cache=tmp_path, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(403, json={'error': 'PRIVATE free-form message'}))))
    assert agent.key_status() == {'key_configured': True, 'diagnostic_http_status': 403}
