"""Deterministic, explicitly FICTIONAL UI fixtures. Never writes to the live dataset."""
from datetime import date

from pipeline.documents import pages_to_markdown
from pipeline.models import (
    Assessment,
    Criterion,
    GroupVote,
    Impact,
    Law,
    MatchAudit,
    Program,
    Review,
    Source,
    TreeNode,
    Vote,
)
from pipeline.store import ROOT, json_text, write_json

DATA = ROOT / "data"
REVIEW = Review(status="reviewed", reviewer="demo-redaktion (fiktiv)", reviewed_at=date(2025, 7, 1),
                note="Nur eine Illustration des Review-Prozesses; keine Tatsachenbehauptung.")
SOURCE = Source(url="https://example.org/politrace/fiktive-quelle", title="Fiktiver Beispieldatensatz",
                publisher="Politrace – Demonstration, keine echte Parteiquelle", retrieved_at=date(2025, 7, 1),
                license_note="Fiktive Politrace-Beispieltexte, CC0-1.0. Keine Zitate echter Wahlprogramme.")
# These statements demonstrate the data model, NOT the actual programmes of the named parties.
EXAMPLES = {
    "cdu-csu": [
        ("steuern", "Stromsteuer für alle senken", "Die Stromsteuer wird für alle Haushalte auf das europäische Mindestmaß gesenkt.", "Ein Gesetz senkt den Stromsteuersatz für private Haushalte auf den EU-Mindestsatz."),
        ("wirtschaft", "Unternehmen steuerlich entlasten", "Die Steuerbelastung für Unternehmen soll auf höchstens 25 Prozent sinken.", "Die gesetzliche Gesamtsteuerbelastung der definierten Unternehmensgruppe beträgt höchstens 25 Prozent."),
        ("digitales", "Verwaltung digital zugänglich machen", "Alle Anträge für öffentliche Leistungen sollen vollständig digital möglich sein.", "Für jede öffentliche Leistung existiert ein vollständig digitaler Antragsweg."),
        ("sicherheit", "Beschaffung beschleunigen", "Beschaffungsverfahren der Bundeswehr werden auf höchstens sechs Monate verkürzt.", "Gesetzliche Fristen begrenzen die genannten Beschaffungsverfahren auf sechs Monate."),
    ],
    "spd": [
        ("arbeit", "Mindestlohn auf 15 Euro anheben", "Der gesetzliche Mindestlohn soll spätestens 2026 auf 15 Euro pro Stunde steigen.", "Der gesetzliche Mindestlohn beträgt bis zum 31.12.2026 mindestens 15 Euro brutto je Stunde."),
        ("wohnen", "Mietpreisbremse verlängern", "Die Mietpreisbremse soll ohne Befristung für angespannte Wohnungsmärkte gelten.", "Die gesetzliche Mietpreisbremse enthält keine zeitliche Befristung mehr."),
        ("soziales", "Rentenniveau bei 48 Prozent sichern", "Das gesetzliche Rentenniveau wird dauerhaft bei mindestens 48 Prozent gesichert.", "Eine dauerhafte gesetzliche Untergrenze für das Sicherungsniveau beträgt 48 Prozent."),
        ("bildung", "Schulessen kostenfrei anbieten", "Jedes Kind soll in der Schule ein kostenloses Mittagessen erhalten.", "Ein bundesweit geltender Anspruch finanziert ein kostenloses Schulmittagessen für jedes Kind."),
    ],
    "gruene": [
        ("energie", "Erneuerbare Energien ausbauen", "Der Anteil erneuerbarer Energien am Stromverbrauch soll 2030 mindestens 80 Prozent betragen.", "Ein verbindlicher gesetzlicher Ausbaupfad zielt auf mindestens 80 Prozent erneuerbaren Strom bis 2030."),
        ("mobilitaet", "Deutschlandticket dauerhaft sichern", "Das Deutschlandticket wird dauerhaft zu einem Preis von höchstens 49 Euro finanziert.", "Ein Gesetz sichert die dauerhafte Finanzierung eines bundesweiten Tickets für höchstens 49 Euro monatlich."),
        ("klima", "Klimageld direkt auszahlen", "Die Einnahmen aus dem CO2-Preis werden als Pro-Kopf-Klimageld zurückgegeben.", "Ein gesetzlicher Mechanismus zahlt die genannten Einnahmen gleichmäßig pro Kopf aus."),
        ("wohnen", "Sozialen Wohnungsbau fördern", "Jährlich sollen 100.000 neue Sozialwohnungen durch den Bund gefördert werden.", "Der Bundeshaushalt finanziert verbindlich mindestens 100.000 neue Sozialwohnungen pro Jahr."),
    ],
    "fdp": [
        ("steuern", "Solidaritätszuschlag abschaffen", "Der Solidaritätszuschlag wird vollständig abgeschafft.", "Das Solidaritätszuschlaggesetz wird ohne verbleibende Zahlungspflicht aufgehoben."),
        ("wirtschaft", "Berichtspflichten abbauen", "Berichtspflichten für kleine Unternehmen werden um ein Viertel reduziert.", "Die Zahl verpflichtender Berichte für kleine Unternehmen sinkt gegenüber dem Ausgangsjahr um mindestens 25 Prozent."),
        ("bildung", "Elternunabhängiges BAföG einführen", "Die Studienförderung wird unabhängig vom Einkommen der Eltern gewährt.", "Das Einkommen der Eltern wird bei der BAföG-Berechtigung nicht berücksichtigt."),
        ("digitales", "Digitale Identität ermöglichen", "Alle Bürgerinnen und Bürger erhalten Zugang zu einer staatlichen digitalen Identität.", "Es besteht ein gesetzlicher, diskriminierungsfreier Zugang zur staatlichen digitalen Identität."),
    ],
    "afd": [
        ("steuern", "CO2-Abgabe aufheben", "Die nationale CO2-Abgabe auf Kraftstoffe und Heizenergie wird aufgehoben.", "Die nationale Pflicht zur Entrichtung der genannten CO2-Abgabe wird gesetzlich aufgehoben."),
        ("energie", "Kernenergie ermöglichen", "Der Betrieb von Kernkraftwerken zur Stromerzeugung soll wieder gesetzlich möglich sein.", "Ein Gesetz hebt das Verbot des kommerziellen Betriebs von Kernkraftwerken auf."),
        ("migration", "Asylverfahren verkürzen", "Asylverfahren sollen innerhalb von drei Monaten abgeschlossen werden.", "Eine verbindliche gesetzliche Verfahrensfrist beträgt höchstens drei Monate."),
        ("demokratie", "Bundesweite Volksentscheide einführen", "Bundesweite Volksentscheide über Bundesgesetze werden eingeführt.", "Eine gesetzliche Grundlage ermöglicht verbindliche bundesweite Abstimmungen über Bundesgesetze."),
    ],
    "linke": [
        ("wohnen", "Mieten bundesweit begrenzen", "Mieten sollen für sechs Jahre auf dem bestehenden Niveau eingefroren werden.", "Eine bundesweite gesetzliche Regelung untersagt Mieterhöhungen für sechs Jahre."),
        ("arbeit", "Mindestlohn auf 15 Euro anheben", "Der gesetzliche Mindestlohn wird auf mindestens 15 Euro je Stunde erhöht.", "Der gesetzliche Mindestlohn beträgt mindestens 15 Euro brutto je Stunde."),
        ("gesundheit", "Pflege-Eigenanteile deckeln", "Der monatliche Eigenanteil für Pflege wird auf 500 Euro begrenzt.", "Ein gesetzlicher Höchstbetrag begrenzt den monatlichen pflegebedingten Eigenanteil auf 500 Euro."),
        ("mobilitaet", "Nahverkehr kostenfrei anbieten", "Der öffentliche Nahverkehr wird für alle Menschen kostenfrei.", "Die Nutzung des öffentlichen Nahverkehrs ist bundesweit ohne Fahrpreis möglich."),
    ],
    "bsw": [
        ("soziales", "Mindestrente einführen", "Nach 40 Beitragsjahren soll eine Mindestrente von 1.500 Euro gelten.", "Ein gesetzlicher Anspruch sichert nach 40 Beitragsjahren mindestens 1.500 Euro monatliche Rente."),
        ("gesundheit", "Krankenhäuser bedarfsorientiert finanzieren", "Die Grundfinanzierung öffentlicher Krankenhäuser wird von Fallpauschalen entkoppelt.", "Die gesetzliche Grundfinanzierung öffentlicher Krankenhäuser ist unabhängig von der Zahl abgerechneter Fälle."),
        ("energie", "Energiepreise begrenzen", "Ein Grundkontingent Strom soll für Haushalte höchstens 20 Cent je Kilowattstunde kosten.", "Der gesetzliche Bruttohöchstpreis für das definierte Grundkontingent beträgt 20 Cent je Kilowattstunde."),
        ("arbeit", "Tarifbindung stärken", "Öffentliche Aufträge werden nur an tarifgebundene Unternehmen vergeben.", "Das Vergaberecht schreibt Tarifbindung als Voraussetzung für öffentliche Aufträge vor."),
    ],
}


def save(collection, record):
    write_json(DATA / "demo" / collection / f"{record.id}.json", record)


def seed():
    for dataset in ("live", "demo"):
        for collection in ("programs", "criteria", "laws", "impacts", "votes"):
            folder = DATA / dataset / collection
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ".gitkeep").touch()
    criteria = {}
    for party, examples in EXAMPLES.items():
        for year in ([2025, 2021] if party == "spd" else [2025]):
            program_id = f"demo-{party}-{year}"
            markdown, leaves = pages_to_markdown([text for _, _, text, _ in examples], program_id)
            md_path = f"demo/programs/{program_id}.md"
            (DATA / md_path).write_text(markdown)
            children = [TreeNode(id=f"{program_id}-section-{i + 1}", title=topic.capitalize(), leaf_ids=[leaf.id])
                        for i, ((topic, *_), leaf) in enumerate(zip(examples, leaves, strict=True))]
            program = Program(
                id=program_id, dataset="demo", party_id=party, election_year=year,
                title=f"Beispielprogramm {year} · keine Originalquelle", published_at=date(year, 1, 1),
                period_start=date(year, 1, 1), period_end=date(2025, 1, 1) if year == 2021 else None,
                source=SOURCE, markdown_path=md_path, leaves=leaves,
                tree=TreeNode(id=f"{program_id}-root", title="Beispielprogramm", children=children), review=REVIEW,
            )
            save("programs", program)
            for i, ((topic, title, text, test), leaf) in enumerate(zip(examples, leaves, strict=True), 1):
                criterion = Criterion(
                    id=f"{program_id}-ac-{i:03d}", dataset="demo", program_id=program_id, party_id=party,
                    leaf_id=leaf.id, title=title, description=f"Fiktive Illustration eines prüfbaren Versprechens. {text}",
                    test=test, tags=[topic], keywords=title.split(), reference=leaf.reference, review=REVIEW,
                )
                criteria[criterion.id] = criterion

    definitions = [
        ("energie", "Stromsteuer-Entlastung", "Die Stromsteuer für private Haushalte wird auf den europäischen Mindestsatz gesenkt.", date(2025, 6, 24), ["steuern", "energie"]),
        ("miete", "Verlängerung der Mietpreisbremse", "Die Geltungsdauer der Mietpreisbremse wird bis zum 31. Dezember 2029 verlängert.", date(2025, 6, 18), ["wohnen"]),
        ("lohn", "Anhebung des Mindestlohns", "Ab dem 1. Januar 2026 beträgt der gesetzliche Mindestlohn 15 Euro brutto je Zeitstunde.", date(2025, 6, 6), ["arbeit"]),
        ("ticket", "Finanzierung des Deutschlandtickets", "Das Deutschlandticket wird bis zum 31. Dezember 2026 mitfinanziert. Der monatliche Preis beträgt 58 Euro.", date(2025, 5, 28), ["mobilitaet", "klima"]),
        ("alt", "Renten-Sicherung (historisches Beispiel)", "Das Sicherungsniveau der gesetzlichen Rente wird bis zum 31. Dezember 2024 auf 48 Prozent festgelegt.", date(2023, 6, 15), ["soziales"]),
    ]
    laws = {}
    for key, title, text, published, tags in definitions:
        law_id = f"demo-gesetz-{key}"
        markdown, passages = pages_to_markdown([f"§ 1 – Fiktive Regelung\n\n{text}"], law_id)
        md_path = f"demo/laws/{law_id}.md"
        (DATA / md_path).write_text(markdown)
        law = Law(id=law_id, dataset="demo", title=title, official_title=f"Fiktives Beispielgesetz: {title}",
                  published_at=published, citation="DEMO · keine amtliche Fundstelle", source=SOURCE,
                  markdown_path=md_path, text_status="available", passages=passages, tags=tags,
                  summary=text + " Dies ist ein erfundenes Beispiel, kein tatsächlich verkündetes Gesetz.",
                  matching=MatchAudit(status="proposed"), review=REVIEW)
        save("laws", law)
        laws[key] = law
    links = [
        ("cdu-csu", 1, "energie", 2, "fulfilled", True, 2025),
        ("spd", 1, "lohn", 2, "fulfilled", True, 2025),
        ("spd", 2, "miete", 1, "partial", True, 2025),
        ("linke", 2, "lohn", 2, "fulfilled", True, 2025),
        ("gruene", 2, "ticket", -1, "contradicted", True, 2025),
        ("linke", 1, "miete", 1, "unassessed", False, 2025),
        ("bsw", 3, "energie", 1, "unassessed", False, 2025),
        ("spd", 3, "alt", 1, "partial", True, 2021),
    ]
    for party, index, key, score, status, reviewed, year in links:
        criterion = criteria[f"demo-{party}-{year}-ac-{index:03d}"]
        law = laws[key]
        passage = law.passages[-1]
        impact = Impact(
            id=f"demo-impact-{party}-{key}", dataset="demo", criterion_id=criterion.id, law_id=law.id,
            score=score, confidence=0.87 if reviewed else 0.61,
            rationale={2: "Die fiktive Regelung setzt das eng formulierte Einzelkriterium im Beispiel unmittelbar um.",
                       1: "Die fiktive Regelung wirkt in Richtung des Ziels, erfüllt aber nicht alle genannten Bedingungen.",
                       -1: "Der fiktive Ticketpreis liegt über der im Beispiel versprochenen Preisobergrenze."}[score],
            law_passage_id=passage.id, law_quote=passage.text, criterion_quote=criterion.reference.quote,
            caveats=["Ausschließlich fiktive Demonstration. Keine Bewertung tatsächlicher Politik."],
            verification="passed" if reviewed else "needs_review", review=REVIEW if reviewed else Review(),
        )
        save("impacts", impact)
        if status != "unassessed":
            criterion.assessment = Assessment(status=status, rationale=impact.rationale, reviewer=REVIEW.reviewer,
                                               assessed_at=REVIEW.reviewed_at, evidence_ids=[impact.id])
    for criterion in criteria.values():
        save("criteria", criterion)
    for key in ("lohn", "miete"):
        vote = Vote(id=f"demo-vote-{key}", dataset="demo", law_id=laws[key].id, date=date(2025, 5, 22),
                    motion="Fiktive Schlussabstimmung – keine echten Abstimmungsdaten", type="roll_call",
                    source=SOURCE, review=REVIEW, groups=[
                        GroupVote(group="CDU/CSU", party_id="cdu-csu", yes=200, no=2, abstain=1, absent=5),
                        GroupVote(group="SPD", party_id="spd", yes=115, no=0, abstain=0, absent=5),
                        GroupVote(group="Grüne", party_id="gruene", yes=78, no=0, abstain=2, absent=5),
                        GroupVote(group="AfD", party_id="afd", yes=0, no=145, abstain=2, absent=5),
                        GroupVote(group="Die Linke", party_id="linke", yes=60, no=0, abstain=0, absent=4),
                        GroupVote(group="Fraktionslos", yes=0, no=1, abstain=0, absent=0),
                    ])
        save("votes", vote)
    print(json_text({"demo_criteria": len(criteria), "note": "Only fictional demo data written"}))


if __name__ == "__main__":
    seed()
