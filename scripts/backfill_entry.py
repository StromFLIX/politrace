"""Bounded historical import. Source inventory/rights checks run before any paid requests."""
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Literal

from pipeline.archive import ingest_archive
from pipeline.catalog import load_catalog
from pipeline.llm import Agent, ProviderError
from pipeline.matching import match_laws
from pipeline.models import Model
from pipeline.programs import extract_criteria, ingest_program
from pipeline.store import ROOT, load_records, validate_store, write_json


class Probe(Model):
    status: Literal["ready"]


def pilot_leaves(program, terms):
    """Explicit, deterministic source-term sample; never select on predicted political effect."""
    if (not isinstance(terms, list) or not 1 <= len(terms) <= 12
            or any(not isinstance(term, str) or not 3 <= len(term) <= 80 for term in terms)):
        raise ValueError('Pilot terms must be 1–12 explicit source terms of 3–80 characters')
    selected = set()
    for term in terms:
        matching = [leaf.id for leaf in program.leaves if term.casefold() in leaf.text.casefold()
                    and len(leaf.text) >= 80]
        selected.update(matching[:2])
    if not selected:
        raise ValueError('Pilot terms found no source paragraphs; never report an empty pilot as complete')
    return [leaf.id for leaf in program.leaves if leaf.id in selected]


def run(target, *, root=ROOT / "data", agent=None, criteria_terms=None, match_law_ids=None):
    validate_store(root)
    catalog = load_catalog(root)
    if target == "probe":
        agent = agent or Agent(cache=ROOT / ".cache" / "llm")
        result, _ = agent.ask("Return status ready, to verify the configured JSON provider integration.",
                              {"purpose": "integration smoke test"}, Probe, max_output=256)
        return {"provider": result.status, "budget": agent.summary()}
    if target == "laws":
        result = ingest_archive(root=root, since=catalog.period_start, snapshot_fallback=True)
    else:
        source = next((p for p in catalog.programs if p.id == target), None)
        if source is None:
            raise ValueError("Target must be laws, probe, or a programme ID in the checked catalog")
        source.require_publication_basis()
        agent = agent or Agent(cache=ROOT / ".cache" / "llm")
        existing = {p.id: p for p in load_records(root, "live", "programs")}
        if target in existing:
            if existing[target].source.sha256 != source.sha256:
                raise ValueError("Existing programme edition differs from the inspected source; never overwrite")
            result = {"program_id": target, "preserved_program": True}
        else:
            result = ingest_program(
                root=root, agent=agent, program_id=target, party=source.party_id,
                year=catalog.election_year, title=source.title, pdf=str(source.pdf_url),
                source_url=str(source.pdf_url), published=source.published,
                period_start=catalog.period_start, period_end=None,
                expected_sha256=source.sha256, textless_pages=source.textless_pages,
                transcription_note=source.transcription_note,
                license_note=f"{source.rights.note} Licence: {source.rights.license_url}; terms: {source.rights.terms_url}",
            )
        # The complete transcription/tree is an independent product. Retain it even if the
        # later criteria stage fails; never label an incomplete criteria stage successful.
        tree_validation = validate_store(root)
        checkpoint = ROOT / '.cache' / 'backfill-trees' / target
        checkpoint.mkdir(parents=True, exist_ok=True)
        for extension in ('json', 'md'):
            shutil.copy(root / 'live' / 'programs' / f'{target}.{extension}', checkpoint / f'{target}.{extension}')
        report(target + '-tree', {'stage': 'complete-tree', **result,
                                 'budget': agent.summary(), 'validation': tree_validation})
        program = next(p for p in load_records(root, 'live', 'programs') if p.id == target)
        selected = pilot_leaves(program, criteria_terms) if criteria_terms is not None else None
        result["criteria"] = extract_criteria(root=root, program_id=target, agent=agent,
                                              batch_size=6, workers=4, leaf_ids=selected)
        result['criteria_scope'] = {'mode': 'source-term-pilot' if selected is not None else 'all-leaves',
                                    'terms': criteria_terms, 'selected_leaf_ids': selected}
        validate_store(root)
        # A completed bounded criteria stage is useful even if the independent law stage fails.
        proposal = ROOT / '.cache' / 'backfill-criteria' / target
        for collection in ('programs', 'criteria'):
            for path in (root / 'live' / collection).glob('*'):
                if path.suffix in ('.json', '.md'):
                    destination = proposal / collection / path.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(path, destination)
        report(target + '-criteria', {'stage': 'complete-selected-criteria', **result,
                                     'budget': agent.summary()})
        if match_law_ids is not None:
            result['matching'] = match_laws(root=root, agent=agent, law_ids=match_law_ids, per_program=6)
        result["budget"] = agent.summary()
    result["validation"] = validate_store(root)
    return result


def report(target, result):
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    write_json(ROOT / ".cache" / f"backfill-{target}.json", result)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as file:
            file.write(f"\n## {target}\n```json\n{rendered}\n```\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    logging.getLogger('pipeline').setLevel(logging.INFO)
    target = os.environ.get("BACKFILL_TARGET") or sys.argv[1]
    options, budget = {}, None
    if os.environ.get('GITHUB_EVENT_NAME') == 'push':
        request = json.loads((ROOT / '.github/backfills/bundestag-21.json').read_text())
        if request.get('scope') == target:
            options = {key: request[key] for key in ('criteria_terms', 'match_law_ids') if key in request}
            if 'max_usd' in request:
                # A committed retry can tighten, never raise, the configured job ceiling.
                budget = min(float(request['max_usd']), float(os.environ.get('POLITRACE_MAX_USD', '5')))
    agent = None if target == 'laws' else Agent(cache=ROOT / '.cache' / 'llm', max_usd=budget)
    if agent:
        report(target + '-provider-check', {'provider_check': agent.key_status()})
    try:
        result = run(target, agent=agent, **options)
    except Exception as error:
        # Report charges and outstanding exposure separately, never free-form provider bodies.
        report(target, {'status': 'failed', 'error_type': type(error).__name__,
                        'provider_error': error.safe_details() if isinstance(error, ProviderError) else None,
                        'budget': agent.summary() if agent else None})
        raise
    report(target, result)
