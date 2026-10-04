from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from pipeline.laws import FEED_URL, ingest_laws
from pipeline.llm import Agent
from pipeline.matching import match_laws
from pipeline.programs import extract_criteria, ingest_program
from pipeline.store import ROOT, export_schemas, validate_store


def parser():
    cli = argparse.ArgumentParser(description="Politrace: source-backed data, proposed via Git PRs")
    cli.add_argument("--data", type=Path, default=ROOT / "data")
    cli.add_argument("--cache", type=Path, default=ROOT / ".cache" / "llm")
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate contracts, graph integrity and verbatim source citations")
    sub.add_parser("schemas", help="Export JSON Schema contracts")
    program = sub.add_parser("program", help="PDF → page-anchored Markdown → agent-structured tree")
    program.add_argument("--pdf", required=True, help="Local PDF path or public HTTPS URL")
    program.add_argument("--source-url", required=True, help="Canonical published programme URL")
    program.add_argument("--party", required=True)
    program.add_argument("--year", required=True, type=int)
    program.add_argument("--title", required=True)
    program.add_argument("--published", required=True, type=date.fromisoformat)
    program.add_argument("--period-start", required=True, type=date.fromisoformat)
    program.add_argument("--period-end", type=date.fromisoformat)
    program.add_argument("--id", dest="program_id")
    criteria = sub.add_parser("criteria", help="Every leaf + parent sections → atomic testable commitments")
    criteria.add_argument("--program", dest="program_id", required=True)
    laws = sub.add_parser("laws", help="Import official BGBl I laws, without a model or API key")
    laws.add_argument("--limit", type=int, default=10)
    laws.add_argument("--since", type=date.fromisoformat)
    laws.add_argument("--feed-url", default=FEED_URL)
    matching = sub.add_parser("match", help="Cheap retrieval → evidence judgment → second-pass challenge")
    matching.add_argument("--per-program", type=int, default=6)
    return cli


def main():
    args = vars(parser().parse_args())
    command, root, cache = args.pop("command"), args.pop("data"), args.pop("cache")
    if command == "validate":
        result = validate_store(root)
    elif command == "schemas":
        export_schemas(root / "schemas")
        result = {"exported": True}
    elif command == "laws":
        validate_store(root)
        result = ingest_laws(root=root, **args)
        validate_store(root)
    else:
        validate_store(root)
        agent = Agent(cache=cache)
        if command == "program":
            result = ingest_program(root=root, agent=agent, **args)
        elif command == "criteria":
            result = extract_criteria(root=root, agent=agent, **args)
        else:
            result = match_laws(root=root, agent=agent, **args)
        validate_store(root)
        result["budget"] = agent.summary()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
