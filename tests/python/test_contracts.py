from datetime import date

import pytest
from pydantic import ValidationError

from pipeline.documents import pages_to_markdown
from pipeline.models import Assessment, Impact, Review
from pipeline.store import ROOT, safe_markdown, stable_id, validate_store, write_json


def example_impact(criterion, law):
    return Impact(id="impact-test-lohn", dataset="live", criterion_id=criterion.id, law_id=law.id,
                  score=2, confidence=0.9, rationale="Die Regelung setzt den genannten Mindestlohn unmittelbar um.",
                  law_passage_id=law.passages[0].id, law_quote=law.passages[0].text,
                  criterion_quote=criterion.reference.quote, verification="passed")


def test_repository_data_are_valid():
    result = validate_store(ROOT / "data")
    assert result["demo/programs"] == 0  # Fictional examples are test fixtures, never published data.
    assert result["live/laws"] >= 3


def test_all_contracts_and_citations(corpus):
    root, *_ = corpus
    assert validate_store(root)["live/criteria"] == 1


def test_stable_ids_do_not_depend_on_order_or_whitespace():
    assert stable_id("ac", " Mehr  Lohn ") == stable_id("ac", "mehr lohn")
    assert stable_id("ac", "mehr lohn") != stable_id("ac", "weniger lohn")


def test_page_markers_and_citations_preserve_source():
    md, leaves = pages_to_markdown(["# Arbeit\n\nEine Zusage.\nNoch eine Zeile.", "Zweiter Absatz."], "test")
    for leaf in leaves:
        span = leaf.reference
        assert span.quote in "\n".join(md.splitlines()[span.line_start - 1:span.line_end])
    assert leaves[-1].reference.page == 2
    assert len(leaves) == 3


def test_identical_paragraphs_have_unique_ids():
    _, leaves = pages_to_markdown(["Gleicher Text.\n\nGleicher Text."], "test")
    assert len({leaf.id for leaf in leaves}) == 2


def test_long_paragraphs_remain_bounded_verbatim():
    md, leaves = pages_to_markdown(["Ein sehr langes Programm. " * 1000], "test")
    assert max(len(leaf.text) for leaf in leaves) <= 4500
    assert all(leaf.text in md for leaf in leaves)


def test_broken_markdown_quote_is_rejected(corpus):
    root, program, *_ = corpus
    (root / program.markdown_path).write_text("Manipulierte Transkription")
    with pytest.raises(ValueError, match="citation"):
        validate_store(root)


def test_tree_cannot_drop_or_duplicate_paragraphs(corpus):
    root, program, *_ = corpus
    program.tree.leaf_ids.pop()
    write_json(root / "live/programs/spd-2025.json", program)
    with pytest.raises(ValueError, match="every leaf exactly once"):
        validate_store(root)


def test_source_page_must_match_markdown_page(corpus):
    root, program, *_ = corpus
    program.leaves[0].reference.page = 2
    write_json(root / "live/programs/spd-2025.json", program)
    with pytest.raises(ValueError, match="Wrong PDF page"):
        validate_store(root)


def test_program_reference_cannot_point_outside_dataset(corpus):
    root, *_ = corpus
    with pytest.raises(ValueError, match="inside"):
        safe_markdown(root, "live", "../.env.md")
    with pytest.raises(ValueError, match="inside"):
        safe_markdown(root, "live", "demo/programs/test.md")


def test_llm_cannot_self_approve_via_missing_review_metadata():
    with pytest.raises(ValidationError):
        Review(status="reviewed")
    with pytest.raises(ValidationError):
        Assessment(status="fulfilled", rationale="The model says yes")


def test_assessment_requires_reviewed_evidence(corpus):
    root, _, criterion, law = corpus
    impact = example_impact(criterion, law)
    write_json(root / "live/impacts/impact-test-lohn.json", impact)
    criterion.assessment = Assessment(status="fulfilled", reviewer="human", assessed_at=date(2025, 6, 1),
                                      rationale="Sourced human assessment", evidence_ids=[impact.id])
    write_json(root / "live/criteria/spd-2025-ac-lohn.json", criterion)
    with pytest.raises(ValueError, match="reviewed evidence"):
        validate_store(root)
    impact.review = Review(status="reviewed", reviewer="human", reviewed_at=date(2025, 6, 1))
    write_json(root / "live/impacts/impact-test-lohn.json", impact)
    validate_store(root)


def test_future_programmes_cannot_be_matched_retroactively(corpus):
    root, program, criterion, law = corpus
    law.published_at = date(2024, 12, 31)
    write_json(root / "live/laws/bgbl-1-2025-100.json", law)
    write_json(root / "live/impacts/impact-test-lohn.json", example_impact(criterion, law))
    with pytest.raises(ValueError, match="outside programme"):
        validate_store(root)


def test_impact_quote_must_exist_verbatim(corpus):
    root, _, criterion, law = corpus
    impact = example_impact(criterion, law)
    impact.law_quote = "Diese Aussage wurde vom Modell erfunden."
    write_json(root / "live/impacts/impact-test-lohn.json", impact)
    with pytest.raises(ValueError, match="Law quote"):
        validate_store(root)


def test_duplicate_law_criterion_pairs_are_rejected(corpus):
    root, _, criterion, law = corpus
    impact = example_impact(criterion, law)
    write_json(root / "live/impacts/impact-test-lohn.json", impact)
    impact.id = "impact-other-lohn"
    write_json(root / "live/impacts/impact-other-lohn.json", impact)
    with pytest.raises(ValueError, match="one canonical impact"):
        validate_store(root)


def test_demo_and_live_ids_are_isolated(corpus):
    _, _, criterion, _ = corpus
    record = criterion.model_dump()
    record["dataset"] = "demo"
    with pytest.raises(ValidationError, match="Demo IDs"):
        type(criterion).model_validate(record)
