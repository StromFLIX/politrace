"""Explicit, bounded recovery of exhausted provider tasks, not a queue/ledger reset."""
from __future__ import annotations

import logging
import re
from copy import deepcopy

logger = logging.getLogger(__name__)
_FIELDS = {'id', 'task_keys', 'additional_attempts', 'screen_batch_size'}
_TRANSIENT = {408, 429, 500, 502, 503, 504, 529}


def _request(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError('Provider recovery requires an ID, exact task keys, attempts and screening batch size')
    identifier = value['id']
    if not isinstance(identifier, str) or not re.fullmatch(r'provider-recovery-[a-z0-9-]{1,64}', identifier):
        raise ValueError('Invalid provider recovery ID')
    keys = value['task_keys']
    if (not isinstance(keys, list) or not 1 <= len(keys) <= 100
            or any(not isinstance(k, str) or not re.fullmatch(r'screen:[a-z0-9-]+:[a-f0-9]{20}', k) for k in keys)
            or len(set(keys)) != len(keys)):
        raise ValueError('Recovery targets must be unique exact screening task keys')
    attempts, size = value['additional_attempts'], value['screen_batch_size']
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError('Recovery grants one to three additional attempts, not unlimited retries')
    if type(size) is not int or not 1 <= size <= 8:
        raise ValueError('Recovery uses smaller screening batches of one to eight criteria')
    return deepcopy(value)


def apply_provider_recoveries(state, requests=(), *, active_keys, default_attempts=3):
    """Return per-task limits; retain attempts, failures, successful pairs and all costs.

    Each config ID is immutable and applied once. The durable record survives config
    removal/re-addition. Only named, currently exhausted transient provider errors can
    receive extra attempts. Completed/changed tasks cannot be brought back as fresh work.
    All requests are validated before modifying state; this function never touches a ledger.
    """
    if not isinstance(requests, (list, tuple)):
        raise ValueError('Provider recoveries must be an explicit list')
    parsed = [_request(request) for request in requests]
    if len({request['id'] for request in parsed}) != len(parsed):
        raise ValueError('Provider recovery IDs must be unique')
    records = deepcopy(state.get('provider_recoveries', []))
    limits, by_id = {}, {}
    for record in records:
        request = _request(record['request'])
        if request['id'] in by_id or set(record['attempt_limits']) != set(request['task_keys']):
            raise ValueError('Invalid retained provider recovery record')
        by_id[request['id']] = record
        for key, limit in record['attempt_limits'].items():
            previous = limits.get(key, {}).get('max_attempts', default_attempts)
            if type(limit) is not int or not previous < limit <= 9:
                raise ValueError('Invalid retained provider retry limit')
            limits[key] = {'max_attempts': limit, 'screen_batch_size': request['screen_batch_size']}
    added = []
    for request in parsed:
        prior = by_id.get(request['id'])
        if prior is not None:
            if prior['request'] != request:
                raise ValueError('An applied provider recovery is immutable; use a new ID for new recovery')
            continue
        attempt_limits, failures = {}, {}
        for key in request['task_keys']:
            error = state['errors'].get(key, {})
            attempts = state['attempts'].get(key, 0)
            previous_limit = limits.get(key, {}).get('max_attempts', default_attempts)
            code = error.get('error_code') or error.get('http_status')
            if (key not in active_keys or error.get('type') != 'provider' or error.get('retryable') is not True
                    or code not in _TRANSIENT or error.get('stage') != 'screen'
                    or type(attempts) is not int or attempts < previous_limit
                    or error.get('attempts') != attempts):
                raise ValueError('Recovery is only for active, exhausted transient provider screening errors')
            limit = attempts + request['additional_attempts']
            if limit > 9:
                raise ValueError('Recovery exceeds the nine-attempt per-task safeguard')
            attempt_limits[key] = limit
            failures[key] = deepcopy(error)
            limits[key] = {'max_attempts': limit, 'screen_batch_size': request['screen_batch_size']}
        record = {'request': request, 'attempt_limits': attempt_limits, 'previous_errors': failures}
        records.append(record)
        by_id[request['id']] = record
        added.append(record)
    if added:
        state['provider_recoveries'] = records
        for record in added:
            request = record['request']
            logger.info('Applied %s once: %s exhausted tasks, +%s bounded attempts, batches of %s; '
                        'previous attempts, results and budget unchanged', request['id'], len(request['task_keys']),
                        request['additional_attempts'], request['screen_batch_size'])
    return limits
