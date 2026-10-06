"""Resumable all-party queue with independent cheap screening and batched final decisions."""
from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from functools import lru_cache
from threading import Event, Lock, Thread

from pipeline.adjudication import (
    FINAL_MODEL,
    apply_decision,
    assess,
    assessment_context,
    assessment_signature,
    decide,
    screen,
)
from pipeline.experiment import (
    Experiment,
    Index,
    LawAudit,
    PairAudit,
    PairJudgment,
    batches,
    complete_link_groups,
    corpus_fingerprint,
    deduplicate,
)
from pipeline.models import MatchAudit
from pipeline.production import law_fingerprint, retrieve, safe_failure
from pipeline.store import digest, json_text, load_records, validate_store, write_json

logger = logging.getLogger(__name__)
VERSION = 'all-party-sol-final-v2'
LEGACY_VERSION = 'all-party-law-first-v1'


def migrate_budget(path, additional_usd, *, topups=()):
    """Apply explicit funding once per ID, never resetting charges or ordinary retry limits."""
    if not path.exists():
        raise ValueError('A retained ledger is required; never reset paid work')
    original = path.read_text()
    data = json.loads(original)
    snapshot = None
    if data['model'] != 'openai/gpt-6-luna':
        raise ValueError('Unexpected primary model in retained ledger')
    if data['review_model'] == FINAL_MODEL:
        if not any(m.get('id') == VERSION for m in data.get('migrations', [])):
            raise ValueError('Missing documented ledger transition')
    else:
        if (data['review_model'] != 'anthropic/claude-sonnet-5.5'
                or isinstance(additional_usd, bool) or not 0 < additional_usd <= 20):
            raise ValueError('Only the explicit Sonnet-to-Sol transition with up to $20 new budget is supported')
        exposure = data['reported_cost_usd'] + data['unknown_cost_reserved_usd'] + data['pending_reserved_usd']
        cap = exposure + additional_usd
        snapshot = path.with_name('budget-before-sol.json')
        data['migrations'] = [*data.get('migrations', []), {'id': VERSION, 'from_model': data['review_model'],
            'to_model': FINAL_MODEL, 'prior_reported_usd': data['reported_cost_usd'],
            'prior_exposure_usd': exposure, 'additional_budget_usd': additional_usd, 'cumulative_cap_usd': cap}]
        data['review_model'] = FINAL_MODEL
        data['max_usd'] = cap
        # Legacy totals cannot honestly be attributed to either old model after the fact.
        data.setdefault('breakdown', {})
    cap = data['max_usd']
    if (not isinstance(cap, (int, float)) or isinstance(cap, bool)
            or not math.isfinite(cap) or not 0 < cap <= 100):
        raise ValueError('Invalid cumulative cap or global safeguard exceeded')
    if not isinstance(topups, (list, tuple)):
        raise ValueError('Budget top-ups must be an explicit list')
    seen, added = set(), []
    for topup in topups:
        if not isinstance(topup, dict) or set(topup) != {'id', 'additional_budget_usd'}:
            raise ValueError('A budget top-up requires an ID and additional_budget_usd')
        identifier, amount = topup['id'], topup['additional_budget_usd']
        if (not isinstance(identifier, str) or not re.fullmatch(r'budget-topup-[a-z0-9-]{1,64}', identifier)
                or identifier in seen):
            raise ValueError('Budget top-up IDs must be unique and use the budget-topup- prefix')
        seen.add(identifier)
        if (not isinstance(amount, (int, float)) or isinstance(amount, bool)
                or not math.isfinite(amount) or not 0 < amount <= 100):
            raise ValueError('Budget top-up amount must be finite and positive, at most $100')
        applied = [m for m in data['migrations'] if m.get('id') == identifier]
        if applied:
            if (len(applied) != 1 or applied[0].get('kind') != 'budget_topup'
                    or applied[0].get('additional_budget_usd') != amount):
                raise ValueError('An applied budget top-up is immutable; use a new ID for new funding')
            continue
        previous_cap = cap
        cap += amount
        if cap > 100:
            raise ValueError('Cumulative cap exceeds the global safeguard')
        entry = {'id': identifier, 'kind': 'budget_topup', 'additional_budget_usd': amount,
                 'previous_cap_usd': previous_cap, 'cumulative_cap_usd': cap}
        data['migrations'].append(entry)
        added.append(entry)
    data['max_usd'] = cap
    # Validate every allocation before any write. Repeating a funded continuation is a no-op;
    # removing an allocation from config cannot remove its durable record or re-add it later.
    if data != json.loads(original):
        if snapshot is not None and not snapshot.exists():
            write_json(snapshot, json.loads(original))
        write_json(path, data)
        for entry in added:
            logger.info('Applied %s once: +$%.2f; cumulative cap $%.4f; prior charges/reservations retained',
                        entry['id'], entry['additional_budget_usd'], entry['cumulative_cap_usd'])
    return cap


def pair_signature(law, criterion, *, version=VERSION, reviewer=FINAL_MODEL):
    return digest(':'.join([law_fingerprint(law), corpus_fingerprint([criterion]), version,
                           'openai/gpt-6-luna', reviewer]))


def signature_factory(laws, criteria):
    law_hashes = {key: law_fingerprint(value) for key, value in laws.items()}
    criterion_hashes = {key: corpus_fingerprint([value]) for key, value in criteria.items()}
    def signature(lid, cid, *, version=VERSION, reviewer=FINAL_MODEL):
        return digest(':'.join([law_hashes[lid], criterion_hashes[cid], version,
                               'openai/gpt-6-luna', reviewer]))
    return signature


def load_state(path, laws, criteria, existing, signature=None):
    signature = signature or signature_factory(laws, criteria)
    old = json.loads(path.read_text()) if path.exists() else None
    state = old if old and old['version'] == VERSION else {
        'version': VERSION, 'pairs': {}, 'drafts': {}, 'grouped': {}, 'attempts': {},
        'errors': {}, 'slices': 0}
    if old and old['version'] not in (VERSION, LEGACY_VERSION):
        raise ValueError('Unexpected queue version; explicit migration required')
    if old and old['version'] == LEGACY_VERSION:
        snapshot = path.with_name('queue-before-sol.json')
        if not snapshot.exists():
            write_json(snapshot, old)
        state['grouped'] = old['grouped']
        for key, saved in old['pairs'].items():
            lid, cid = key.split(':')
            if lid not in laws or cid not in criteria:
                continue
            if saved['signature'] != signature(lid, cid, version=LEGACY_VERSION,
                                                    reviewer='anthropic/claude-sonnet-5.5'):
                continue
            audit = PairAudit.model_validate(saved['audit'])
            row = {'signature': signature(lid, cid),
                   'audit': audit.model_dump(mode='json'), 'origin': 'retained-luna-screen'}
            if audit.impact_id or audit.disposition in ('proposed_link', 'preserved_link'):
                state['drafts'][key] = row  # Old Sonnet agreement/disagreement is NOT a final decision.
            else:
                state['pairs'][key] = row
    # Published initial pilot links may predate the queue. Bring all of them through Sol once.
    for (lid, cid), impact in existing.items():
        if lid not in laws or cid not in criteria or impact.review.status != 'proposed':
            continue
        key = f'{lid}:{cid}'
        if key in state['pairs'] or key in state['drafts']:
            continue
        draft = PairAudit(criterion_id=cid, disposition='proposed_link', rationale=impact.rationale,
            input_sha256=impact.generation[0].input_sha256, generation=impact.generation[:1],
            judgment=PairJudgment(criterion_id=cid, disposition='proposed_link', supported=True,
                score=impact.score, confidence=impact.confidence, rationale=impact.rationale,
                law_passage_id=impact.law_passage_id, law_quote=impact.law_quote,
                criterion_quote=impact.criterion_quote, caveats=[]))
        state['drafts'][key] = {'signature': signature(lid, cid),
                              'audit': draft.model_dump(mode='json'), 'origin': 'retained-published-link'}
    for collection in ('pairs', 'drafts'):
        for key, row in list(state[collection].items()):
            lid, cid = key.split(':')
            if (lid not in laws or cid not in criteria or row['signature'] != signature(lid, cid)):
                del state[collection][key]
                continue
            if collection == 'drafts' and not row['audit'].get('judgment'):
                impact = existing.get((lid, cid))
                if impact is None:
                    del state[collection][key]
                    continue
                row['audit']['judgment'] = PairJudgment(criterion_id=cid, disposition='proposed_link',
                    supported=True, score=impact.score, confidence=impact.confidence,
                    rationale=impact.rationale, law_passage_id=impact.law_passage_id,
                    law_quote=impact.law_quote, criterion_quote=impact.criterion_quote, caveats=[]).model_dump()
    return state


def run_final_slice(root, agent, *, workers=8, seconds=600, max_attempts=3, clock=time.time):
    if agent.model != 'openai/gpt-6-luna' or agent.review_model != FINAL_MODEL or not agent.flex:
        raise ValueError('Production requires Luna Flex screening and Sol Flex final evaluation')
    if not 1 <= workers <= 16 or not 30 <= seconds <= 14400:
        raise ValueError('Invalid worker/time bounds')
    validate_store(root)
    programs = load_records(root, 'live', 'programs')
    criteria = [c for c in load_records(root, 'live', 'criteria') if c.review.status != 'rejected']
    laws = sorted(load_records(root, 'live', 'laws'), key=lambda law: law.id)
    by_law, by_criterion = {law.id: law for law in laws}, {c.id: c for c in criteria}
    if not programs or not laws:
        raise ValueError('Missing source corpus')
    for program in programs:
        if {a.leaf_id for a in program.criteria_extraction} != {leaf.id for leaf in program.leaves}:
            raise ValueError(f'Programme extraction incomplete: {program.id}')
    reading_text = {}
    for law in laws:
        path = root / 'live/readings' / f'{law.id}.json'
        if path.exists():
            reading = json.loads(path.read_text())
            if reading['source_pdf_sha256'] == law.source.sha256:
                reading_text[law.id] = '\n'.join(p['markdown'] for p in reading['pages'])
    candidates, eligible = retrieve(laws, criteria, programs, reading_text)
    existing = {(i.law_id, i.criterion_id): i for i in load_records(root, 'live', 'impacts')}
    cache = agent.cache.parent
    state_path = cache / 'queue.json'
    signature = signature_factory(by_law, by_criterion)
    state = load_state(state_path, by_law, by_criterion, existing, signature)
    for collection in ('pairs', 'drafts'):
        for key in list(state[collection]):
            lid, cid = key.split(':')
            if cid not in eligible[lid]:
                del state[collection][key]
            else:
                candidates[lid].add(cid)
    signatures = {f'{law.id}:{cid}': signature(law.id, cid)
                  for law in laws for cid in candidates[law.id]}
    corpus = digest(json_text({'version': VERSION, 'signatures': signatures}))
    if state.get('input_signature') != corpus:
        state['slices'] = 0
    state['input_signature'] = corpus
    state['slices'] += 1
    state['drafts'] = state.get('drafts', {})
    deadline = clock() + seconds
    agent.request_deadline = time.monotonic() + seconds
    lock, done, halted = Lock(), Event(), Event()
    progress_path = root / 'live/analysis/overview.json'
    status = {'version': VERSION, 'status': 'running', 'input_signature': corpus,
              'total_laws': len(laws), 'total_programmes': len(programs), 'total_criteria': len(criteria),
              'candidate_pairs': len(signatures), 'final_model': FINAL_MODEL,
              'retrieval': 'Per-programme whole-law/provision/reverse BM25 union',
              'limitations': 'Unselected pairs unknown; statistical recall not measured.'}
    def persist():
        with lock:
            write_json(state_path, state)
            status.update(updated_at=datetime.now(UTC).isoformat(), cost=agent.summary(),
                completed_pairs=len(state['pairs']), screened_pairs=len(state['pairs']) + len(state['drafts']),
                pending_pairs=len(signatures) - len(state['pairs']), final_pending=len(state['drafts']),
                errors=state['errors'], slices=state['slices'])
            status['programmes'] = []
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
                status['programmes'].append({'program_id': program.id, 'criteria': len(ids),
                    'laws_completed': sum(r['status'] == 'completed' for r in rows), 'laws': rows,
                    'grouping': 'completed' if state['grouped'].get(program.id, {}).get('signature') ==
                        corpus_fingerprint([c for c in criteria if c.id in ids]) else 'pending'})
            write_json(progress_path, status)
            logger.info('PROGRESS %s/%s final/screened outcomes; %s drafts waiting for Sol; $%.4f reported',
                        len(state['pairs']), len(signatures), len(state['drafts']), status['cost']['reported_cost_usd'])
    def heartbeat():
        while not done.wait(45):
            persist()
    reporter = Thread(target=heartbeat, daemon=True)
    reporter.start()
    @lru_cache(maxsize=workers)
    def index(lid):
        return Index({p.id: p.text for p in by_law[lid].passages})
    def task_key(stage, lid, ids):
        return stage + ':' + lid + ':' + digest(':'.join(signatures[f'{lid}:{cid}'] for cid in ids))[:20]
    def available(key):
        return (state['attempts'].get(key, 0) < max_attempts
                and state['errors'].get(key, {}).get('next_retry_at', 0) <= clock())
    def execute(tasks, worker, apply):
        tasks = [t for t in tasks if available(t[0])]
        finished_count = 0
        for chunk in batches(tasks, workers):
            if halted.is_set() or clock() >= deadline:
                break
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending = {}
                for task in chunk:
                    with lock:
                        state['attempts'][task[0]] = state['attempts'].get(task[0], 0) + 1
                    pending[pool.submit(worker, task)] = task
                for future in as_completed(pending):
                    task = pending[future]
                    try:
                        # Workers return generators; execute in the worker, never while holding the queue lock.
                        results = future.result()
                        with lock:
                            apply(task, results)
                            state['errors'].pop(task[0], None)
                        finished_count += 1
                    except Exception as error:
                        failure = safe_failure(error)
                        with lock:
                            if failure['type'] == 'slice_deadline':
                                state['attempts'][task[0]] -= 1
                            else:
                                state['errors'][task[0]] = {**failure, 'stage': task[0].split(':')[0],
                                    'attempts': state['attempts'][task[0]],
                                    'next_retry_at': clock() + 60 * 2 ** state['attempts'][task[0]]}
                                if not failure['retryable']:
                                    halted.set()
                        logger.warning('Deferred task %s: %s', task[0], failure)
                    persist()
        return finished_count
    def screen_tasks():
        tasks = []
        for law in laws:
            ids = [cid for cid in sorted(candidates[law.id])
                   if f'{law.id}:{cid}' not in state['pairs'] and f'{law.id}:{cid}' not in state['drafts']]
            for part in batches(ids, 16):
                tasks.append((task_key('screen', law.id, part), law.id, part))
        return tasks
    def review_tasks():
        by_id = defaultdict(list)
        for key in sorted(state['drafts']):
            lid, cid = key.split(':')
            by_id[lid].append(cid)
        return [(task_key('final', lid, part), lid, part) for lid, ids in by_id.items() for part in batches(ids, 12)]
    def screening_worker(task):
        _, lid, ids = task
        return list(screen(by_law[lid], [by_criterion[cid] for cid in ids], agent, index(lid)))
    def screened(task, results):
        _, lid, _ = task
        for audit in results:
            key = f'{lid}:{audit.criterion_id}'
            target = 'drafts' if audit.disposition == 'proposed_link' else 'pairs'
            state[target][key] = {'signature': signatures[key], 'audit': audit.model_dump(mode='json'), 'origin': VERSION}
    def final_worker(task):
        _, lid, ids = task
        drafts = {cid: PairAudit.model_validate(state['drafts'][f'{lid}:{cid}']['audit']) for cid in ids}
        return list(decide(by_law[lid], [by_criterion[cid] for cid in ids], drafts, agent, index(lid)))
    def decided(task, results):
        _, lid, _ = task
        for final, generation in results:
            cid, key = final.criterion_id, f'{lid}:{final.criterion_id}'
            draft = PairAudit.model_validate(state['drafts'][key]['audit'])
            audit = apply_decision(root, by_law[lid], by_criterion[cid], draft, final, generation, existing)
            state['pairs'][key] = {'signature': signatures[key], 'audit': audit.model_dump(mode='json'), 'origin': VERSION}
            del state['drafts'][key]
    def assessment_tasks():
        ids = []
        for c in criteria:
            if c.review.status == 'rejected' or (c.assessment.method == 'editorial' and c.assessment.status != 'unassessed'):
                continue
            context = assessment_context(c, existing.values(), by_law)
            if context['effects'] and c.assessment.input_sha256 != assessment_signature(context):
                ids.append(c.id)
        return [('overall:' + digest(json_text([assessment_context(by_criterion[i], existing.values(), by_law)
                                               for i in part]))[:20], '', part) for part in batches(ids, 8)]
    def overall_worker(task):
        return list(assess([by_criterion[cid] for cid in task[2]], list(existing.values()), by_law, agent))
    def assessed(task, results):
        for cid, value in results:
            by_criterion[cid].assessment = value
            write_json(root / 'live/criteria' / f'{cid}.json', by_criterion[cid])
    try:
        persist()
        while clock() < deadline and not halted.is_set():
            count = execute(review_tasks()[:workers * 2], final_worker, decided)
            count += execute(assessment_tasks(), overall_worker, assessed)
            # Frequent alternation accumulates drafts across cheap batches but never holds them until
            # all 40k candidate pairs finish. Each cycle publishes final data plus its synthesis.
            ready = [t for t in screen_tasks() if available(t[0])][:workers * 8]
            count += execute(ready, screening_worker, screened)
            if not count:
                break
        if not halted.is_set() and clock() < deadline:
            execute(review_tasks(), final_worker, decided)
            execute(assessment_tasks(), overall_worker, assessed)
            for program in programs:
                if clock() >= deadline or halted.is_set():
                    break
                items = [c for c in criteria if c.program_id == program.id]
                sig = corpus_fingerprint(items)
                if state['grouped'].get(program.id, {}).get('signature') == sig:
                    continue
                key = 'group:' + program.id + ':' + sig[:20]
                def group_worker(_):
                    return deduplicate(items, agent)
                def grouped(_, result):
                    groups, decisions = result
                    state['grouped'][program.id] = {'signature': sig,
                        'groups': [g.model_dump() for g in groups],
                        'decisions': [d.model_dump(mode='json') for d in decisions]}
                execute([(key, '', [])], group_worker, grouped)
        remaining = [*screen_tasks(), *review_tasks(), *assessment_tasks()]
        groups_pending = [p for p in programs if state['grouped'].get(p.id, {}).get('signature') !=
                          corpus_fingerprint([c for c in criteria if c.program_id == p.id])]
        active = {t[0] for t in remaining} | {'group:' + p.id + ':' + corpus_fingerprint(
                    [c for c in criteria if c.program_id == p.id])[:20] for p in groups_pending}
        state['errors'] = {k: v for k, v in state['errors'].items() if k in active}
        actionable = any(state['attempts'].get(k, 0) < max_attempts for k in active)
        status['status'] = ('blocked' if halted.is_set() else 'completed' if not active
                            else 'continuing' if actionable else 'needs_attention')
        if any(law.text_status != 'available' for law in laws) and status['status'] == 'completed':
            status['status'] = 'needs_attention'
        status['automatic_continue'] = status['status'] == 'continuing'
        status['pending_assessments'] = sum(len(t[2]) for t in remaining if t[0].startswith('overall:'))
        persist()
        publish(root, programs, laws, criteria, candidates, eligible, state, agent.summary())
        validate_store(root)
        return status
    finally:
        done.set()
        reporter.join(timeout=10)
        persist()


def publish(root, programs, laws, criteria, candidates, eligible, state, cost):
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
            note='Luna screening; batched Sol final evaluations. Cost shared across all programmes. '
                 'Old proposed_link enum is retained for API compatibility; final provenance identifies decisions.')
        for law in laws:
            selected = sorted(candidates[law.id] & ids)
            pairs = [PairAudit.model_validate(state['pairs'][f'{law.id}:{cid}']['audit'])
                     for cid in selected if f'{law.id}:{cid}' in state['pairs']]
            report.laws.append(LawAudit(law_id=law.id, analysis_sha256=digest(json_text({
                'version': VERSION, 'law': law_fingerprint(law), 'criteria': report.criteria_sha256,
                'candidates': selected})),
                status='needs_ocr' if law.text_status != 'available' else
                       'completed' if len(pairs) == len(selected) else 'partial',
                eligible_count=len(eligible[law.id] & ids), candidate_ids=selected,
                omitted_count=len(eligible[law.id] & ids) - len(selected), pairs=pairs))
        write_json(root / 'live/analyses' / f'{program.id}.json', report)
    for law in laws:
        completed = sum(f'{law.id}:{cid}' in state['pairs'] for cid in candidates[law.id])
        law.matching = MatchAudit(status='needs_ocr' if law.text_status != 'available' else
            'pending' if completed < len(candidates[law.id]) else 'no_candidates' if not candidates[law.id]
            else 'proposed' if any(state['pairs'].get(f'{law.id}:{cid}', {}).get('audit', {}).get('disposition')
                                   in ('proposed_link', 'preserved_link') for cid in candidates[law.id])
            else 'no_supported_links', retrieval_version=VERSION, candidate_ids=sorted(candidates[law.id]),
            eligible_count=len(eligible[law.id]), omitted_count=len(eligible[law.id]) - len(candidates[law.id]),
            note=f'{completed}/{len(candidates[law.id])} candidates processed. Final accepted links carry Sol provenance.')
        write_json(root / 'live/laws' / f'{law.id}.json', law)
