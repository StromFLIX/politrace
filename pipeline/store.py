from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import TypeAdapter

from pipeline.models import RECORD_TYPES, LawCoverage, Party, Record, TreeNode

ROOT = Path(__file__).resolve().parents[1]


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def stable_id(prefix: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return f"{prefix}-{digest(normalized)[:16]}"


def json_text(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json_text(value), encoding="utf-8")
    temporary.replace(path)


def load_records(root: Path, dataset: str, collection: str):
    model = RECORD_TYPES[collection]
    return [model.model_validate_json(p.read_text()) for p in sorted((root / dataset / collection).glob("*.json"))]


def save_record(root: Path, collection: str, record: Record) -> None:
    path = root / record.dataset / collection / f"{record.id}.json"
    if path.exists():
        raise ValueError(f"Refusing to overwrite existing record {record.id}; use a reviewed PR")
    write_json(path, record)


def safe_markdown(root: Path, dataset: str, path: str) -> Path:
    resolved = (root / path).resolve()
    expected = (root / dataset).resolve()
    if not resolved.is_relative_to(expected) or resolved.suffix != ".md":
        raise ValueError(f"Markdown must stay inside data/{dataset}: {path}")
    return resolved


def all_leaf_ids(tree: TreeNode) -> list[str]:
    return tree.leaf_ids + [leaf for child in tree.children for leaf in all_leaf_ids(child)]


def tree_paths(tree: TreeNode, path: list[str] | None = None) -> dict[str, list[str]]:
    path = [*(path or []), tree.title]
    result = {leaf: path for leaf in tree.leaf_ids}
    for child in tree.children:
        result.update(tree_paths(child, path))
    return result


def validate_store(root: Path = ROOT / "data") -> dict[str, int]:
    parties = TypeAdapter(list[Party]).validate_json((root / "parties.json").read_text())
    party_ids = {p.id for p in parties}
    if len(party_ids) != len(parties):
        raise ValueError("Duplicate party IDs")
    if (root / "sources" / "bundestag-21.json").exists():
        from pipeline.catalog import load_catalog

        if not {p.party_id for p in load_catalog(root).programs} <= party_ids:
            raise ValueError("Source catalog references an unknown party")
    counts = {}
    for dataset in ("live", "demo"):
        data = {}
        for collection in RECORD_TYPES:
            records = load_records(root, dataset, collection)
            indexed = {r.id: r for r in records}
            if len(indexed) != len(records):
                raise ValueError(f"Duplicate IDs in {dataset}/{collection}")
            for record in records:
                if record.dataset != dataset:
                    raise ValueError(f"Mixed dataset: {record.id}")
                expected = root / dataset / collection / f"{record.id}.json"
                if not expected.exists():
                    raise ValueError(f"Filename must equal record ID: {record.id}")
            data[collection] = indexed
            counts[f"{dataset}/{collection}"] = len(records)

        def check_spans(record, leaves):
            md = safe_markdown(root, dataset, record.markdown_path).read_text(encoding="utf-8")
            lines = md.splitlines()
            if len({leaf.id for leaf in leaves}) != len(leaves):
                raise ValueError(f"Duplicate passage IDs: {record.id}")
            for leaf in leaves:
                span = leaf.reference
                excerpt = "\n".join(lines[span.line_start - 1:span.line_end])
                if span.line_end > len(lines) or span.quote not in excerpt or leaf.text != span.quote:
                    raise ValueError(f"Broken Markdown citation: {record.id}/{leaf.id}")
                previous = "\n".join(lines[:span.line_start])
                pages = re.findall(r"<!-- page:(\d+) -->", previous)
                if not pages or int(pages[-1]) != span.page:
                    raise ValueError(f"Wrong PDF page: {record.id}/{leaf.id}")

        for program in data["programs"].values():
            if program.party_id not in party_ids:
                raise ValueError(f"Unknown party: {program.id}")
            referenced = all_leaf_ids(program.tree)
            if len(set(referenced)) != len(referenced) or set(referenced) != {p.id for p in program.leaves}:
                raise ValueError(f"Tree must reference every leaf exactly once: {program.id}")
            def node_ids(node):
                return [node.id] + [i for child in node.children for i in node_ids(child)]
            nodes = node_ids(program.tree)
            if len(set(nodes)) != len(nodes):
                raise ValueError(f"Duplicate tree node IDs: {program.id}")
            check_spans(program, program.leaves)
            audits = program.criteria_extraction
            if len({a.leaf_id for a in audits}) != len(audits):
                raise ValueError(f"Duplicate leaf extraction audits: {program.id}")
            for audit in audits:
                if audit.leaf_id not in referenced:
                    raise ValueError(f"Extraction audit references missing leaf: {program.id}")
                for criterion_id in audit.criterion_ids:
                    criterion = data["criteria"].get(criterion_id)
                    if not criterion or criterion.program_id != program.id or criterion.leaf_id != audit.leaf_id:
                        raise ValueError(f"Extraction audit references wrong criterion: {criterion_id}")

        for criterion in data["criteria"].values():
            program = data["programs"].get(criterion.program_id)
            if not program or program.party_id != criterion.party_id:
                raise ValueError(f"Invalid program/party: {criterion.id}")
            leaf = next((leaf for leaf in program.leaves if leaf.id == criterion.leaf_id), None)
            if not leaf or criterion.reference.quote not in leaf.text:
                raise ValueError(f"Criterion quote not in leaf: {criterion.id}")
            if (criterion.reference.page, criterion.reference.line_start, criterion.reference.line_end) != (
                leaf.reference.page, leaf.reference.line_start, leaf.reference.line_end
            ):
                raise ValueError(f"Criterion citation must refer to its leaf range: {criterion.id}")
            if criterion.assessment.status != "unassessed":
                if criterion.review.status != "reviewed" or program.review.status != "reviewed":
                    raise ValueError(f"Assessments need a reviewed criterion and program: {criterion.id}")
                for evidence_id in criterion.assessment.evidence_ids:
                    impact = data["impacts"].get(evidence_id)
                    if not impact or impact.criterion_id != criterion.id or impact.review.status != "reviewed":
                        raise ValueError(f"Assessment needs reviewed evidence: {criterion.id}/{evidence_id}")

        for law in data["laws"].values():
            if law.text_status == "available":
                check_spans(law, law.passages)
            for candidate in law.matching.candidate_ids:
                if candidate not in data["criteria"]:
                    raise ValueError(f"Unknown retrieval candidate: {law.id}/{candidate}")

        for impact in data["impacts"].values():
            criterion = data["criteria"].get(impact.criterion_id)
            law = data["laws"].get(impact.law_id)
            if not criterion or not law:
                raise ValueError(f"Dangling impact: {impact.id}")
            program = data["programs"][criterion.program_id]
            if law.published_at < program.period_start or (
                program.period_end and law.published_at >= program.period_end
            ):
                raise ValueError(f"Law outside programme comparison period: {impact.id}")
            passage = next((p for p in law.passages if p.id == impact.law_passage_id), None)
            if not passage or impact.law_quote not in passage.text:
                raise ValueError(f"Law quote not in source: {impact.id}")
            if impact.criterion_quote not in criterion.reference.quote:
                raise ValueError(f"Criterion quote not in source: {impact.id}")

        for path in (root / dataset / "coverage").glob("*.json"):
            coverage = LawCoverage.model_validate_json(path.read_text())
            if dataset != "live":
                raise ValueError("Official archive coverage cannot be demo data")
            for identifier in set(coverage.expected_ids) - set(coverage.pending_ids):
                law = data["laws"].get(identifier)
                if not law or not coverage.period_start <= law.published_at <= coverage.as_of:
                    raise ValueError(f"Coverage claims an absent/out-of-window law: {identifier}")

        pairs = [(i.criterion_id, i.law_id) for i in data["impacts"].values()]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Only one canonical impact per criterion/law; revise it through a PR")
        for vote in data["votes"].values():
            if vote.law_id not in data["laws"]:
                raise ValueError(f"Vote for unknown law: {vote.id}")
            if any(g.party_id and g.party_id not in party_ids for g in vote.groups):
                raise ValueError(f"Vote references unknown party: {vote.id}")
    return counts


def export_schemas(root: Path = ROOT / "data" / "schemas"):
    from pipeline.catalog import SourceCatalog

    for name, model in {**RECORD_TYPES, "parties": Party, "coverage": LawCoverage,
                        "source-catalog": SourceCatalog}.items():
        write_json(root / f"{name}.schema.json", model.model_json_schema())
