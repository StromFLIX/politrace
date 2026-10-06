from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from pipeline.archive import ingest_archive, snapshot_archive
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
    program.add_argument("--license-note", required=True, help="Actual basis for public full-text reuse, not just a citation")
    program.add_argument("--expected-sha256")
    program.add_argument("--textless-pages", type=int, nargs="+", help="Visually checked PDF page numbers, bound to expected SHA-256")
    program.add_argument("--transcription-note", default="")
    criteria = sub.add_parser("criteria", help="Every leaf + parent sections → atomic testable commitments")
    criteria.add_argument("--program", dest="program_id", required=True)
    criteria.add_argument("--batch-size", type=int, default=6)
    criteria.add_argument("--workers", type=int, default=2)
    archive = sub.add_parser("archive", help="Paginated official BGBl I/II historical law inventory and backfill")
    archive.add_argument("--since", required=True, type=date.fromisoformat)
    archive.add_argument("--until", type=date.fromisoformat)
    archive.add_argument("--limit", type=int, default=2000)
    archive.add_argument('--snapshot-fallback', action='store_true', help='On search HTTP 403 only, use the dated checked inventory plus RSS; never claim a fresh complete scan')
    snapshot = sub.add_parser('snapshot-archive', help='Save a count-reconciled official inventory from a network that can reach the public archive')
    snapshot.add_argument('--since', required=True, type=date.fromisoformat)
    snapshot.add_argument('--until', type=date.fromisoformat)
    laws = sub.add_parser("laws", help="Import official BGBl I/II feed laws, without a model or API key")
    laws.add_argument("--limit", type=int, default=10)
    laws.add_argument("--since", type=date.fromisoformat)
    laws.add_argument("--feed-url", default=FEED_URL)
    votes = sub.add_parser('votes', help='DIP proceedings → official decisions, faction positions and named ballots; no LLM')
    votes.add_argument('--since', type=date.fromisoformat, help='Scope by law publication date, not vote date')
    votes.add_argument('--law-ids', nargs='+', help='Explicit law IDs; unselected coverage remains untouched')
    votes.add_argument('--limit', type=int)
    votes.add_argument('--refresh', action='store_true', help='Re-fetch public sources instead of using the bounded cache')
    votes.add_argument('--no-crosscheck', dest='crosscheck', action='store_false',
                       help='Skip the supplementary abgeordnetenwatch JSON cross-check; official sources remain required')
    matching = sub.add_parser("match", help="Cheap retrieval → evidence judgment → second-pass challenge")
    matching.add_argument("--per-program", type=int, default=6)
    matching.add_argument("--limit", type=int, help="Maximum changed laws in this batch; unchanged audits cost no slot")
    matching.add_argument("--law-ids", nargs="+", help="Explicit pilot scope; other laws are not marked checked")
    return cli


def main():
    args = vars(parser().parse_args())
    command, root, cache = args.pop("command"), args.pop("data"), args.pop("cache")
    if command == "validate":
        result = validate_store(root)
    elif command == "schemas":
        export_schemas(root / "schemas")
        result = {"exported": True}
    elif command == 'votes':
        from pipeline.votes import ingest_votes

        validate_store(root)
        result = ingest_votes(root=root, cache=cache.parent / 'votes', **args)
        validate_store(root)
    elif command in {"laws", "archive", "snapshot-archive"}:
        validate_store(root)
        importer = {'laws': ingest_laws, 'archive': ingest_archive, 'snapshot-archive': snapshot_archive}[command]
        result = importer(root=root, **args)
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
