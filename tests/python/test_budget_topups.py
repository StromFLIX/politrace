"""Explicit additional funding is durable and cannot compound on continuation."""
import json

import pytest

from pipeline.adjudication import FINAL_MODEL
from pipeline.final_queue import VERSION, migrate_budget
from pipeline.llm import Agent
from pipeline.store import ROOT, write_json

TOPUP = {'id': 'budget-topup-2026-10-05-extra-10', 'additional_budget_usd': 10}


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'budget.json'
    write_json(path, {
        'model': 'openai/gpt-6-luna', 'review_model': FINAL_MODEL,
        'max_usd': 37.5, 'calls': 2000, 'cache_hits': 24,
        'reported_cost_usd': 22, 'reported_cost_calls': 1990,
        'unknown_cost_reserved_usd': 1, 'unknown_cost_calls': 9,
        'pending_reserved_usd': .5, 'in_flight_calls': 1,
        'prompt_tokens': 100000, 'completion_tokens': 10000,
        'breakdown': {f'{FINAL_MODEL}:final_links': {
            'model': FINAL_MODEL, 'stage': 'final_links', 'calls': 100,
            'reported_cost_usd': 2, 'unknown_cost_reserved_usd': .1, 'pending_reserved_usd': .5}},
        'migrations': [{'id': VERSION, 'from_model': 'anthropic/claude-sonnet-5.5',
            'to_model': FINAL_MODEL, 'prior_reported_usd': 16, 'prior_exposure_usd': 17.5,
            'additional_budget_usd': 20, 'cumulative_cap_usd': 37.5}],
    })
    return path


def test_extra_funding_applies_once_without_resetting_any_accounting(ledger, caplog):
    before = json.loads(ledger.read_text())
    with caplog.at_level('INFO', logger='pipeline.final_queue'):
        assert migrate_budget(ledger, 20, topups=[TOPUP]) == 47.5
        saved = ledger.read_bytes()
        for _ in range(5):
            assert migrate_budget(ledger, 20, topups=[TOPUP]) == 47.5
            assert ledger.read_bytes() == saved
    data = json.loads(saved)
    assert data['migrations'][:-1] == before['migrations']
    assert data['migrations'][-1] == {
        **TOPUP, 'kind': 'budget_topup', 'previous_cap_usd': 37.5, 'cumulative_cap_usd': 47.5}
    for key in before.keys() - {'max_usd', 'migrations'}:
        assert data[key] == before[key]
    assert caplog.text.count('Applied budget-topup-') == 1


def test_ledger_restore_retains_topup_and_conservatively_settles_inflight_cost(ledger, tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_REVIEW_MODEL', FINAL_MODEL)
    cap = migrate_budget(ledger, 20, topups=[TOPUP])
    agent = Agent(cache=tmp_path / 'llm', ledger=ledger, model='openai/gpt-6-luna',
                  flex=True, max_usd=cap, max_calls=10000)
    try:
        assert agent.max_usd == 47.5
        assert agent.calls == 2000 and agent.reported_cost_usd == 22
        assert agent.unknown_cost_reserved_usd == 1.5  # Not refunded on restart.
        assert agent.unknown_cost_calls == 10
        saved = ledger.read_bytes()
    finally:
        agent._ledger_lock.close()
        agent.client.close()
    assert migrate_budget(ledger, 20, topups=[TOPUP]) == 47.5
    assert ledger.read_bytes() == saved


def test_only_a_new_id_adds_funding_and_config_rollback_never_regrants(ledger):
    second = {'id': 'budget-topup-separate-deposit', 'additional_budget_usd': 5}
    assert migrate_budget(ledger, 20, topups=[TOPUP]) == 47.5
    assert migrate_budget(ledger, 20, topups=[TOPUP, second]) == 52.5
    saved = ledger.read_bytes()
    assert migrate_budget(ledger, 20) == 52.5
    assert migrate_budget(ledger, 20, topups=[second, TOPUP]) == 52.5
    assert ledger.read_bytes() == saved
    # The old transition parameter cannot silently change a migrated budget.
    assert migrate_budget(ledger, 30, topups=[TOPUP]) == 52.5


def test_applied_id_amount_is_immutable(ledger):
    migrate_budget(ledger, 20, topups=[TOPUP])
    before = ledger.read_bytes()
    with pytest.raises(ValueError, match='immutable'):
        migrate_budget(ledger, 20, topups=[{**TOPUP, 'additional_budget_usd': 20}])
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('amount', [0, -10, True, '10', None, float('nan'), float('inf'), 101, 63])
def test_invalid_or_over_cap_topups_cannot_modify_ledger(ledger, amount):
    before = ledger.read_bytes()
    with pytest.raises(ValueError):
        migrate_budget(ledger, 20, topups=[{**TOPUP, 'additional_budget_usd': amount}])
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('topups', [
    None, {}, 'funds', [10], [{'id': TOPUP['id']}],
    [{**TOPUP, 'balance': 24.89}], [{**TOPUP, 'id': VERSION}],
    [{**TOPUP, 'id': []}], [{**TOPUP, 'id': 'budget-topup-'}], [TOPUP, TOPUP],
    [TOPUP, {'id': 'budget-topup-too-large', 'additional_budget_usd': 60}],
])
def test_all_topups_validated_before_any_write(ledger, topups):
    before = ledger.read_bytes()
    with pytest.raises(ValueError):
        migrate_budget(ledger, 20, topups=topups)
    assert ledger.read_bytes() == before


def test_topup_does_not_replace_missing_or_unmigrated_ledger(ledger, tmp_path):
    missing = tmp_path / 'absent.json'
    with pytest.raises(ValueError, match='retained ledger'):
        migrate_budget(missing, 20, topups=[TOPUP])
    assert not missing.exists()
    data = json.loads(ledger.read_text())
    data['migrations'] = []
    write_json(ledger, data)
    with pytest.raises(ValueError, match='Missing documented'):
        migrate_budget(ledger, 20, topups=[TOPUP])


def test_legacy_transition_and_funding_are_atomic(ledger):
    data = json.loads(ledger.read_text())
    data.update(review_model='anthropic/claude-sonnet-5.5', max_usd=25,
                reported_cost_usd=16, migrations=[])
    write_json(ledger, data)
    before = ledger.read_bytes()
    with pytest.raises(ValueError):
        migrate_budget(ledger, 20, topups=[TOPUP, TOPUP])
    assert ledger.read_bytes() == before
    assert not ledger.with_name('budget-before-sol.json').exists()
    assert migrate_budget(ledger, 20, topups=[TOPUP]) == 47.5
    assert json.loads(ledger.with_name('budget-before-sol.json').read_text()) == data


def test_production_config_authorizes_exactly_one_additional_ten_dollars(ledger):
    config = json.loads((ROOT / '.github/production.json').read_text())
    assert config['additional_budget_usd'] == 20
    assert config['budget_topups'] == [TOPUP]
    assert migrate_budget(ledger, config['additional_budget_usd'], topups=config['budget_topups']) == 47.5
    assert config['review_model'] == FINAL_MODEL and config['provider'] == 'openai/flex'
    script = (ROOT / 'scripts/production.py').read_text()
    assert "topups=config.get('budget_topups', [])" in script
