"""Small, source-backed comparison, not a claim of Pareto efficiency or legal accuracy.

Runs the real extraction path on identical PDF paragraphs. Expected checks are not sent to models.
Outputs are review artifacts only, never written to the canonical dataset or marked human-reviewed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.catalog import load_catalog
from pipeline.documents import download, extract_pdf, pages_to_markdown
from pipeline.llm import Agent, ProviderError
from pipeline.models import Program, Source, TreeNode
from pipeline.programs import extract_criteria
from pipeline.store import ROOT, digest, load_records, save_record, validate_store, write_json

ALLOWED_MODELS = {'google/gemini-3.8-flash', 'anthropic/claude-sonnet-5.5', 'openai/gpt-5.6-luna'}
# Stable source IDs and page numbers, checked against the inspected official PDF edition.
CASES = [
    ('contents', 'gruene-2025-p-168d109017e0ae8b', 4, 'Inhaltsverzeichnis', True),
    ('rhetoric', 'gruene-2025-p-c8714e049b540476', 9, 'Präambel', True),
    ('status-quo', 'gruene-2025-p-d529a0fdad5d7ec8', 38, 'Klimaschutz', True),
    ('minimum-wage', 'gruene-2025-p-b67e3d1d8d1efdff', 67, 'Für gute Arbeit und faire Löhne', False),
    ('speed-limits', 'gruene-2025-p-f73bea62b99b208f', 48, 'Mobilität und Verkehrssicherheit', False),
    ('investment-fund', 'gruene-2025-p-197ea8ce4364cbe7', 36, 'Für einen Deutschlandfonds', False),
]
CONCEPTS = {
    'minimum-wage': {
        '15 Euro': r'\b15\s*(?:Euro|€)',
        'under-18 applicability': r'unter\s*18|Minderjähr|unter\s*achtzehn',
        '60-percent median reference': r'60\s*(?:Prozent|%).*Median|Median.*60\s*(?:Prozent|%)',
        'examination, not implementation, of funding criteria': r'Prüfung|geprüft|untersucht|Untersuchung',
    },
    'speed-limits': {'autobahn 130': r'\b130\b', 'municipal 30': r'\b30\b', 'rural 80': r'\b80\b'},
    'investment-fund': {'establish the fund': r'Deutschlandfonds'},
}


def prepare():
    catalog = load_catalog(ROOT / 'data')
    source = next(p for p in catalog.programs if p.id == 'gruene-2025')
    source.require_publication_basis()
    content = download(str(source.pdf_url))
    if digest(content) != source.sha256:
        raise ValueError('Programme changed; inspect the new edition before comparing models')
    pages = extract_pdf(content, textless_pages=set(source.textless_pages))
    markdown, all_leaves = pages_to_markdown(pages, source.id)
    by_id = {leaf.id: leaf for leaf in all_leaves}
    leaves, children = [], []
    for label, identifier, page, heading, _ in CASES:
        leaf = by_id[identifier]
        if leaf.reference.page != page:
            raise ValueError('Sample source location changed')
        leaves.append(leaf)
        children.append(TreeNode(id=f'sample-{label}', title=heading, leaf_ids=[leaf.id]))
    selected_ids = {leaf.id for leaf in leaves}
    children.append(TreeNode(id='sample-context', title='Nicht bewerteter Kontext der Stichprobe',
                             leaf_ids=[leaf.id for leaf in all_leaves if leaf.id not in selected_ids]))
    return source, catalog, markdown, all_leaves, children


def evaluate(model, prepared):
    source, catalog, markdown, leaves, children = prepared
    agent = Agent(cache=ROOT / '.cache' / 'model-evaluation' / 'llm', model=model, max_usd=0.50, max_calls=16)
    start = time.monotonic()
    output = {'model': model, 'status': 'failed'}
    try:
        with TemporaryDirectory(prefix='politrace-evaluation-') as tmp:
            root = Path(tmp)
            shutil.copy(ROOT / 'data' / 'parties.json', root / 'parties.json')
            md_path = f'live/programs/{source.id}.md'
            (root / md_path).parent.mkdir(parents=True)
            (root / md_path).write_text(markdown)
            program = Program(
                id=source.id, dataset='live', party_id=source.party_id,
                election_year=catalog.election_year, title=source.title,
                published_at=source.published, period_start=catalog.period_start,
                source=Source(url=source.pdf_url, title=source.title, publisher='BÜNDNIS 90/DIE GRÜNEN',
                              retrieved_at=date.today(), sha256=source.sha256,
                              license_note=source.rights.note),
                pdf_url=source.pdf_url, markdown_path=md_path, leaves=leaves,
                tree=TreeNode(id='sample-root', title=source.title, children=children),
                transcription_note='Evaluation sample only; NOT a full programme import.',
            )
            save_record(root, 'programs', program)
            extract_criteria(root=root, program_id=source.id, agent=agent, batch_size=6,
                             leaf_ids=[case[1] for case in CASES])
            validate_store(root)
            criteria = load_records(root, 'live', 'criteria')
            audits = load_records(root, 'live', 'programs')[0].criteria_extraction
            checks, samples = [], []
            for label, identifier, page, _, abstain in CASES:
                rows = [c for c in criteria if c.leaf_id == identifier]
                audit = next(a for a in audits if a.leaf_id == identifier)
                checks.append({'check': f'{label}: abstain/commitment',
                               'passed': not rows if abstain else bool(rows)})
                texts = [' '.join((c.title, c.description, c.test)) for c in rows]
                for name, pattern in CONCEPTS.get(label, {}).items():
                    checks.append({'check': f'{label}: {name}',
                                   'passed': any(bool(re.search(pattern, t, re.I | re.S)) for t in texts)})
                if label == 'minimum-wage':
                    checks.append({'check': 'minimum-wage: amount and eligibility are independently testable',
                                   'passed': len(rows) >= 6 and any(
                                       re.search(r'unter\s*18|Minderjähr', c.test, re.I)
                                       and not re.search(r'\b15\s*(?:Euro|€)', c.test, re.I) for c in rows)})
                if label == 'speed-limits':
                    checks.append({'check': 'speed-limits: no invented European fine baseline',
                                   'passed': not any(re.search(r'Bußgeld|Bussgeld', t, re.I) for t in texts)})
                checks.append({'check': f'{label}: no invented calendar date',
                               'passed': all(c.deadline is None for c in rows)})
                samples.append({'case': label, 'page': page, 'source_leaf_id': identifier,
                                'source_text': next(leaf.text for leaf in leaves if leaf.id == identifier),
                                'abstention_reason': audit.abstention_reason,
                                'criteria': [c.model_dump(mode='json') for c in rows]})
            output.update(status='completed', checks=checks, samples=samples,
                          gates_passed=all(c['passed'] for c in checks),
                          passed_checks=sum(c['passed'] for c in checks), total_checks=len(checks),
                          exact_citations_validated=True, criterion_count=len(criteria))
    except Exception as error:
        # Do not print arbitrary HTTP bodies/request headers or silently call a failed model a no-op.
        output.update(error_type=type(error).__name__)
        if isinstance(error, ProviderError):
            output.update(http_status=error.status_code, error_category=error.category)
    finally:
        output.update(budget=agent.summary(), elapsed_seconds=round(time.monotonic() - start, 2))
    return output


def main():
    config = json.loads((ROOT / '.github' / 'backfills' / 'model-evaluation.json').read_text())
    models = config.get('models', ['google/gemini-3.8-flash', 'anthropic/claude-sonnet-5.5'])
    if not 1 <= len(models) <= 2 or len(set(models)) != len(models) or not set(models) <= ALLOWED_MODELS:
        raise ValueError('Select one or two explicitly supported comparison models')
    prepared = prepare()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda model: evaluate(model, prepared), models))
    report = {'sample_version': 2, 'source_url': str(prepared[0].pdf_url),
              'source_sha256': prepared[0].sha256,
              'limitations': 'Six deliberately selected paragraphs from one programme, not a balanced benchmark. '
                            'Checks test citations, negative controls and selected commitment coverage; '
                            'regex coverage is not semantic equivalence or a precision/recall estimate. '
                            'Manual review of atomicity, conditions, wording and omissions is still required. '
                            'No legal-impact accuracy or general Pareto efficiency is established.',
              'results': results}
    write_json(ROOT / '.cache' / 'model-evaluation' / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(summary).open('a') as file:
            file.write('## Source-backed model comparison\n' + report['limitations'] + '\n\n')
            for result in results:
                file.write(f"- **{result['model']}**: {result['status']}; "
                           f"{result.get('passed_checks', 0)}/{result.get('total_checks', 0)} checks; "
                           f"provider-reported ${result['budget']['reported_cost_usd']:.6f}; "
                           f"{result['elapsed_seconds']} seconds.\n")
            file.write('\nFull quotations, proposed tests, failed checks and cost accounting are in the report artifact.\n')
    if any(result['status'] != 'completed' for result in results):
        raise SystemExit('Model evaluation failed; inspect the report, do not launch a blind bulk retry.')


if __name__ == '__main__':
    main()
