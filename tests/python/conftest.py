from datetime import date

import pytest

from pipeline.documents import pages_to_markdown
from pipeline.models import Criterion, Law, Program, Review, Source, TreeNode
from pipeline.store import write_json


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "data"
    for dataset in ("demo", "live"):
        for collection in ("programs", "criteria", "laws", "impacts", "votes"):
            (root / dataset / collection).mkdir(parents=True)
    write_json(root / "parties.json", [{"id": "spd", "name": "SPD", "short_name": "SPD",
                                        "color": "#ee3333", "website": "https://example.org"}])
    source = Source(url="https://example.org/source", title="Test source", publisher="Test fixture",
                    retrieved_at=date(2025, 6, 1))
    review = Review(status="reviewed", reviewer="human-test", reviewed_at=date(2025, 6, 2))
    quote = "Wir erhöhen den Mindestlohn auf 15 Euro brutto pro Stunde."
    markdown, leaves = pages_to_markdown([quote, "Gemeinsam für eine bessere Zukunft."], "spd-2025")
    (root / "live/programs/spd-2025.md").write_text(markdown)
    program = Program(id="spd-2025", dataset="live", party_id="spd", election_year=2025,
                      title="Test programme", published_at=date(2025, 1, 1), period_start=date(2025, 1, 1),
                      source=source, markdown_path="live/programs/spd-2025.md", leaves=leaves,
                      tree=TreeNode(id="spd-2025-root", title="Arbeit", leaf_ids=[p.id for p in leaves]),
                      review=review)
    write_json(root / "live/programs/spd-2025.json", program)
    criterion = Criterion(id="spd-2025-ac-lohn", dataset="live", program_id=program.id, party_id="spd",
                          leaf_id=leaves[0].id, title="Mindestlohn auf 15 Euro", description="Mindestlohn anheben.",
                          test="Der gesetzliche Mindestlohn beträgt mindestens 15 Euro brutto je Stunde.",
                          tags=["arbeit"], reference=leaves[0].reference, review=review)
    write_json(root / "live/criteria/spd-2025-ac-lohn.json", criterion)
    law_text = "Der gesetzliche Mindestlohn beträgt ab 1. Juni 2025 15 Euro brutto je Zeitstunde."
    md, passages = pages_to_markdown([law_text], "bgbl-1-2025-100")
    law = Law(id="bgbl-1-2025-100", dataset="live", title="Mindestlohnanpassung", official_title="Testgesetz",
              published_at=date(2025, 5, 30), citation="Test fixture", source=source,
              text_status="available", passages=passages, markdown_path="live/laws/bgbl-1-2025-100.md",
              summary="Testgesetz zur Erhöhung des Mindestlohns.")
    (root / law.markdown_path).write_text(md)
    write_json(root / "live/laws/bgbl-1-2025-100.json", law)
    return root, program, criterion, law
