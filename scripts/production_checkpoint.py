"""Restore newest spending/results together; never silently use an older funded ledger."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from pipeline.store import ROOT, validate_store, write_json


def api(path):
    repo = os.environ['GITHUB_REPOSITORY']
    return json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/{path}']))


def merge_live(incoming: Path, target: Path):
    """Add results, never overwrite citizen-owned reviews/tests/source editions."""
    for source in sorted(incoming.rglob('*')):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(incoming)
        if source.name == '.gitkeep' and source.stat().st_size == 0:
            continue  # Old artifacts include harmless empty Git directory markers.
        if source.suffix not in ('.json', '.md') or '..' in relative.parts:
            raise ValueError('Unexpected file in generated data checkpoint')
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            shutil.copyfile(source, output)
            continue
        if output.read_bytes() == source.read_bytes() or source.suffix == '.md':
            continue
        collection = relative.parts[0]
        current, proposed = json.loads(output.read_text()), json.loads(source.read_text())
        if collection in ('programs', 'laws'):
            for field in ('source', 'leaves' if collection == 'programs' else 'passages'):
                if current.get(field) != proposed.get(field):
                    raise ValueError(f'Changed source at {relative}; do not overwrite editorial corrections')
            if collection == 'programs':
                audits = {a['leaf_id']: a for a in current.get('criteria_extraction', [])}
                for audit in proposed.get('criteria_extraction', []):
                    audits.setdefault(audit['leaf_id'], audit)
                current['criteria_extraction'] = list(audits.values())
            else:
                current['matching'] = proposed['matching']
            write_json(output, current)
        elif collection in ('experiments', 'analyses'):
            if current['criteria_sha256'] != proposed['criteria_sha256']:
                raise ValueError('Checkpoint analysis conflicts with the current criterion snapshot')
            # Published records win where both snapshots contain the same pair audit.
            audits = {a['law_id']: a for a in current['laws']}
            for audit in proposed['laws']:
                if audit['law_id'] not in audits or len(audit['pairs']) > len(audits[audit['law_id']]['pairs']):
                    audits[audit['law_id']] = audit
            proposed['laws'] = list(audits.values())
            write_json(output, proposed)
        elif collection in ('analysis', 'processing'):
            write_json(output, proposed)
        # Existing criteria, impacts, votes and reading editions remain untouched.


def main():
    if os.environ.get('GITHUB_RUN_ATTEMPT', '1') != '1':
        raise RuntimeError('Dispatch a new run to resume the newest ledger; never rerun a paid job from old state')
    config = json.loads((ROOT / '.github/production.json').read_text())
    current_id = int(os.environ['GITHUB_RUN_ID'])
    runs = api('actions/workflows/production.yml/runs?per_page=100')
    selected, name = None, 'production-checkpoint'
    for run in sorted(runs['workflow_runs'], key=lambda r: r['id'], reverse=True):
        if run['id'] >= current_id:
            continue
        if run['status'] != 'completed':
            raise RuntimeError('Another production run is still active; do not race its ledger')
        artifacts = api(f'actions/runs/{run["id"]}/artifacts')['artifacts']
        if any(a['name'] == name and not a['expired'] for a in artifacts):
            selected = run['id']
            break
        jobs = api(f'actions/runs/{run["id"]}/jobs')['jobs']
        if any(s['name'] == 'Process a bounded all-party slice' and s.get('started_at')
               and s.get('conclusion') != 'skipped' for j in jobs for s in j['steps']):
            raise RuntimeError('A paid run has no recoverable checkpoint; reconcile its ledger before resuming')
    if selected is None:
        if runs['total_count'] > 100:
            raise RuntimeError('No recent recoverable ledger; inspect expired checkpoint history before spending')
        selected = config.get('legacy_checkpoint_run')
        name = 'gruene-e2e-checkpoint'
        if not isinstance(selected, int) or selected <= 0:
            raise RuntimeError('Initial migration requires the last funded checkpoint; never reset prior spending')
        run = api(f'actions/runs/{selected}')
        if run['status'] != 'completed':
            # The repository-scoped CLI token may be read-only for Actions. The workflow's
            # actions:write token performs the one-time handoff, then waits for always-upload.
            subprocess.run(['gh', 'api', '--method', 'POST',
                f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{selected}/cancel'], check=True)
            for _ in range(60):
                time.sleep(5)
                if api(f'actions/runs/{selected}')['status'] == 'completed':
                    break
            else:
                raise RuntimeError('Legacy runner has not stopped; do not race its charge ledger')
    incoming = ROOT / '.cache/incoming'
    if incoming.exists():
        raise RuntimeError('Unexpected existing checkpoint restore directory')
    subprocess.run(['gh', 'run', 'download', str(selected), '--repo', os.environ['GITHUB_REPOSITORY'],
                    '--name', name, '--dir', str(incoming)], check=True)
    merge_live(incoming / 'data/live', ROOT / 'data/live')
    origin = incoming / '.cache' / ('e2e' if name == 'gruene-e2e-checkpoint' else 'production')
    if not (origin / 'budget.json').exists():
        raise RuntimeError('Restored checkpoint lacks its spending ledger')
    shutil.copytree(origin, ROOT / '.cache/production', dirs_exist_ok=True)
    # OCR usage/cache is also cumulative and separate from OpenRouter's invoice.
    if (incoming / '.cache/ocr').exists():
        shutil.copytree(incoming / '.cache/ocr', ROOT / '.cache/ocr', dirs_exist_ok=True)
    validate_store()
    print(f'Restored run {selected}: source results, validated responses and cumulative costs together')


if __name__ == '__main__':
    main()
