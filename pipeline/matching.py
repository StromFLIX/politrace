from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

import snowballstemmer
from pydantic import Field, model_validator

from pipeline.llm import PROMPT_VERSION, Agent
from pipeline.models import Impact, MatchAudit, Model
from pipeline.store import digest, json_text, load_records, save_record, stable_id, write_json

logger = logging.getLogger(__name__)
MATCHING_VERSION = 'evidence-links-v2'
STEMMER = snowballstemmer.stemmer("german")
STOP = set("der die das ein eine einer eines und oder ist sind wird werden mit für von im in an auf zu des den dem "
           "als nach über durch zum zur sich bei auch nicht nur sowie es wir soll sollen mehr diesem diese".split())
ALIASES = {
    "arbeit": "Mindestlohn Lohn Tarifvertrag Beschäftigung Arbeitszeit Arbeitnehmer",
    "wirtschaft": "Unternehmen Wirtschaft Investition Bürokratie Wettbewerb",
    "steuern": "Steuer Einkommensteuer Körperschaftsteuer Umsatzsteuer Abgabe",
    "soziales": "Rente Bürgergeld Grundsicherung Sozialleistung Armut",
    "klima": "Klimaschutz Emission CO2 Treibhausgas Klimaneutralität",
    "energie": "Strom Energie erneuerbar Netzentgelt Stromsteuer Heizung",
    "mobilitaet": "Bahn ÖPNV Verkehr Deutschlandticket Straße Schiene Tempolimit",
    "wohnen": "Miete Wohnung Mietpreisbremse Wohnungsbau Wohngeld",
    "bildung": "Schule Bildung Hochschule BAföG Ausbildung",
    "gesundheit": "Pflege Krankenhaus Gesundheit Krankenkasse",
    "migration": "Asyl Einwanderung Migration Staatsangehörigkeit Aufenthalt",
    "digitales": "Digitalisierung Internet Breitband Datenschutz Verwaltung",
    "demokratie": "Wahl Transparenz Demokratie Bundestag Lobbyregister",
    "sicherheit": "Bundeswehr Polizei Sicherheit Verteidigung Strafrecht",
    "europa": "Europäische Union Europarecht Binnenmarkt",
}


def tokens(text: str) -> list[str]:
    return STEMMER.stemWords([word for word in re.findall(r"[\wäöüß]+", text.casefold())
                             if len(word) > 2 and word not in STOP])


def rank(query: str, documents: dict[str, str]) -> list[tuple[str, float]]:
    if not documents:
        return []
    terms = {key: Counter(tokens(text)) for key, text in documents.items()}
    lengths = {key: sum(count.values()) for key, count in terms.items()}
    average = max(1, sum(lengths.values()) / len(lengths))
    df = Counter(term for count in terms.values() for term in count)
    query_terms = set(tokens(query))
    result = []
    for key, counts in terms.items():
        score = 0.0
        for term in query_terms & counts.keys():
            frequency = counts[term]
            inverse = math.log(1 + (len(terms) - df[term] + 0.5) / (df[term] + 0.5))
            score += inverse * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * lengths[key] / average))
        if score > 0:
            result.append((key, score))
    return sorted(result, key=lambda item: (-item[1], item[0]))


def criterion_text(criterion):
    return " ".join([criterion.title, criterion.test, criterion.reference.quote,
                     *criterion.keywords, *(ALIASES[t] for t in criterion.tags)])


def eligible_criteria(law, criteria, programs):
    programs = {p.id: p for p in programs}
    return [c for c in criteria if c.review.status != "rejected" and (
        (p := programs[c.program_id]).review.status != "rejected"
        and p.period_start <= law.published_at and (not p.period_end or law.published_at < p.period_end)
    )]


def retrieve(law, criteria, *, per_program=6):
    # A cap per programme avoids a large party crowding out smaller ones.
    by_program = defaultdict(list)
    for criterion in criteria:
        by_program[criterion.program_id].append(criterion)
    query = " ".join([law.title, *(p.text for p in law.passages), *(ALIASES[t] for t in law.tags)])
    candidates = []
    for program_id in sorted(by_program):
        group = {c.id: c for c in by_program[program_id]}
        candidates.extend(group[key] for key, _ in rank(query, {key: criterion_text(c) for key, c in group.items()})
                          [:per_program])
    return candidates


def context_for(law, criterion, max_chars=60_000):
    if sum(len(p.text) for p in law.passages) <= max_chars:
        return law.passages, False
    ranked = rank(criterion_text(criterion), {p.id: p.text for p in law.passages})
    selected = set()
    size = 0
    indices = {p.id: i for i, p in enumerate(law.passages)}
    for key, _ in ranked:
        index = indices[key]
        for neighbor in (index - 1, index, index + 1):
            if 0 <= neighbor < len(law.passages) and neighbor not in selected:
                length = len(law.passages[neighbor].text)
                if size + length <= max_chars:
                    selected.add(neighbor)
                    size += length
    return [law.passages[i] for i in sorted(selected)], True


class Judgment(Model):
    supported: bool
    score: Literal[-2, -1, 0, 1, 2] | None
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=15)
    law_passage_id: str | None
    law_quote: str | None
    criterion_quote: str | None
    caveats: list[str]

    @model_validator(mode="after")
    def has_evidence(self):
        if self.supported and not (self.score is not None and self.law_passage_id and self.law_quote
                                   and self.criterion_quote):
            raise ValueError("Supported judgments require a score and two quotations")
        return self


class Verification(Model):
    accepted: bool
    rationale: str = Field(min_length=10)
    caveats: list[str]


def match_laws(*, root: Path, agent: Agent, per_program=6, law_ids=None, limit=None):
    if not 1 <= per_program <= 50:
        raise ValueError("per_program must be between 1 and 50")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000):
        raise ValueError("Matching limit must be between 1 and 2000 laws")
    criteria = load_records(root, "live", "criteria")
    programs = load_records(root, "live", "programs")
    laws = load_records(root, "live", "laws")
    if law_ids is not None:
        by_id = {law.id: law for law in laws}
        if not law_ids or len(set(law_ids)) != len(law_ids) or not set(law_ids) <= by_id.keys():
            raise ValueError("Select unique existing law IDs; an empty selection is not an exhaustive run")
        laws = [by_id[identifier] for identifier in law_ids]
    else:
        # New publications first; unchanged laws do not consume a batch slot on later runs.
        laws.sort(key=lambda law: (law.published_at, law.id), reverse=True)
    existing = {(i.criterion_id, i.law_id) for i in load_records(root, "live", "impacts")}
    corpus_hash = digest(json_text({"criteria": [c.model_dump(mode="json") for c in criteria],
                                  "periods": [p.model_dump(mode="json", exclude={"leaves", "tree"})
                                              for p in programs], "per_program": per_program}))
    created, candidate_pairs_checked = 0, 0
    processed, unchanged, deferred = [], [], []
    for law in laws:
        analysis_hash = digest(json_text({
            "law": law.model_dump(mode="json", exclude={"matching"}),
            "criteria_sha256": corpus_hash, "retrieval_version": "bm25-de-v1",
            "matching_version": MATCHING_VERSION,
            "prompt_version": PROMPT_VERSION, "model": getattr(agent, "model", None),
            "review_model": getattr(agent, "review_model", None),
        }))
        if law.matching.analysis_sha256 == analysis_hash and law.matching.status != "pending":
            unchanged.append(law.id)
            continue
        if limit is not None and len(processed) >= limit:
            deferred.append(law.id)
            continue
        eligible = eligible_criteria(law, criteria, programs)
        if law.text_status != "available":
            audit = MatchAudit(status="needs_ocr", criteria_sha256=corpus_hash)
            candidates = []
        elif not eligible:
            audit = MatchAudit(status="no_programs", criteria_sha256=corpus_hash,
                               note="No criteria with an applicable programme comparison window.")
            candidates = []
        else:
            candidates = retrieve(law, eligible, per_program=per_program)
            audit = MatchAudit(
                status="no_supported_links" if candidates else "no_candidates",
                candidate_ids=[c.id for c in candidates], eligible_count=len(eligible),
                omitted_count=len(eligible) - len(candidates), criteria_sha256=corpus_hash,
                note="German-stemmed BM25 + curated topic expansion, not exhaustive semantic retrieval. "
                     "Unselected criteria are UNKNOWN, not unaffected. Every link still needs human review.",
            )
        staged = []
        for criterion in candidates:
            if (criterion.id, law.id) in existing:
                audit.status = "proposed"
                continue
            passages, truncated = context_for(law, criterion)
            if not passages:
                continue
            def check_judgment(result):
                if not result.supported:
                    return
                passage = next((p for p in passages if p.id == result.law_passage_id), None)
                if (not passage or not result.law_quote or len(result.law_quote) < 10
                        or result.law_quote not in passage.text):
                    raise ValueError("Supported law quote must be a verbatim substring of the supplied passage")
                if (not result.criterion_quote or len(result.criterion_quote) < 10
                        or result.criterion_quote not in criterion.reference.quote):
                    raise ValueError("Supported criterion quote must be a verbatim substring of the programme quote")

            result, generation = agent.ask(
                "Judge whether the ACTUAL enacted legal text changes this specific testable commitment. "
                "Topic similarity alone is not a link. Amendments referring to missing base legislation, "
                "missing applicability dates or unclear legal scope require abstention. "
                "score -2 = directly contradicts, -1 = impedes, 0 = demonstrably mixed effect, "
                "+1 = supports in part, +2 = directly implements this specific criterion. "
                "An impact is NOT an overall fulfilment assessment. Cite an exact law passage and an exact "
                "substring of the criterion source quote. supported=false if no defensible effect.",
                {"criterion": criterion.model_dump(mode="json"), "law_title": law.official_title,
                 "published_at": str(law.published_at), "partial_law_context": truncated,
                 "passages": [{"id": p.id, "text": p.text} for p in passages]}, Judgment,
                validator=check_judgment,
            )
            check_judgment(result)  # Offline agents must satisfy the same source contract.
            candidate_pairs_checked += 1
            if not result.supported:
                continue
            passage = next(p for p in passages if p.id == result.law_passage_id)
            verifier, verification_generation = agent.ask(
                "Independently challenge this proposed link using ONLY the quoted programme and the supplied "
                "legal context. Check whether the signed effect and magnitude are actually supported, whether "
                "a condition or exception is omitted, and whether missing base legislation prevents interpretation. "
                "Reject topic-only similarity, speculative effects and overclaims. This is NOT human approval.",
                {"proposal": result.model_dump(mode="json"), "criterion_test": criterion.test,
                 "program_quote": criterion.reference.quote, "partial_law_context": truncated,
                 "law_title": law.official_title, "published_at": str(law.published_at),
                 "legal_context": [{"id": p.id, "text": p.text} for p in passages]}, Verification, review=True,
            )
            caveats = [*result.caveats, *verifier.caveats]
            if truncated:
                caveats.append("Nur ausgewählte Gesetzespassagen geprüft; vollständiger Rechtskontext offen.")
            if not verifier.accepted:
                caveats.append(f"Zweite Modellprüfung widerspricht: {verifier.rationale}")
            staged.append(Impact(
                id=stable_id("impact", law.id + ":" + criterion.id), dataset="live",
                criterion_id=criterion.id, law_id=law.id, score=result.score,
                confidence=result.confidence, rationale=result.rationale,
                law_passage_id=passage.id, law_quote=result.law_quote, criterion_quote=result.criterion_quote,
                caveats=caveats, verification="passed" if verifier.accepted else "needs_review",
                generation=[generation, verification_generation],
            ))
        for impact in staged:
            save_record(root, "impacts", impact)
            created += 1
        if staged:
            audit.status = "proposed"
        audit.analysis_sha256 = analysis_hash
        law.matching = audit
        # Only machine-owned retrieval bookkeeping is changed; never human fields, text or prior links.
        write_json(root / "live" / "laws" / f"{law.id}.json", law)
        processed.append(law.id)
        logger.info('%s: completed %s candidate checks, %s new proposed links; %s laws completed in this batch',
                    law.id, len(candidates), len(staged), len(processed))
    return {"new_impacts": created, "candidate_pairs_checked": candidate_pairs_checked,
            "processed_laws": processed, "unchanged_laws": unchanged, "deferred_laws": deferred,
            "selected_scope_only": law_ids is not None, "scope_complete": not deferred,
            **agent.summary()}
