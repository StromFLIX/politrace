"""Bounded historical import. Source inventory/rights checks run before any paid requests."""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Literal

from pipeline.archive import ingest_archive
from pipeline.catalog import load_catalog
from pipeline.llm import Agent
from pipeline.models import Model
from pipeline.programs import extract_criteria, ingest_program
from pipeline.store import ROOT, load_records, validate_store, write_json


class Probe(Model):
    status: Literal["ready"]


def run(target, *, root=ROOT / "data", agent=None):
    validate_store(root)
    catalog = load_catalog(root)
    if target == "probe":
        agent = agent or Agent(cache=ROOT / ".cache" / "llm")
        result, _ = agent.ask("Return status ready, to verify the configured JSON provider integration.",
                              {"purpose": "integration smoke test"}, Probe, max_output=256)
        return {"provider": result.status, "budget": agent.summary()}
    if target == "laws":
        result = ingest_archive(root=root, since=catalog.period_start)
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
        result["criteria"] = extract_criteria(root=root, program_id=target, agent=agent,
                                              batch_size=6, workers=2)
        result["budget"] = agent.summary()
    result["validation"] = validate_store(root)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    logging.getLogger('pipeline').setLevel(logging.INFO)
    target = os.environ.get("BACKFILL_TARGET") or sys.argv[1]
    result = run(target)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    write_json(ROOT / ".cache" / f"backfill-{target}.json", result)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as file:
            file.write(f"\n## {target}\n```json\n{rendered}\n```\n")
