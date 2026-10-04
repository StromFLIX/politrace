from datetime import date

import pymupdf
import pytest

from pipeline.documents import NeedsOCR, extract_pdf
from pipeline.laws import ingest_laws, parse_feed, pdf_link
from pipeline.matching import Judgment, Verification, eligible_criteria, match_laws, rank, retrieve
from pipeline.models import Generation, Review
from pipeline.programs import CriteriaResponse, Outline, build_tree, extract_criteria, ingest_program
from pipeline.store import load_records, validate_store, write_json

FEED = b'''<?xml version="1.0"?><rss xmlns:meta="http://recht.bund.de/rss/meta"><channel>
<item><title>Testgesetz</title><link>https://www.recht.bund.de/eli/bund/bgbl-1/2025/210a</link>
<pubDate>2025-06-01</pubDate><meta:typ>Gesetz</meta:typ><meta:fundstelle>BGBl I Test</meta:fundstelle></item>
<item><title>Verordnung</title><meta:typ>Verordnung</meta:typ></item>
<item><title>Korrektur</title><meta:typ>Sonstiges</meta:typ></item>
</channel></rss>'''
PDF_URL = 'https://www.recht.bund.de/bgbl/1/2025/210a/regelungstext.pdf?__blob=publicationFile&v=1'
HTML = f'<a href="{PDF_URL}">PDF</a>'.encode()
GEN = Generation(model="offline-test", prompt_version="test", input_sha256="0" * 64)


class FakeAgent:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = 0

    def ask(self, task, data, schema, **kwargs):
        self.calls += 1
        assert self.answers, "Unexpected model call"
        answer = self.answers.pop(0)
        return schema.model_validate(answer), GEN

    def summary(self):
        return {"calls": self.calls, "reserved_usd_upper_bound": 0}


def test_official_feed_filters_non_laws_and_accepts_letter_suffixes():
    records = parse_feed(FEED)
    assert [r["id"] for r in records] == ["bgbl-1-2025-210a"]


def test_feed_empty_or_changed_markup_is_a_failure_not_a_noop():
    for content in (b"<html>error</html>", b"<rss><channel/></rss>"):
        with pytest.raises(ValueError):
            parse_feed(content)


def test_feed_rejects_non_official_urls():
    with pytest.raises(ValueError, match="non-official"):
        parse_feed(FEED.replace(b"www.recht.bund.de/eli", b"attacker.example/eli"))


def test_feed_rejects_xml_entity_expansion():
    with pytest.raises(Exception):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel>&x;</channel></rss>')


def test_pdf_must_belong_to_this_law():
    assert pdf_link(HTML, "https://www.recht.bund.de/eli/bund/bgbl-1/2025/210a") == PDF_URL
    with pytest.raises(ValueError):
        pdf_link(HTML, "https://www.recht.bund.de/eli/bund/bgbl-1/2025/211")


def test_real_pdf_tool_extracts_text():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Ein Gesetz zum Mindestlohn. Der Mindestlohn betraegt 15 Euro.")
    pages = extract_pdf(doc.tobytes())
    assert "15 Euro" in pages[0]
    assert len(pages) == 1
    doc.close()


def test_scanned_or_empty_pdf_requires_ocr():
    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(NeedsOCR):
        extract_pdf(doc.tobytes())
    doc.close()


def test_law_import_is_idempotent_and_does_not_call_model(corpus, monkeypatch):
    root, *_ = corpus
    calls = []
    def fake_download(url, **kwargs):
        calls.append(url)
        return FEED if "rss" in url else HTML if "eli" in url else b"%PDF-test"
    monkeypatch.setattr("pipeline.laws.download", fake_download)
    monkeypatch.setattr("pipeline.laws.extract_pdf", lambda _: ["Dies ist ein amtlicher Gesetzestext für den Test."])
    first = ingest_laws(root=root)
    assert first["new_laws"] == ["bgbl-1-2025-210a"]
    calls.clear()
    second = ingest_laws(root=root)
    assert second["new_laws"] == [] and second["notify"] is False
    assert len(calls) == 1  # only the feed, not the already imported PDF
    validate_store(root)


def test_ocr_laws_remain_visible_without_fabricated_text(corpus, monkeypatch):
    root, *_ = corpus
    monkeypatch.setattr("pipeline.laws.download", lambda url, **kw: FEED if "rss" in url else HTML)
    def no_text(_):
        raise NeedsOCR("scan")
    monkeypatch.setattr("pipeline.laws.extract_pdf", no_text)
    ingest_laws(root=root)
    law = next(item for item in load_records(root, "live", "laws") if item.id.endswith("210a"))
    assert law.text_status == "needs_ocr" and not law.passages
    validate_store(root)


def test_outline_preserves_order_and_every_leaf(corpus):
    _, program, *_ = corpus
    placements = [{"leaf_id": p.id, "sections": ["Arbeit", "Lohn"]} for p in program.leaves]
    tree, _ = build_tree(program.leaves, program.title, program.id, FakeAgent([{"placements": placements}]))
    assert tree.children[0].children[0].leaf_ids == [p.id for p in program.leaves]
    with pytest.raises(ValueError, match="every paragraph"):
        build_tree(program.leaves, program.title, program.id, FakeAgent([{"placements": placements[:1]}]))


def test_existing_criterion_is_preserved_and_abstention_is_audited(corpus):
    root, program, criterion, _ = corpus
    agent = FakeAgent([{"criteria": [], "abstention_reason": "Nur Rhetorik, keine beobachtbare Verpflichtung."}])
    before = (root / f"live/criteria/{criterion.id}.json").read_bytes()
    result = extract_criteria(root=root, program_id=program.id, agent=agent)
    assert result["new_criteria"] == 0 and result["abstained_leaves"] == 1
    assert before == (root / f"live/criteria/{criterion.id}.json").read_bytes()
    no_calls = FakeAgent()
    extract_criteria(root=root, program_id=program.id, agent=no_calls)
    assert no_calls.calls == 0
    assert load_records(root, "live", "programs")[0].criteria_extraction[0].abstention_reason
    validate_store(root)


def test_criteria_extraction_requires_verbatim_programme_quote(corpus):
    root, program, criterion, _ = corpus
    (root / f"live/criteria/{criterion.id}.json").unlink()
    proposal = {"title": "Mindestlohn erhöhen", "description": "Den Mindestlohn auf 15 Euro anheben.",
                "test": "Der Mindestlohn beträgt 15 Euro.", "quote": "Ein komplett erfundenes Zitat.",
                "tags": ["arbeit"], "keywords": ["Mindestlohn"], "deadline": None}
    agent = FakeAgent([{"criteria": [proposal], "abstention_reason": None}])
    with pytest.raises(ValueError, match="invented"):
        extract_criteria(root=root, program_id=program.id, agent=agent)
    assert not load_records(root, "live", "criteria")


def test_existing_program_cannot_be_overwritten(corpus):
    root, program, *_ = corpus
    with pytest.raises(ValueError, match="already exists"):
        ingest_program(root=root, agent=FakeAgent(), pdf="unused.pdf", party="spd", year=2025, title="New",
                       source_url="https://example.org", published=date(2025, 1, 1), period_start=date(2025, 1, 1),
                       period_end=None, program_id=program.id)


def test_german_stemming_and_topic_retrieval(corpus):
    _, program, criterion, law = corpus
    assert rank("Mindestlöhne erhöhen", {"lohn": "Mindestlohn anheben", "solar": "Solarenergie fördern"})[0][0] == "lohn"
    assert retrieve(law, [criterion], per_program=1) == [criterion]
    future = program.model_copy(update={"period_start": date(2026, 1, 1)})
    assert eligible_criteria(law, [criterion], [future]) == []
    ended = program.model_copy(update={"period_end": law.published_at})
    assert eligible_criteria(law, [criterion], [ended]) == []


def test_two_pass_links_stay_proposed_and_reruns_make_no_calls(corpus):
    root, _, criterion, law = corpus
    proposal = Judgment(supported=True, score=2, confidence=0.8, rationale="Diese konkrete Regelung erhöht den Mindestlohn.",
                        law_passage_id=law.passages[0].id, law_quote=law.passages[0].text,
                        criterion_quote=criterion.reference.quote, caveats=[])
    challenge = Verification(accepted=False, rationale="Der zeitliche Geltungsbereich muss geprüft werden.", caveats=[])
    agent = FakeAgent([proposal.model_dump(), challenge.model_dump()])
    assert match_laws(root=root, agent=agent)["new_impacts"] == 1
    impact = load_records(root, "live", "impacts")[0]
    assert impact.review.status == "proposed" and impact.verification == "needs_review"
    assert load_records(root, "live", "criteria")[0].assessment.status == "unassessed"
    assert match_laws(root=root, agent=FakeAgent())["new_impacts"] == 0
    validate_store(root)


def test_matching_abstains_without_supported_legal_effect(corpus):
    root, *_ = corpus
    response = Judgment(supported=False, score=None, confidence=0.2, rationale="Keine belastbare Wirkung nachweisbar.",
                        law_passage_id=None, law_quote=None, criterion_quote=None, caveats=[])
    agent = FakeAgent([response.model_dump()])
    assert match_laws(root=root, agent=agent)["new_impacts"] == 0
    law = load_records(root, "live", "laws")[0]
    assert law.matching.status == "no_supported_links" and len(law.matching.candidate_ids) == 1


def test_source_and_model_changes_invalidate_previous_abstentions(corpus):
    root, _, _, law = corpus
    response = Judgment(supported=False, score=None, confidence=0.2,
                        rationale="Keine belastbare Wirkung nachweisbar.",
                        law_passage_id=None, law_quote=None, criterion_quote=None, caveats=[]).model_dump()
    assert match_laws(root=root, agent=FakeAgent([response]))["calls"] == 1
    assert match_laws(root=root, agent=FakeAgent())["calls"] == 0
    # Even a corrected official title must not leave a stale no-match decision in place.
    law = load_records(root, "live", "laws")[0]
    law.official_title += " (berichtigter Titel)"
    write_json(root / "live" / "laws" / f"{law.id}.json", law)
    assert match_laws(root=root, agent=FakeAgent([response]))["calls"] == 1
    agent = FakeAgent([response])
    agent.model = "different-evaluator"
    assert match_laws(root=root, agent=agent)["calls"] == 1
    validate_store(root)


def test_rejected_criteria_are_not_retrieved(corpus):
    root, program, criterion, law = corpus
    criterion.review = Review(status="rejected", reviewer="human", reviewed_at=date(2025, 6, 1))
    write_json(root / "live/criteria/spd-2025-ac-lohn.json", criterion)
    assert eligible_criteria(law, [criterion], [program]) == []
    assert match_laws(root=root, agent=FakeAgent())["new_impacts"] == 0


def test_outline_schema_rejects_instruction_side_channels():
    with pytest.raises(Exception):
        Outline.model_validate({"placements": [], "execute_shell": "bad"})
    with pytest.raises(Exception):
        CriteriaResponse.model_validate({"criteria": [], "abstention_reason": None, "review": "reviewed"})
