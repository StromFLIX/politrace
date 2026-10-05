"""Resumable law-first, all-party queue. A poisoned item never blocks unrelated work.

A GitHub run executes a short slice, publishes validated results, uploads its ledger
and queue, and dispatches the next slice. Limits/errors are explicit, not no-op success.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Event, Lock, Thread

from pipeline.experiment import (
    VERSION as LEGACY_VERSION,
)
from pipeline.experiment import (
    Experiment,
    Index,
    LawAudit,
    PairAudit,
    analyze_law,
    complete_link_groups,
    corpus_fingerprint,
    criterion_text,
    deduplicate,
    eligible_criteria,
)
from pipeline.llm import BudgetExceeded, InvalidModelResponse, ProviderError, SliceExpired
from pipeline.models import MatchAudit
from pipeline.store import digest, json_text, load_records, validate_store, write_json

logger = logging.getLogger(__name__)
VERSION = 'all-party-law-first-v1'


def retrieve(laws, criteria, programs, reading_text=None):
    """Shared law index; independent per-programme quotas; union, never party crowd-out."""
    reading_text = reading_text or {}
    texts = {law.id: law.title + ' ' + reading_text.get(law.id, ' '.join(p.text for p in law.passages))
             for law in laws if law.text_status == 'available'}
    reverse = Index(texts)
    chosen = {law.id: set() for law in laws}
    eligible = {law.id: {c.id for c in eligible_criteria(law, criteria, programs)} for law in laws}
    by_program = defaultdict(list)
    for criterion in criteria:
        by_program[criterion.program_id].append(criterion)
    for items in by_program.values():
        index = Index({c.id: criterion_text(c) for c in items})
        for law_id, text in texts.items():
            chosen[law_id].update(i for i in index.rank(text)[:12] if i in eligible[law_id])
            for offset in range(0, len(text), 6000):
                chosen[law_id].update(i for i in index.rank(text[offset:offset + 8000])[:2]
                                      if i in eligible[law_id])
        for criterion in items:
            for law_id in reverse.rank(criterion_text(criterion))[:3]:
                if criterion.id in eligible[law_id]:
                    chosen[law_id].add(criterion.id)
    return chosen, eligible


def safe_failure(error):
    if isinstance(error, SliceExpired):
        return {'type': 'slice_deadline', 'retryable': True}
    if isinstance(error, ProviderError):
        return {'type': 'provider', 'retryable': error.retryable, **error.safe_details()}
    if isinstance(error, InvalidModelResponse):
        return {'type': 'validation', 'retryable': True}
    if isinstance(error, BudgetExceeded):
        return {'type': 'budget', 'retryable': False}
    # Unknown programming/source errors cannot be retried blindly or hidden as no-link.
    return {'type': type(error).__name__, 'retryable': False}


def law_fingerprint(law):
    return digest(json_text({'title': law.official_title, 'date': str(law.published_at),
                            'text_status': law.text_status,
                            'passages': [p.model_dump() for p in law.passages]}))


def audit_signature(law, criteria_hash, candidates, model, review_model, *, legacy=False):
    if legacy:
        return digest(json_text({'version': LEGACY_VERSION,
            'law': law.model_dump(mode='json', exclude={'matching'}), 'criteria': criteria_hash,
            'candidates': candidates, 'model': model, 'review_model': review_model}))
    return digest(json_text({'version': VERSION, 'law': law_fingerprint(law),
        'criteria': criteria_hash, 'candidates': candidates, 'model': model, 'review_model': review_model}))


def run_slice(root: Path, agent, *, workers=8, seconds=1200, max_attempts=3, clock=time.time):
    if not 1 <= workers <= 16 or not 30 <= seconds <= 14400:
        raise ValueError('Workers 1–16 and slice duration 30–14400 seconds required')
    validate_store(root)
    cache = agent.cache.parent
    programs = load_records(root, 'live', 'programs')
    criteria = [c for c in load_records(root, 'live', 'criteria') if c.review.status != 'rejected']
    laws = sorted(load_records(root, 'live', 'laws'), key=lambda law: law.id)
    by_law, by_criterion = {law.id: law for law in laws}, {c.id: c for c in criteria}
    for program in programs:
        if {a.leaf_id for a in program.criteria_extraction} != {leaf.id for leaf in program.leaves}:
            raise ValueError(f'Programme extraction incomplete: {program.id}; complete it before freezing matching')
    if not programs or not laws:
        raise ValueError('No complete source corpus; do not report a successful empty backfill')
    reading_text = {}
    for law in laws:
        path = root / 'live/readings' / f'{law.id}.json'
        if path.exists():
            from pipeline.reading import ReadingEdition
            reading = ReadingEdition.model_validate_json(path.read_text())
            if reading.source_pdf_sha256 == law.source.sha256:
                reading_text[law.id] = '\n'.join(p.markdown for p in reading.pages)
    candidates, eligible = retrieve(laws, criteria, programs, reading_text)
    # Source fingerprints exclude mutable review/matching metadata. Editorial changes to
    # evidence/tests invalidate affected pairs, not unrelated parties or laws.
    law_hash = {law.id: law_fingerprint(law) for law in laws}
    criterion_hash = {c.id: corpus_fingerprint([c]) for c in criteria}
    input_signature = digest(json_text({'version': VERSION, 'laws': law_hash, 'criteria': criterion_hash,
        'programme_scope': [p.model_dump(mode='json', include={'id', 'published_at', 'period_start', 'period_end'})
                            for p in programs],
        'readings': {key: digest(value) for key, value in reading_text.items()},
        'model': agent.model, 'review_model': agent.review_model}))
    def pair_signature(law_id, criterion_id):
        return digest(':'.join([law_hash[law_id], criterion_hash[criterion_id], VERSION,
                                agent.model, agent.review_model]))
    state_path = cache / 'queue.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'version': VERSION, 'pairs': {}, 'attempts': {}, 'errors': {}, 'grouped': {}, 'slices': 0}
    if state['version'] != VERSION:
        raise ValueError('Queue version changed; explicit migration required')
    if state.get('input_signature') != input_signature:
        state['slices'] = 0  # Bound continuations per corpus, not across all future daily laws.
    state['input_signature'] = input_signature
    state['slices'] += 1
    # Previously published completed programme audits are reusable source-backed results.
    # Never let a new retrieval pass erase earlier candidates or political corrections.
    for directory in ('experiments', 'analyses'):
        for path in (root / 'live' / directory).glob('*.json'):
            report = Experiment.model_validate_json(path.read_text())
            items = [c for c in criteria if c.program_id == report.program_id]
            if report.criteria_sha256 != corpus_fingerprint(items):
                continue
            for audit in report.laws:
                if audit.law_id not in by_law:
                    continue
                expected = audit_signature(by_law[audit.law_id], report.criteria_sha256,
                    audit.candidate_ids, agent.model, agent.review_model, legacy=report.version == LEGACY_VERSION)
                if audit.analysis_sha256 != expected:
                    continue  # Editorial source changes must invalidate even a published audit.
                for pair in audit.pairs:
                    if pair.criterion_id not in eligible[audit.law_id]:
                        continue
                    candidates[audit.law_id].add(pair.criterion_id)
                    key = f'{audit.law_id}:{pair.criterion_id}'
                    state['pairs'].setdefault(key, {'signature': pair_signature(audit.law_id, pair.criterion_id),
                        'audit': pair.model_dump(mode='json'), 'origin': report.version})
            if report.version == LEGACY_VERSION and report.groups:
                state['grouped'].setdefault(report.program_id, {
                    'signature': report.criteria_sha256,
                    'groups': [g.model_dump() for g in report.groups],
                    'decisions': [d.model_dump(mode='json') for d in report.deduplication]})
    for key, saved in list(state['pairs'].items()):
        law_id, cid = key.split(':')
        if (law_id not in by_law or cid not in by_criterion or cid not in eligible[law_id]
                or saved['signature'] != pair_signature(law_id, cid)):
            del state['pairs'][key]
        elif cid in eligible[law_id]:
            candidates[law_id].add(cid)
    existing = {(i.law_id, i.criterion_id): i for i in load_records(root, 'live', 'impacts')}
    tasks = []
    for law in laws:
        pending = [i for i in sorted(candidates[law.id]) if f'{law.id}:{i}' not in state['pairs']]
        for offset in range(0, len(pending), 6):
            ids = pending[offset:offset + 6]
            identifier = law.id + '-' + digest(':'.join(pair_signature(law.id, i) for i in ids))[:20]
            tasks.append((identifier, law.id, ids))
    active_keys = {task[0] for task in tasks} | {'group:' + p.id for p in programs}
    state['errors'] = {key: value for key, value in state['errors'].items() if key in active_keys}
    state['attempts'] = {key: value for key, value in state['attempts'].items() if key in active_keys}
    complete_groups = all(state['grouped'].get(p.id, {}).get('signature') ==
                          corpus_fingerprint([c for c in criteria if c.program_id == p.id]) for p in programs)
    previous_progress = root / 'live/analysis/overview.json'
    if not tasks and complete_groups and previous_progress.exists():
        previous = json.loads(previous_progress.read_text())
        if previous.get('status') == 'completed' and previous.get('input_signature') == input_signature:
            return {**previous, 'automatic_continue': False}
    # A provider failure is isolated to a bounded batch, rather than a whole programme/law.
    # Complete all other work before retrying the failed batch. Backoff persists across slices.
    lock = Lock()
    stopped, paused, finished = Event(), Event(), Event()
    deadline = clock() + seconds
    agent.request_deadline = time.monotonic() + seconds
    total_pairs = sum(len(ids) for ids in candidates.values())
    progress_path = root / 'live/analysis/overview.json'
    status = {'status': 'running', 'version': VERSION, 'input_signature': input_signature, 'total_laws': len(laws),
              'total_programmes': len(programs), 'total_criteria': len(criteria),
              'candidate_pairs': total_pairs, 'retrieval': 'Per-programme whole-law/provision/reverse BM25 union',
              'limitations': 'Unselected pairs are unknown; retrieval recall is not measured. '
                             'Proposals are not human review, fulfilment or inferred votes.'}
    def persist():
        with lock:
            write_json(state_path, state)
            status.update({'updated_at': datetime.now(UTC).isoformat(), 'cost': agent.summary(),
                           'completed_pairs': len(state['pairs']), 'pending_pairs': total_pairs - len(state['pairs']),
                           'errors': state['errors'], 'slices': state['slices']})
            progress = []
            for program in programs:
                ids = {c.id for c in criteria if c.program_id == program.id}
                rows = []
                for law in laws:
                    selected = candidates[law.id] & ids
                    count = sum(f'{law.id}:{cid}' in state['pairs'] for cid in selected)
                    rows.append({'law_id': law.id, 'candidates': len(selected), 'completed': count,
                                 'status': 'needs_ocr' if law.text_status != 'available' else
                                           'completed' if count == len(selected) else 'pending',
                                 'omitted': len(eligible[law.id] & ids) - len(selected)})
                progress.append({'program_id': program.id, 'criteria': len(ids),
                    'laws_completed': sum(row['status'] == 'completed' for row in rows), 'laws': rows,
                    'grouping': 'completed' if state['grouped'].get(program.id, {}).get('signature') ==
                                corpus_fingerprint([c for c in criteria if c.id in ids]) else 'pending'})
            status['programmes'] = progress
            write_json(progress_path, status)
            logger.info('PROGRESS %s/%s pairs | %s tasks in error | $%.4f reported, $%.4f exposure',
                        len(state['pairs']), total_pairs, len(state['errors']),
                        status['cost']['reported_cost_usd'], status['cost']['budget_exposure_usd'])
    def heartbeat():
        while not finished.wait(45):
            persist()
    reporter = Thread(target=heartbeat, daemon=True)
    reporter.start()
    @lru_cache(maxsize=workers)
    def index(law_id):
        return Index({p.id: p.text for p in by_law[law_id].passages})
    def work(task):
        key, law_id, ids = task
        try:
            audit = analyze_law(by_law[law_id], [by_criterion[i] for i in ids], ids, len(ids),
                agent, existing, root, corpus_fingerprint([by_criterion[i] for i in ids]),
                checkpoint_id=key, write_law=False, passage_index=index(law_id))
            return task, audit, None
        except Exception as error:
            return task, None, safe_failure(error)
    try:
        persist()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = set()
            todo = list(tasks)
            while todo or pending:
                if clock() >= deadline or stopped.is_set() or paused.is_set():
                    todo = []  # In-flight calls settle; next slice resumes the rest.
                while todo and len(pending) < workers:
                    task = todo.pop(0)
                    key = task[0]
                    error = state['errors'].get(key, {})
                    if (state['attempts'].get(key, 0) >= max_attempts
                            or error.get('next_retry_at', 0) > clock()):
                        continue
                    with lock:
                        state['attempts'][key] = state['attempts'].get(key, 0) + 1
                    pending.add(pool.submit(work, task))
                if not pending:
                    break
                done, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
                for future in done:
                    (key, law_id, ids), audit, error = future.result()
                    with lock:
                        if error and error['type'] == 'slice_deadline':
                            state['attempts'][key] -= 1
                            paused.set()
                        elif error:
                            state['errors'][key] = {**error, 'law_id': law_id, 'criterion_ids': ids,
                                'attempts': state['attempts'][key], 'next_retry_at': clock() + 60 * 2 ** state['attempts'][key]}
                            if not error['retryable']:
                                stopped.set()
                        else:
                            state['errors'].pop(key, None)
                            for pair in audit.pairs:
                                state['pairs'][f'{law_id}:{pair.criterion_id}'] = {
                                    'signature': pair_signature(law_id, pair.criterion_id),
                                    'audit': pair.model_dump(mode='json'), 'origin': VERSION}
                    persist()
        # Grouping is independent of legal analysis and preserves party-owned source IDs.
        if not stopped.is_set() and not paused.is_set():
            for program in programs:
                if clock() >= deadline:
                    break
                items = [c for c in criteria if c.program_id == program.id]
                signature = corpus_fingerprint(items)
                key = 'group:' + program.id
                if state['grouped'].get(program.id, {}).get('signature') == signature:
                    state['errors'].pop(key, None)
                    continue
                if (state['attempts'].get(key, 0) >= max_attempts
                        or state['errors'].get(key, {}).get('next_retry_at', 0) > clock()):
                    continue
                state['attempts'][key] = state['attempts'].get(key, 0) + 1
                try:
                    groups, decisions = deduplicate(items, agent)
                    with lock:
                        state['grouped'][program.id] = {'signature': signature,
                            'groups': [g.model_dump() for g in groups],
                            'decisions': [d.model_dump(mode='json') for d in decisions]}
                        state['errors'].pop(key, None)
                except SliceExpired:
                    state['attempts'][key] -= 1
                    paused.set()
                    break
                except Exception as error:
                    failure = safe_failure(error)
                    with lock:
                        state['errors'][key] = {**failure, 'attempts': state['attempts'][key],
                            'next_retry_at': clock() + 60 * 2 ** state['attempts'][key]}
                    if not failure['retryable']:
                        stopped.set()
                        break
                persist()
        publish_reports(root, programs, laws, criteria, candidates, eligible, state, agent.summary())
        complete_groups = all(state['grouped'].get(p.id, {}).get('signature') ==
                              corpus_fingerprint([c for c in criteria if c.program_id == p.id]) for p in programs)
        incomplete = (len(state['pairs']) < total_pairs or not complete_groups
                      or any(law.text_status != 'available' for law in laws))
        # A quarantined batch cannot stop unrelated pending laws/programmes. Only stop
        # continuations when every remaining item has exhausted its own bounded attempts.
        actionable = any(state['attempts'].get(key, 0) < max_attempts
            and any(f'{law_id}:{cid}' not in state['pairs'] for cid in ids) for key, law_id, ids in tasks)
        actionable |= any(state['grouped'].get(p.id, {}).get('signature') !=
                          corpus_fingerprint([c for c in criteria if c.program_id == p.id])
                          and state['attempts'].get('group:' + p.id, 0) < max_attempts for p in programs)
        status['status'] = ('blocked' if stopped.is_set() else 'completed' if not incomplete
                            else 'continuing' if actionable else 'needs_attention')
        status['automatic_continue'] = status['status'] == 'continuing'
        persist()
        validate_store(root)
        return status
    finally:
        finished.set()
        reporter.join(timeout=10)
        persist()


def publish_reports(root, programs, laws, criteria, candidates, eligible, state, cost):
    for program in programs:
        items = [c for c in criteria if c.program_id == program.id]
        ids = {c.id for c in items}
        grouped = state['grouped'].get(program.id)
        if grouped and grouped['signature'] != corpus_fingerprint(items):
            grouped = None
        report = Experiment(program_id=program.id, version=VERSION,
            criteria_sha256=corpus_fingerprint(items), law_ids=[law.id for law in laws],
            processed_leaves=len(program.criteria_extraction), total_leaves=len(program.leaves),
            groups=grouped['groups'] if grouped else complete_link_groups(list(ids), []),
            deduplication=grouped['decisions'] if grouped else [], cost=cost,
            note=('Grouping completed as unreviewed proposals. ' if grouped else
                  'Grouping pending: singleton groups are not a deduplicated denominator. ') +
                 'All-party law-first screening. Unselected pairs are unknown; missing context is explicit. '
                 'Cost is shared across programmes, never sum it once per programme.')
        for law in laws:
            selected = sorted(candidates[law.id] & ids)
            pairs = [PairAudit.model_validate(state['pairs'][f'{law.id}:{cid}']['audit'])
                     for cid in selected if f'{law.id}:{cid}' in state['pairs']]
            report.laws.append(LawAudit(law_id=law.id,
                analysis_sha256=audit_signature(law, report.criteria_sha256, selected,
                                               cost['model'], cost['review_model']),
                status='needs_ocr' if law.text_status != 'available' else
                       'completed' if len(pairs) == len(selected) else 'partial',
                eligible_count=len(eligible[law.id] & ids), candidate_ids=selected,
                omitted_count=len(eligible[law.id] & ids) - len(selected), pairs=pairs))
        write_json(root / 'live/analyses' / f'{program.id}.json', report)
    for law in laws:
        completed = sum(f'{law.id}:{cid}' in state['pairs'] for cid in candidates[law.id])
        any_links = any(state['pairs'].get(f'{law.id}:{cid}', {}).get('audit', {}).get('impact_id')
                        for cid in candidates[law.id])
        law.matching = MatchAudit(status='needs_ocr' if law.text_status != 'available' else
            'pending' if completed != len(candidates[law.id]) else
            'no_candidates' if not candidates[law.id] else 'proposed' if any_links else 'no_supported_links',
            retrieval_version=VERSION, candidate_ids=sorted(candidates[law.id]), eligible_count=len(eligible[law.id]),
            omitted_count=len(eligible[law.id]) - len(candidates[law.id]),
            note=f'{completed}/{len(candidates[law.id])} selected pairs checked across all applicable programmes. '
                 'See /api/v1/live/analysis.json for per-programme coverage. Unselected pairs unknown.')
        write_json(root / 'live/laws' / f'{law.id}.json', law)
