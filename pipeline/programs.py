from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import date
from pathlib import Path

from pydantic import Field

from pipeline.documents import download, extract_pdf, pages_to_markdown
from pipeline.llm import Agent, InvalidModelResponse
from pipeline.models import Criterion, Leaf, LeafExtraction, Model, Program, Source, Span, Topic, TreeNode
from pipeline.parallel import ordered_map
from pipeline.store import digest, load_records, save_record, stable_id, tree_paths, write_json

logger = logging.getLogger(__name__)


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


class LeafCriteria(CriteriaResponse):
    leaf_id: str


class CriteriaBatch(Model):
    paragraphs: list[LeafCriteria]


class ParagraphGroup(Model):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    sections: list[str] = Field(min_length=1, max_length=5)


class StructuredParagraphs(Model):
    groups: list[ParagraphGroup] = Field(min_length=1)


def structure_paragraphs(raw_leaves, markdown, title, program_id, agent):
    """Join layout fragments into paragraphs without letting the model rewrite source text."""
    root = TreeNode(id=f"{program_id}-root", title=title)
    leaves, provenance, known_paths = [], [], []
    lines = markdown.splitlines()
    completed = 0
    batches = deque(chunks(raw_leaves))
    while batches:
        batch = batches.popleft()
        def group_text(group):
            first, last = batch[group.start], batch[group.end]
            if group.start == group.end:
                return first.text
            return "\n".join(lines[first.reference.line_start - 1:last.reference.line_end])

        def check(result):
            cursor = 0
            for group in result.groups:
                if group.start != cursor or not group.start <= group.end < len(batch):
                    raise ValueError(f'Expected the next range to start at {cursor}; received '
                                     f'[{group.start}, {group.end}] for {len(batch)} blocks (0-based indexes)')
                if any(not s.strip() or len(s) > 120 for s in group.sections):
                    raise ValueError("Invalid section title")
                cursor = group.end + 1
            if cursor != len(batch):
                raise ValueError("Paragraph groups omitted source blocks")

        def cited_groups(groups):
            # Models often join continuations across PDF pages. Preserve their section assignment,
            # but create page-bound, size-bound verbatim leaves deterministically. Overlapping
            # ranges are pre-split pieces of a long source block and must never be joined twice.
            for group in groups:
                start = group.start
                for end in range(start + 1, group.end + 1):
                    candidate = group.model_copy(update={'start': start, 'end': end})
                    if (batch[end].reference.page != batch[start].reference.page
                            or batch[end].reference.line_start <= batch[end - 1].reference.line_end
                            or len(group_text(candidate)) > 4500):
                        yield group.model_copy(update={'start': start, 'end': end - 1})
                        start = end
                yield group.model_copy(update={'start': start})

        try:
            result, generation = agent.ask(
                "Structure these numbered PDF layout blocks into a readable section tree and paragraphs. "
                "Join consecutive fragments of ONE paragraph, not separate policy commitments; PDF line "
                "wrapping often splits a sentence into many blocks. Preserve ALL blocks, including headers, "
                "contents, footnotes and rhetoric. Return consecutive inclusive start/end index ranges, "
                "covering every input index exactly once in input order. A continued paragraph may span pages: "
                "the importer will split it at PDF page/size boundaries to preserve exact citations. "
                "Use document headings as section paths "
                "and reuse existing paths. Never write replacement source text. Contents/front matter should "
                "be grouped under clearly identified front-matter sections, not substantive policy sections.",
                {"blocks": [{"index": i, "page": leaf.reference.page, "text": leaf.text}
                            for i, leaf in enumerate(batch)], "existing_sections": known_paths[-80:]},
                StructuredParagraphs, validator=check, max_output=9000, subdivide=len(batch) > 4,
            )
        except InvalidModelResponse:
            if len(batch) <= 4:
                raise
            midpoint = len(batch) // 2
            logger.warning('%s: subdividing an invalid %s-block outline batch; source checks stay strict',
                           program_id, len(batch))
            batches.appendleft(batch[midpoint:])
            batches.appendleft(batch[:midpoint])
            continue
        check(result)
        for group in cited_groups(result.groups):
            first, last = batch[group.start], batch[group.end]
            text = group_text(group)
            leaf = first if group.start == group.end else Leaf(
                id=stable_id(f"{program_id}-p", f"{first.id}:{last.id}:{text}"), text=text,
                reference=Span(page=first.reference.page, line_start=first.reference.line_start,
                               line_end=last.reference.line_end, quote=text))
            leaves.append(leaf)
            node, current = root, []
            for section in group.sections:
                current.append(section)
                identifier = stable_id(f"{program_id}-s", "/".join(current))
                child = next((c for c in node.children if c.id == identifier), None)
                if child is None:
                    child = TreeNode(id=identifier, title=section)
                    node.children.append(child)
                node = child
            node.leaf_ids.append(leaf.id)
            if current not in known_paths:
                known_paths.append(current)
        provenance.append(generation)
        completed += len(batch)
        logger.info('%s: structured %s/%s source blocks into %s paragraphs',
                    program_id, completed, len(raw_leaves), len(leaves))
    return leaves, root, provenance


def chunks(leaves, max_chars=12_000, max_leaves=64):
    batch, size = [], 0
    for leaf in leaves:
        if batch and (size + len(leaf.text) > max_chars or len(batch) >= max_leaves):
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
                   program_id: str | None = None, expected_sha256: str | None = None,
                   textless_pages: list[int] | None = None, transcription_note: str = "",
                   license_note: str | None = None, semantic_paragraphs=True):
    program_id = program_id or f"{party}-{year}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,69}", program_id) or program_id.startswith("demo-"):
        raise ValueError("Use a live program ID of 2–70 lowercase letters, digits or hyphens")
    path = root / "live" / "programs" / f"{program_id}.json"
    if path.exists():
        raise ValueError("Program already exists; preserve its IDs and corrections. Use a new ID for a new edition.")
    parties = {p["id"]: p for p in json.loads((root / "parties.json").read_text())}
    if party not in parties:
        raise ValueError("Unknown party; add its metadata through a PR first")
    if period_start < published or (period_end and period_end <= period_start):
        raise ValueError("Invalid comparison window; validate dates before any paid model calls")
    if not 1949 <= year <= 2100:
        raise ValueError("Election year outside supported range")
    if not license_note or len(license_note.strip()) < 20:
        raise ValueError("Record an actual public full-text reuse licence/permission in license_note before importing")
    # Validate source metadata before downloading or spending the model budget.
    Source(url=source_url, title=title, publisher=party, retrieved_at=date.today())
    if textless_pages and (not expected_sha256 or not transcription_note):
        raise ValueError("Textless-page declarations require an expected PDF hash and an inspection note")
    content = download(pdf) if pdf.startswith("https://") else Path(pdf).read_bytes()
    if expected_sha256 and digest(content) != expected_sha256:
        raise ValueError("Programme PDF changed since source inspection; review the new edition before importing")
    pages = extract_pdf(content, textless_pages=set(textless_pages or []))
    markdown, leaves = pages_to_markdown(pages, program_id)
    if semantic_paragraphs:
        leaves, tree, generation = structure_paragraphs(leaves, markdown, title, program_id, agent)
    else:
        tree, generation = build_tree(leaves, title, program_id, agent)
    relative_md = f"live/programs/{program_id}.md"
    program = Program(
        id=program_id, dataset="live", party_id=party, election_year=year, title=title,
        published_at=published, period_start=period_start, period_end=period_end,
        source=Source(url=source_url, title=title, publisher=parties[party]["name"], retrieved_at=date.today(),
                      sha256=digest(content), license_note=license_note),
        pdf_url=pdf if pdf.startswith("https://") else None,
        textless_pages=sorted(textless_pages or []), transcription_note=transcription_note,
        markdown_path=relative_md, leaves=leaves, tree=tree, generation=generation,
    )
    (root / relative_md).parent.mkdir(parents=True, exist_ok=True)
    (root / relative_md).write_text(markdown, encoding="utf-8")
    save_record(root, "programs", program)
    return {"program_id": program.id, "pages": len(pages), "paragraphs": len(leaves)}


def extract_criteria(*, root: Path, program_id: str, agent: Agent, batch_size=1, workers=1, leaf_ids=None):
    if not 1 <= batch_size <= 8 or not 1 <= workers <= 4:
        raise ValueError("Criterion batches must be 1–8 leaves; workers 1–4")
    programs = {p.id: p for p in load_records(root, "live", "programs")}
    if program_id not in programs:
        raise ValueError("Unknown live program ID")
    program = programs[program_id]
    existing = load_records(root, "live", "criteria")
    completed_leaves = {c.leaf_id for c in existing if c.program_id == program_id}
    completed_leaves.update(a.leaf_id for a in program.criteria_extraction)
    paths = tree_paths(program.tree)
    created, audits = [], []
    # Evaluate every leaf. Batching preserves one explicit result/abstention per leaf.
    pending = [leaf for leaf in program.leaves if leaf.id not in completed_leaves]
    if leaf_ids is not None:
        selected = set(leaf_ids)
        if len(selected) != len(leaf_ids) or not selected <= {leaf.id for leaf in program.leaves}:
            raise ValueError("Selected sample must contain unique existing leaf IDs")
        pending = [leaf for leaf in pending if leaf.id in selected]
    task = (
        "Extract atomic, observable acceptance criteria from each manifesto paragraph. "
        "Write titles, descriptions, tests and abstention reasons in German. "
        "One policy commitment per criterion, with a falsifiable test and VERBATIM supporting quote, "
        "including source line breaks and Markdown. Do not invent quantities, dates, promises or use "
        "your knowledge of the party. Return an empty list with an abstention reason for rhetoric, "
        "headings, tables of contents, descriptions of the status quo, ambiguous aspirations or "
        "non-testable statements. A deadline may only come from the cited source; otherwise null. "
        "If only a year is specified, preserve it in the test but set deadline=null rather than inventing "
        "an exact calendar day. A promise to examine an option is NOT a promise to implement it. "
        "Neighbouring context helps interpret a continuation but is NOT citable for this leaf."
    )
    positions = {leaf.id: i for i, leaf in enumerate(program.leaves)}
    def query(batch):
        def check(result):
            if batch_size != 1:
                ids = [r.leaf_id for r in result.paragraphs]
                if len(ids) != len(batch) or set(ids) != {leaf.id for leaf in batch}:
                    raise ValueError("Criterion batch must preserve every leaf ID exactly once")
                # ID-based reordering is lossless; missing/duplicate IDs still fail. Never zip
                # source citations to whichever paragraph the model happened to return first.
                by_id = {r.leaf_id: r for r in result.paragraphs}
                result.paragraphs = [by_id[leaf.id] for leaf in batch]
            responses = [result] if batch_size == 1 else result.paragraphs
            for leaf, response in zip(batch, responses, strict=True):
                if not response.criteria and not response.abstention_reason:
                    raise ValueError("Empty criterion extraction must explain its abstention")
                for draft in response.criteria:
                    if draft.quote not in leaf.text:
                        raise ValueError("Model invented a programme quote")
        if batch_size == 1:
            leaf = batch[0]
            return (task, {"program": program.title, "sections": paths[leaf.id], "paragraph": leaf.text},
                    CriteriaResponse, {"validator": check})
        paragraphs = []
        for leaf in batch:
            index = positions[leaf.id]
            paragraphs.append({"leaf_id": leaf.id, "sections": paths[leaf.id], "paragraph": leaf.text,
                "previous_context": program.leaves[index - 1].text[-1000:] if index else "",
                "next_context": program.leaves[index + 1].text[:1000] if index + 1 < len(program.leaves) else ""})
        return (task + " Return every input leaf_id exactly once, in input order.",
                {"program": program.title, "paragraphs": paragraphs}, CriteriaBatch,
                {"validator": check, "max_output": 10000})

    def cached(batch):
        if not hasattr(agent, 'has_cached'):
            return False
        prompt, data, schema, options = query(batch)
        return agent.has_cached(prompt, data, schema, **options)

    def cached_subtree(batch):
        if cached(batch):
            return True
        if len(batch) == 1:
            return False
        midpoint = len(batch) // 2
        return cached_subtree(batch[:midpoint]) or cached_subtree(batch[midpoint:])

    def evaluate(batch):
        midpoint = len(batch) // 2
        if len(batch) > 1 and not cached(batch) and (
                cached_subtree(batch[:midpoint]) or cached_subtree(batch[midpoint:])):
            # Older runs saved valid child batches but not the failed parent. Reuse those
            # results before spending anything to rediscover the same invalid parent.
            return evaluate(batch[:midpoint]) + evaluate(batch[midpoint:])
        prompt, data, schema, options = query(batch)
        try:
            result, generation = agent.ask(prompt, data, schema, **options, subdivide=len(batch) > 1)
        except InvalidModelResponse:
            if len(batch) == 1:
                raise
            logger.warning('%s: subdividing an invalid %s-leaf criteria batch; source checks stay strict',
                           program_id, len(batch))
            return evaluate(batch[:midpoint]) + evaluate(batch[midpoint:])
        options['validator'](result)  # Also enforce contracts for offline/mock agents.
        responses = [result] if batch_size == 1 else result.paragraphs
        return list(zip(batch, responses, [generation] * len(batch), strict=True))
    batches = chunks(pending, max_chars=10_000, max_leaves=batch_size)
    for leaf, result, generation in (
        item for batch in ordered_map(evaluate, batches, workers=workers) for item in batch
    ):
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
        if len(audits) % 24 == 0 or len(audits) == len(pending):
            logger.info('%s: processed %s/%s pending paragraphs, %s criteria proposed',
                        program.id, len(audits), len(pending), len(created))
    # Write only after all calls/citations in this stage validate. No half-written criteria set.
    for criterion in created:
        save_record(root, "criteria", criterion)
    if audits:
        program.criteria_extraction.extend(audits)
        write_json(root / "live" / "programs" / f"{program.id}.json", program)
    return {"program_id": program.id, "new_criteria": len(created), "preserved_leaves": len(completed_leaves),
            "processed_leaves": len(audits), "remaining_leaves": len(program.leaves) - len(completed_leaves) - len(audits),
            "abstained_leaves": sum(not a.criterion_ids for a in audits)}
