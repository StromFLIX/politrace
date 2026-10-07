"""A targeted provider repair must not reset costs, completed work or retry ceilings."""
from copy import deepcopy

import pytest

from pipeline.recovery import apply_provider_recoveries

KEY = 'screen:bgbl-1-2026-107:' + 'a' * 20
OTHER = 'screen:bgbl-1-2026-107:' + 'b' * 20
REQUEST = {'id': 'provider-recovery-test', 'task_keys': [KEY],
           'additional_attempts': 2, 'screen_batch_size': 4}


@pytest.fixture
def state():
    failure = {'type': 'provider', 'retryable': True, 'http_status': 200, 'error_code': 502,
               'stage': 'screen', 'attempts': 3, 'next_retry_at': 1000}
    return {'pairs': {'unchanged-pair': {'audit': 'saved'}}, 'drafts': {}, 'grouped': {'saved-group': {}},
            'slices': 90, 'attempts': {KEY: 3, OTHER: 3},
            'errors': {KEY: deepcopy(failure), OTHER: deepcopy(failure)}}


def apply(state, requests=(REQUEST,), **kwargs):
    return apply_provider_recoveries(state, requests, active_keys={KEY, OTHER}, **kwargs)


def test_targeted_recovery_keeps_all_previous_work_attempts_and_errors(state):
    before = deepcopy(state)
    limits = apply(state)
    assert limits == {KEY: {'max_attempts': 5, 'screen_batch_size': 4}}
    assert {k: v for k, v in state.items() if k != 'provider_recoveries'} == before
    record = state['provider_recoveries'][0]
    assert record == {'request': REQUEST, 'attempt_limits': {KEY: 5},
                      'previous_errors': {KEY: before['errors'][KEY]}}


def test_repeated_config_and_remove_readd_do_not_grant_more_attempts(state):
    limits = apply(state)
    before = deepcopy(state)
    for requests in ((REQUEST,), (), (REQUEST,), (REQUEST,)):
        assert apply(state, requests) == limits
        assert state == before


def test_completed_recovery_stays_idempotent_without_old_error_or_active_task(state):
    expected = apply(state)
    state['errors'].pop(KEY)
    state['attempts'][KEY] = 4
    before = deepcopy(state)
    assert apply_provider_recoveries(state, [REQUEST], active_keys=set()) == expected
    assert state == before


@pytest.mark.parametrize('change', [{'additional_attempts': 3}, {'screen_batch_size': 2}, {'task_keys': [OTHER]}])
def test_applied_request_is_immutable(state, change):
    apply(state)
    before = deepcopy(state)
    with pytest.raises(ValueError, match='immutable'):
        apply(state, [{**REQUEST, **change}])
    assert state == before


def test_new_explicit_recovery_is_required_after_the_added_attempts_are_exhausted(state):
    apply(state)
    state['attempts'][KEY] = state['errors'][KEY]['attempts'] = 5
    assert apply(state)[KEY]['max_attempts'] == 5
    second = {**REQUEST, 'id': 'provider-recovery-second'}
    assert apply(state, [REQUEST, second])[KEY]['max_attempts'] == 7
    assert state['attempts'][KEY] == 5
    assert len(state['provider_recoveries']) == 2


def test_cumulative_recovery_remains_bounded(state):
    apply(state)
    state['attempts'][KEY] = state['errors'][KEY]['attempts'] = 8
    before = deepcopy(state)
    with pytest.raises(ValueError, match='safeguard'):
        apply(state, [{**REQUEST, 'id': 'provider-recovery-excess'}])
    assert state == before


@pytest.mark.parametrize('error', [
    {'type': 'budget'}, {'type': 'validation'}, {'retryable': False},
    {'error_code': 402}, {'error_code': 401}, {'error_code': 403},
    {'error_code': 400}, {'stage': 'final'}, {'attempts': 2},
])
def test_nontransient_unfunded_and_inconsistent_failures_are_not_requeued(state, error):
    state['errors'][KEY].update(error)
    before = deepcopy(state)
    with pytest.raises(ValueError, match='exhausted transient'):
        apply(state)
    assert state == before


def test_inactive_or_unexhausted_tasks_cannot_be_restarted(state):
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply_provider_recoveries(state, [REQUEST], active_keys=set())
    assert state == before
    state['attempts'][KEY] = state['errors'][KEY]['attempts'] = 2
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply(state)
    assert state == before


@pytest.mark.parametrize('requests', [
    None, {}, 'reset', [None], [REQUEST, REQUEST],
    [{**REQUEST, 'id': 'reset-all'}], [{**REQUEST, 'task_keys': [KEY, KEY]}],
    [{**REQUEST, 'task_keys': []}], [{**REQUEST, 'task_keys': ['*']}],
    [{**REQUEST, 'additional_attempts': True}], [{**REQUEST, 'additional_attempts': 0}],
    [{**REQUEST, 'additional_attempts': 4}], [{**REQUEST, 'screen_batch_size': 16}],
    [{**REQUEST, 'screen_batch_size': 0}], [{**REQUEST, 'screen_batch_size': True}],
    [REQUEST, {**REQUEST, 'id': 'provider-recovery-invalid', 'task_keys': ['bad']}],
])
def test_bad_recovery_config_cannot_partially_modify_state(state, requests):
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply(state, requests)
    assert state == before


def test_later_unrecoverable_task_does_not_partially_apply_earlier_request(state):
    state['errors'][OTHER]['error_code'] = 402
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply(state, [REQUEST, {**REQUEST, 'id': 'provider-recovery-other', 'task_keys': [OTHER]}])
    assert state == before
