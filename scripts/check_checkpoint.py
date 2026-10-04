"""Refuse stale/missing paid-run ledgers before any model request (GitHub CLI only)."""
import json
import os
import subprocess


def check(history, api, *, current, resume, target):
    if history['total_count'] > 100:
        raise RuntimeError('Paginate history before establishing spending safety')
    for run in history['workflow_runs']:
        if not resume < run['id'] < current:
            continue
        jobs = api(f'actions/runs/{run["id"]}/jobs')['jobs']
        relevant = [job for job in jobs if job['name'] == f'import ({target})']
        if any(job['status'] != 'completed' for job in relevant):
            raise RuntimeError('Another source attempt may be spending; wait for its checkpoint')
        artifacts = api(f'actions/runs/{run["id"]}/artifacts')['artifacts']
        if any(a['name'] == f'programme-checkpoint-{target}' for a in artifacts):
            raise RuntimeError('A newer source ledger exists; resume that run')
        if any(step['name'] == 'Import source and extract every leaf' and step.get('started_at')
               and step.get('conclusion') != 'skipped' for job in relevant for step in job['steps']):
            raise RuntimeError('Paid work may have started without a retained ledger; reconcile first')


if __name__ == '__main__':
    def api(path):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{os.environ["GITHUB_REPOSITORY"]}/' + path]))
    check(api('actions/workflows/programmes.yml/runs?per_page=100'), api,
          current=int(os.environ['GITHUB_RUN_ID']), resume=int(os.environ.get('RESUME_RUN') or 0),
          target=os.environ['PROGRAMME_TARGET'])
