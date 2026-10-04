"""One cumulative $25 experiment. No independent probe, uncapped fallback or automatic publication."""
import json
import logging
import os
from pathlib import Path

from pipeline.llm import Agent, ProviderError
from pipeline.programs import extract_criteria
from pipeline.store import ROOT, load_records, validate_store, write_json


def main():
    request = json.loads((ROOT / '.github/experiments/gruene-luna.json').read_text())
    if request['experiment'] != 'gruene-luna-flex-v1' or request['max_usd'] != 25:
        raise ValueError('This experiment has a fixed $25 cumulative authorization')
    if os.environ.get('GITHUB_RUN_ATTEMPT', '1') != '1':
        raise ValueError('Resume from the last checkpoint in a new request; never reset spending on job rerun')
    ledger = ROOT / '.cache/e2e/budget.json'
    if request.get('resume_run') and not ledger.exists():
        raise ValueError('Missing cumulative ledger: refuse paid work without the previous checkpoint')
    validate_store()
    agent = Agent(cache=ROOT / '.cache/e2e/llm', model='openai/gpt-6-luna',
                  max_usd=25, max_calls=2000, flex=True, ledger=ledger)
    result = {'experiment': request['experiment'], 'phase': request['phase'],
              'status': 'running', 'provider': agent.key_status()}
    try:
        result['criteria'] = extract_criteria(root=ROOT / 'data', program_id='gruene-2025',
            agent=agent, batch_size=4, workers=4, checkpoint=True, strong_fallback=True)
        validate_store()
        if request['phase'] == 'all':
            from pipeline.experiment import analyse
            result['analysis'] = analyse(root=ROOT / 'data', agent=agent, program_id='gruene-2025')
        elif request['phase'] != 'criteria':
            raise ValueError('Unknown experiment phase')
        result['status'] = 'completed'
        result['validation'] = validate_store()
    except Exception as error:
        result['status'] = 'failed'
        result['error_type'] = type(error).__name__
        if isinstance(error, ProviderError):
            result['provider_error'] = error.safe_details()
        raise
    finally:
        program = next(p for p in load_records(ROOT / 'data', 'live', 'programs') if p.id == 'gruene-2025')
        result['processed_leaves'] = len(program.criteria_extraction)
        result['total_leaves'] = len(program.leaves)
        result['budget'] = agent.summary()
        write_json(ROOT / '.cache/e2e/result.json', result)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(summary).open('a') as f:
                f.write('\n## Cumulative experiment result\n```json\n' + rendered + '\n```\n')


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    logging.getLogger('pipeline').setLevel(logging.INFO)
    main()
