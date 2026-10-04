"""Recover the full source product without a model request or an OpenRouter secret.

Reuses source-validated outline cache entries. Unfinished blocks keep exact source text
under explicitly unfinished PDF-page branches; this is NOT a completed AI outline.
"""
import json
import logging
import os
from pathlib import Path

from pipeline.catalog import load_catalog
from pipeline.llm import Agent
from pipeline.models import Generation
from pipeline.programs import StructuredParagraphs, ingest_program
from pipeline.store import ROOT, digest, json_text, load_records, validate_store, write_json


class CachedOutlineAgent(Agent):
    def __init__(self, *, cache, model=None):
        super().__init__(cache=cache, model=model)
        self.cached_blocks = 0
        self.fallback_blocks = 0

    def ask(self, task, data, schema, *, review=False, validator=None, max_output=7000, subdivide=False):
        if schema is not StructuredParagraphs or review:
            raise ValueError('Offline recovery supports outline structure only, never criteria or legal judgments')
        *_, provenance, path = self._request_context(task, data, schema, max_output=max_output)
        cached = self._read_cached(path, schema, validator)
        if cached is not None:
            self.cache_hits += 1
            self.cached_blocks += len(data['blocks'])
            return cached, provenance
        # Do not infer a missing semantic section from the previous chunk, or pretend the
        # deterministic grouping came from a paid model. Every unfinished block stays visible.
        groups = [dict(start=block['index'], end=block['index'],
                       sections=['Strukturierung noch offen', f"PDF-Seite {block['page']}"])
                  for block in data['blocks']]
        result = StructuredParagraphs(groups=groups)
        if validator:
            validator(result)
        self.fallback_blocks += len(data['blocks'])
        return result, Generation(model='politrace/source-block-recovery',
            prompt_version='source-block-recovery-v1', input_sha256=digest(json_text(data)))


def run(target='gruene-2025', *, root=ROOT / 'data', cache=ROOT / '.cache/llm'):
    validate_store(root)
    catalog = load_catalog(root)
    source = next((item for item in catalog.programs if item.id == target), None)
    if source is None:
        raise ValueError('Unknown programme in the checked source inventory')
    source.require_publication_basis()
    agent = CachedOutlineAgent(cache=cache)
    result = ingest_program(root=root, agent=agent, program_id=target, party=source.party_id,
        year=catalog.election_year, title=source.title, pdf=str(source.pdf_url),
        source_url=str(source.pdf_url), published=source.published, period_start=catalog.period_start,
        period_end=None, expected_sha256=source.sha256, textless_pages=source.textless_pages,
        transcription_note=source.transcription_note,
        license_note=f'{source.rights.note} Licence: {source.rights.license_url}; terms: {source.rights.terms_url}')
    program = next(item for item in load_records(root, 'live', 'programs') if item.id == target)
    if agent.fallback_blocks:
        note = (f'KI-Strukturierung unvollständig: {agent.cached_blocks} PDF-Layoutblöcke aus '
                f'validierten Modellantworten, {agent.fallback_blocks} weitere Quellblöcke ohne neue '
                'Modellanfrage unter „Strukturierung noch offen“ nach PDF-Seiten erhalten. '
                'Die Textspur ist vollständig extrahiert; die Abschnittsstruktur ist ein ungeprüfter Vorschlag.')
        program.transcription_note += ' ' + note
        program.review.note = note
        write_json(root / f'live/programs/{target}.json', program)
    result.update({'stage': 'offline-source-recovery', 'complete_text': True,
                   'ai_outline_complete': agent.fallback_blocks == 0,
                   'cached_blocks': agent.cached_blocks, 'fallback_blocks': agent.fallback_blocks,
                   'cached_batches': agent.cache_hits, 'model_requests': agent.calls,
                   'validation': validate_store(root)})
    if agent.calls != 0:
        raise AssertionError('Offline recovery must never issue a model request')
    write_json(ROOT / '.cache/recovered-tree-result.json', result)
    return result


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    result = run()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(summary).open('a') as file:
            file.write('\n## Offline source recovery — not complete AI analysis\n```json\n' + rendered + '\n```\n')
