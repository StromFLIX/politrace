"""Safely consume Actions inputs as values, never interpolate them into shell commands."""
import json
import os
import sys
from datetime import date
from pathlib import Path

from pipeline.archive import ingest_archive
from pipeline.documents import public_url
from pipeline.laws import ingest_laws
from pipeline.llm import Agent
from pipeline.matching import match_laws
from pipeline.programs import extract_criteria, ingest_program
from pipeline.store import ROOT, validate_store


def run(mode):
    root = ROOT / "data"
    validate_store(root)
    agent = Agent(cache=ROOT / ".cache" / "llm")
    if mode == "laws":
        since = os.environ.get("INPUT_SINCE", "")
        importer = ingest_archive if os.environ.get("INPUT_ARCHIVE", "false").lower() == "true" else ingest_laws
        result = importer(root=root, limit=int(os.environ.get("INPUT_LIMIT", "10")),
                          since=date.fromisoformat(since) if since else date(2025, 3, 25))
        result["matching"] = match_laws(root=root, agent=agent)
    elif mode == "program":
        pdf = os.environ["INPUT_PDF"]
        source_url = os.environ["INPUT_SOURCE_URL"]
        public_url(pdf)
        public_url(source_url)
        end = os.environ.get("INPUT_PERIOD_END", "")
        result = ingest_program(
            root=root, agent=agent, pdf=pdf, source_url=source_url,
            party=os.environ["INPUT_PARTY"], year=int(os.environ["INPUT_YEAR"]), title=os.environ["INPUT_TITLE"],
            published=date.fromisoformat(os.environ["INPUT_PUBLISHED"]),
            period_start=date.fromisoformat(os.environ["INPUT_PERIOD_START"]),
            period_end=date.fromisoformat(end) if end else None,
            program_id=os.environ.get("INPUT_PROGRAM_ID") or None,
            license_note=os.environ.get("INPUT_LICENSE_NOTE"),
        )
        if os.environ.get("INPUT_EXTRACT_CRITERIA", "false").lower() == "true":
            result["criteria"] = extract_criteria(root=root, program_id=result["program_id"], agent=agent)
    elif mode == "criteria":
        result = extract_criteria(root=root, program_id=os.environ["INPUT_PROGRAM_ID"], agent=agent,
                                  batch_size=6, workers=2)
    else:
        raise ValueError("Unknown workflow mode")
    validate_store(root)
    result["budget"] = agent.summary()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Only fixed keys, IDs, numeric counters and known budget metadata are emitted here.
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as file:
            file.write("\n## Data pipeline result\n```json\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n")
    return result


if __name__ == "__main__":
    run(sys.argv[1])
