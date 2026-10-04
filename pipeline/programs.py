from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from pydantic import Field

from pipeline.documents import download, extract_pdf, pages_to_markdown
from pipeline.llm import Agent
from pipeline.models import Criterion, LeafExtraction, Model, Program, Source, Topic, TreeNode
from pipeline.store import digest, load_records, save_record, stable_id, tree_paths, write_json


class Placement(Model):
    leaf_id: str
    sections: list[str] = Field(min_length=1, max_length=5)


class Outline(Model):
    placements: list[Placement]


class DraftCriterion(Model):
    title: str = Field(min_length=5, max_length=240)
    description: str = Field(min_length=10)
    test: str = Field(min_length=10)
    quote: str = Field(min_length=10)
    tags: list[Topic] = Field(min_length=1, max_length=5)
    keywords: list[str] = Field(max_length=15)
    deadline: date | None


class CriteriaResponse(Model):
    criteria: list[DraftCriterion] = Field(max_length=8)
    abstention_reason: str | None


def chunks(leaves, max_chars=12_000):
    batch, size = [], 0
    for leaf in leaves:
        if batch and size + len(leaf.text) > max_chars:
            yield batch
            batch, size = [], 0
        batch.append(leaf)
        size += len(leaf.text)
    if batch:
        yield batch


def build_tree(leaves, title: str, program_id: str, agent: Agent):
    root = TreeNode(id=f"{program_id}-root", title=title)
    provenance, known_paths = [], []
    for batch in chunks(leaves):
        result, generation = agent.ask(
            "Assign EVERY paragraph to a readable section/subsection path, using document headings. "
            "Return each input leaf_id exactly once. Preserve the document's order. Do not rewrite paragraphs. "
            "Use existing section paths where they apply. Footnotes/contents are also preserved, not discarded.",
            {"paragraphs": [{"id": leaf.id, "text": leaf.text} for leaf in batch],
             "existing_sections": known_paths[-100:]}, Outline,
        )
        ids = [item.leaf_id for item in result.placements]
        if ids != [leaf.id for leaf in batch]:
            raise ValueError("Outline must preserve every paragraph exactly once, in order")
        for placement in result.placements:
            node, path = root, []
            for section in placement.sections:
                if not section.strip() or len(section) > 120:
                    raise ValueError("Invalid section title")
                path.append(section)
                node_id = stable_id(f"{program_id}-s", "/".join(path))
                child = next((child for child in node.children if child.id == node_id), None)
                if child is None:
                    child = TreeNode(id=node_id, title=section)
                    node.children.append(child)
                node = child
            node.leaf_ids.append(placement.leaf_id)
            if path not in known_paths:
                known_paths.append(path)
        provenance.append(generation)
    return root, provenance


def ingest_program(*, root: Path, agent: Agent, pdf: str, party: str, year: int, title: str,
                   source_url: str, published: date, period_start: date, period_end: date | None,
                   program_id: str | None = None):
    program_id = program_id or f"{party}-{year}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,69}", program_id) or program_id.startswith("demo-"):
        raise ValueError("Use a live program ID of 2–70 lowercase letters, digits or hyphens")
    path = root / "live" / "programs" / f"{program_id}.json"
    if path.exists():
        raise ValueError("Program already exists; preserve its IDs and corrections. Use a new ID for a new edition.")
    if party not in {p["id"] for p in json.loads((root / "parties.json").read_text())}:
        raise ValueError("Unknown party; add its metadata through a PR first")
    if period_start < published or (period_end and period_end <= period_start):
        raise ValueError("Invalid comparison window; validate dates before any paid model calls")
    if not 1949 <= year <= 2100:
        raise ValueError("Election year outside supported range")
    # Validate source metadata before downloading or spending the model budget.
    Source(url=source_url, title=title, publisher=party, retrieved_at=date.today())
    content = download(pdf) if pdf.startswith("https://") else Path(pdf).read_bytes()
    pages = extract_pdf(content)
    if any(not page.strip() for page in pages):
        raise ValueError("Some PDF pages have no text. Supply a reviewed OCR PDF before generating criteria.")
    markdown, leaves = pages_to_markdown(pages, program_id)
    tree, generation = build_tree(leaves, title, program_id, agent)
    relative_md = f"live/programs/{program_id}.md"
    program = Program(
        id=program_id, dataset="live", party_id=party, election_year=year, title=title,
        published_at=published, period_start=period_start, period_end=period_end,
        source=Source(url=source_url, title=title, publisher=party, retrieved_at=date.today(),
                      sha256=digest(content)),
        markdown_path=relative_md, leaves=leaves, tree=tree, generation=generation,
    )
    (root / relative_md).parent.mkdir(parents=True, exist_ok=True)
    (root / relative_md).write_text(markdown, encoding="utf-8")
    save_record(root, "programs", program)
    return {"program_id": program.id, "pages": len(pages), "paragraphs": len(leaves)}


def extract_criteria(*, root: Path, program_id: str, agent: Agent):
    programs = {p.id: p for p in load_records(root, "live", "programs")}
    if program_id not in programs:
        raise ValueError("Unknown live program ID")
    program = programs[program_id]
    existing = load_records(root, "live", "criteria")
    completed_leaves = {c.leaf_id for c in existing if c.program_id == program_id}
    completed_leaves.update(a.leaf_id for a in program.criteria_extraction)
    paths = tree_paths(program.tree)
    created, audits = [], []
    # Evaluate every leaf, not just paragraphs that contain a hand-picked keyword.
    for leaf in program.leaves:
        if leaf.id in completed_leaves:
            continue
        result, generation = agent.ask(
            "Extract atomic, observable acceptance criteria from the given manifesto paragraph. "
            "One policy commitment per criterion, with a falsifiable test and verbatim supporting quote. "
            "Do not invent quantities, dates, promises or use your knowledge of the party. "
            "Return an empty list with an abstention reason for rhetoric, headings, descriptions of "
            "the status quo, ambiguous aspirations or non-testable statements. "
            "A deadline may only come from the cited source; otherwise null.",
            {"program": program.title, "sections": paths[leaf.id], "paragraph": leaf.text},
            CriteriaResponse,
        )
        if not result.criteria and not result.abstention_reason:
            raise ValueError("Empty criterion extraction must explain its abstention")
        leaf_criteria = []
        for draft in result.criteria:
            if draft.quote not in leaf.text:
                raise ValueError(f"Model invented a programme quote for {leaf.id}")
            criterion = Criterion(
                id=stable_id(f"{program.id}-ac", leaf.id + ":" + draft.test), dataset="live",
                program_id=program.id, party_id=program.party_id, leaf_id=leaf.id,
                title=draft.title, description=draft.description, test=draft.test,
                tags=draft.tags, keywords=draft.keywords, deadline=draft.deadline,
                reference=leaf.reference.model_copy(update={"quote": draft.quote}), generation=[generation],
            )
            if criterion.id not in {c.id for c in created}:
                created.append(criterion)
                leaf_criteria.append(criterion.id)
        audits.append(LeafExtraction(leaf_id=leaf.id, criterion_ids=leaf_criteria,
                                     abstention_reason=result.abstention_reason, generation=generation))
    # Write only after all calls/citations in this stage validate. No half-written criteria set.
    for criterion in created:
        save_record(root, "criteria", criterion)
    if audits:
        program.criteria_extraction.extend(audits)
        write_json(root / "live" / "programs" / f"{program.id}.json", program)
    return {"program_id": program.id, "new_criteria": len(created), "preserved_leaves": len(completed_leaves),
            "abstained_leaves": sum(not a.criterion_ids for a in audits)}
