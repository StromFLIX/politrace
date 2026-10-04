"""Resumable, attributed programme transcriptions and complete criteria, one ledger per source.

The source terms remain unchanged. Importing a transcription does not grant an open licence,
authorise downstream reuse, approve the extraction or attribute permission to any person.
"""
import json
import logging
import os
from pathlib import Path

from pipeline.catalog import load_catalog
from pipeline.llm import Agent, ProviderError
from pipeline.programs import extract_criteria, ingest_program
from pipeline.store import ROOT, load_records, validate_store, write_json

TARGETS = {'cdu-csu-2025', 'spd-2025', 'afd-2025', 'linke-2025', 'ssw-2025'}


def run(target, request, *, root=ROOT / 'data', agent=None):
    if target not in TARGETS or request['source_mode'] != 'attributed-transcription':
        raise ValueError('Explicit catalogue scope and transcription mode required')
    catalog = load_catalog(root)
    source = next(p for p in catalog.programs if p.id == target)
    if not source.published:
        raise ValueError('Inspect and document programme/edition date before importing')
    validate_store(root)
    agent = agent or Agent(cache=ROOT / '.cache/programmes' / target / 'llm',
        ledger=ROOT / '.cache/programmes' / target / 'budget.json',
        model='openai/gpt-6-luna', flex=True, max_calls=2000, max_usd=5)
    existing = {p.id: p for p in load_records(root, 'live', 'programs')}
    result = {'program_id': target, 'status': 'running'}
    try:
        if target in existing:
            if existing[target].source.sha256 != source.sha256:
                raise ValueError('Edition changed: preserve the original and inspect the new source')
        else:
            # Keep actual terms; neither invent a licence nor claim publisher/user permission.
            terms = f'{source.rights.note} Source terms: {source.rights.terms_url}.'
            if source.rights.license_url:
                terms += f' Licence: {source.rights.license_url}.'
            result['tree'] = ingest_program(root=root, agent=agent, program_id=target,
                party=source.party_id, year=catalog.election_year, title=source.title,
                pdf=str(source.pdf_url), source_url=str(source.pdf_url), published=source.published,
                period_start=catalog.period_start, period_end=None, expected_sha256=source.sha256,
                textless_pages=source.textless_pages,
                transcription_note=source.transcription_note + ' ' + source.publication_note,
                license_note=terms)
            validate_store(root)
        result['criteria'] = extract_criteria(root=root, program_id=target, agent=agent,
            batch_size=4, workers=4, checkpoint=True, strong_fallback=True)
        result['validation'] = validate_store(root)
        result['status'] = 'completed'
        return result
    except Exception as error:
        result.update(status='failed', error_type=type(error).__name__)
        if isinstance(error, ProviderError):
            result['provider_error'] = error.safe_details()
        raise
    finally:
        result['budget'] = agent.summary()
        programs = {p.id: p for p in load_records(root, 'live', 'programs')}
        if target in programs:
            program = programs[target]
            result.update(processed_leaves=len(program.criteria_extraction), total_leaves=len(program.leaves))
        path = ROOT / '.cache/programmes' / target / 'result.json'
        write_json(path, result)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(summary).open('a') as stream:
                stream.write('\n## Programme checkpoint\n```json\n' + rendered + '\n```\n')


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    logging.getLogger('pipeline').setLevel(logging.INFO)
    request = json.loads((ROOT / '.github/backfills/programmes.json').read_text())
    target = os.environ['PROGRAMME_TARGET']
    if os.environ.get('GITHUB_RUN_ATTEMPT', '1') != '1':
        raise ValueError('Use a new checkpoint continuation; paid job reruns cannot reset the ledger')
    if request['resume_runs'].get(target) and not (ROOT / '.cache/programmes' / target / 'budget.json').exists():
        raise ValueError('Missing retained spending ledger; refuse paid work')
    run(target, request)
