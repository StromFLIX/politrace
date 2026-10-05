"""A short, independently resumable production slice. GitHub handles continuation."""
import json
import logging
import os
from pathlib import Path

from pipeline.llm import Agent
from pipeline.production import run_slice
from pipeline.store import ROOT, write_json


def main():
    config = json.loads((ROOT / '.github/production.json').read_text())
    cache = ROOT / '.cache/production'
    if config['model'] != 'openai/gpt-6-luna' or config['provider'] != 'openai/flex':
        raise ValueError('Change and test the model/price contract explicitly, not through a silent route fallback')
    os.environ['OPENROUTER_REVIEW_MODEL'] = config['review_model']
    agent = Agent(cache=cache / 'llm', model=config['model'], max_usd=config['max_usd'],
                  max_calls=10000, flex=True, ledger=cache / 'budget.json')
    result = run_slice(ROOT / 'data', agent, workers=config['workers'], seconds=config['slice_seconds'])
    write_json(cache / 'result.json', result)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(summary).open('a') as f:
            f.write(f'## All-party data processing\n\nStatus: **{result["status"]}**\n\n'
                    f'{result["completed_pairs"]}/{result["candidate_pairs"]} candidate pairs. '
                    f'Reported cost: ${result["cost"]["reported_cost_usd"]:.4f}. '
                    'No automatic human approvals. See the checkpoint artifact for every pending/error ID.\n')
    if output := os.environ.get('GITHUB_OUTPUT'):
        with Path(output).open('a') as f:
            f.write('continue=' + str(result['automatic_continue']).lower() + '\n')
            f.write('status=' + result['status'] + '\n')
    if result['status'] in ('blocked', 'needs_attention'):
        raise SystemExit('Explicit unresolved provider/budget/validation state; checkpoint retained')


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
    logging.getLogger('pipeline').setLevel(logging.INFO)
    main()
