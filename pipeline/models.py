"""The canonical, strict contracts. JSON Schemas are exported for non-Python consumers."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,119}$")]
Dataset = Literal["demo", "live"]
Topic = Literal[
    "arbeit", "wirtschaft", "steuern", "soziales", "klima", "energie", "mobilitaet",
    "wohnen", "bildung", "gesundheit", "migration", "digitales", "demokratie", "sicherheit", "europa",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Review(Model):
    status: Literal["proposed", "reviewed", "rejected"] = "proposed"
    reviewer: str | None = None
    reviewed_at: date | None = None
    note: str = ""

    @model_validator(mode="after")
    def signed_review(self):
        if self.status in ("reviewed", "rejected") and (not self.reviewer or not self.reviewed_at):
            raise ValueError("A human review needs reviewer and reviewed_at")
        return self


class Source(Model):
    url: HttpUrl
    title: str
    publisher: str
    retrieved_at: date
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    license_note: str = "Rights remain with the source publisher; quotations for verification."


class Generation(Model):
    model: str
    prompt_version: str
    input_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Party(Model):
    id: Identifier
    name: str
    short_name: str
    color: Annotated[str, Field(pattern=r"^#[a-fA-F0-9]{6}$")]
    website: HttpUrl


class Span(Model):
    page: int = Field(ge=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class Leaf(Model):
    id: Identifier
    text: str = Field(min_length=1)
    reference: Span


class TreeNode(Model):
    id: Identifier
    title: str = Field(min_length=1)
    children: list[TreeNode] = Field(default_factory=list)
    leaf_ids: list[Identifier] = Field(default_factory=list)


class Record(Model):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    dataset: Dataset

    @model_validator(mode="after")
    def separated_dataset(self):
        if (self.dataset == "demo") != self.id.startswith("demo-"):
            raise ValueError("Demo IDs must start with demo-; live IDs must not")
        return self


class LeafExtraction(Model):
    leaf_id: Identifier
    criterion_ids: list[Identifier]
    abstention_reason: str | None
    generation: Generation

    @model_validator(mode="after")
    def explained_abstention(self):
        if not self.criterion_ids and not self.abstention_reason:
            raise ValueError("An unproductive extraction must explain why")
        return self


class Program(Record):
    party_id: Identifier
    election_year: int = Field(ge=1949, le=2100)
    title: str
    published_at: date
    # Explicit comparison window; no retroactive matching to future manifestos.
    period_start: date
    period_end: date | None = None
    source: Source
    pdf_url: HttpUrl | None = None
    textless_pages: list[int] = Field(default_factory=list)
    transcription_note: str = ""
    markdown_path: str
    leaves: list[Leaf] = Field(min_length=1)
    tree: TreeNode
    criteria_extraction: list[LeafExtraction] = Field(default_factory=list)
    review: Review = Field(default_factory=Review)
    generation: list[Generation] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_period(self):
        if self.period_start < self.published_at:
            raise ValueError("Comparison window cannot precede publication")
        if self.period_end and self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start (exclusive)")
        return self


class Assessment(Model):
    status: Literal["unassessed", "partial", "fulfilled", "contradicted", "mixed"] = "unassessed"
    rationale: str = "Noch keine gesetzliche Bewertung."
    reviewer: str | None = None
    assessed_at: date | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)
    method: Literal['editorial', 'agent'] = 'editorial'
    score: Literal[-2, -1, 0, 1, 2] | None = None
    generation: Generation | None = None
    input_sha256: str | None = None

    @model_validator(mode="after")
    def sourced_assessment(self):
        if self.method == 'agent':
            if (not self.generation or self.generation.model != 'openai/gpt-6-sol'
                    or not self.assessed_at or not self.evidence_ids or not self.input_sha256 or self.reviewer):
                raise ValueError('Automated assessments need final-model provenance, date and evidence')
            allowed = {'fulfilled': {2}, 'partial': {1}, 'contradicted': {-2, -1},
                       'mixed': {0}, 'unassessed': {None}}
            if self.score not in allowed[self.status]:
                raise ValueError('Assessment status and signed score must agree')
            return self
        if self.status != "unassessed" and not (
            self.reviewer and self.assessed_at and self.evidence_ids and self.rationale
        ):
            raise ValueError("An assessment needs a human, a date, a rationale and reviewed evidence IDs")
        if self.status == "unassessed" and self.evidence_ids:
            raise ValueError("Unassessed criteria cannot have assessment evidence")
        return self


class Criterion(Record):
    program_id: Identifier
    party_id: Identifier
    leaf_id: Identifier
    title: str = Field(min_length=5, max_length=240)
    description: str = Field(min_length=10)
    test: str = Field(min_length=10)
    tags: list[Topic] = Field(min_length=1, max_length=5)
    keywords: list[str] = Field(default_factory=list, max_length=15)
    reference: Span
    deadline: date | None = None
    review: Review = Field(default_factory=Review)
    assessment: Assessment = Field(default_factory=Assessment)
    generation: list[Generation] = Field(default_factory=list)


class MatchAudit(Model):
    status: Literal["pending", "no_programs", "no_candidates", "proposed", "no_supported_links", "needs_ocr"]
    retrieval_version: str = "bm25-de-v1"
    candidate_ids: list[Identifier] = Field(default_factory=list)
    eligible_count: int = Field(default=0, ge=0)
    omitted_count: int = Field(default=0, ge=0)
    criteria_sha256: str = ""
    # Invalidates a previous abstention when the law, model or prompt changes.
    analysis_sha256: str = ""
    note: str = "No match is not evidence of no impact."


class Law(Record):
    title: str
    official_title: str
    published_at: date
    status: Literal["promulgated"] = "promulgated"
    kind: Literal["law", "regulation", "correction"] = "law"
    citation: str
    source: Source
    pdf_url: HttpUrl | None = None
    markdown_path: str | None = None
    text_status: Literal["available", "needs_ocr"]
    passages: list[Leaf] = Field(default_factory=list)
    tags: list[Topic] = Field(default_factory=list)
    summary: str
    matching: MatchAudit = Field(default_factory=lambda: MatchAudit(status="pending"))
    review: Review = Field(default_factory=Review)

    @model_validator(mode="after")
    def text_consistency(self):
        if self.text_status == "available" and not (self.markdown_path and self.passages):
            raise ValueError("Available text needs a Markdown file and passages")
        return self


class FinalEvaluation(Model):
    status: Literal['accepted', 'rejected', 'missing_context']
    model: Literal['openai/gpt-6-sol'] = 'openai/gpt-6-sol'
    method: Literal['sol-final-v1'] = 'sol-final-v1'
    input_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    decided_at: date
    previous_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')] | None = None


class Impact(Record):
    criterion_id: Identifier
    law_id: Identifier
    # Ordinal direction of THIS law; not a percentage of overall promise fulfilment.
    score: Literal[-2, -1, 0, 1, 2]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=15)
    law_passage_id: Identifier
    law_quote: str = Field(min_length=10)
    criterion_quote: str = Field(min_length=10)
    caveats: list[str] = Field(default_factory=list)
    verification: Literal["passed", "needs_review"]
    evaluation: FinalEvaluation | None = None
    review: Review = Field(default_factory=Review)
    generation: list[Generation] = Field(default_factory=list)


Ballot = Literal['yes', 'no', 'abstain', 'absent', 'invalid']
VoteCount = Annotated[int, Field(ge=0, strict=True)]


class GroupVote(Model):
    group: str = Field(min_length=1)
    party_id: Identifier | None = None
    # A protocol's faction position is NOT a counted ballot. Unknown is never zero.
    yes: VoteCount | None = None
    no: VoteCount | None = None
    abstain: VoteCount | None = None
    absent: VoteCount | None = None
    invalid: VoteCount | None = None
    position: Literal['yes', 'no', 'abstain', 'mixed', 'unknown'] = 'unknown'
    evidence_quote: str = ''

    @model_validator(mode='after')
    def complete_counts(self):
        counts = [self.yes, self.no, self.abstain, self.absent]
        if any(n is not None for n in counts) and not all(n is not None for n in counts):
            raise ValueError('Group counts must be complete or all unknown')
        if self.yes is None and self.invalid is not None:
            raise ValueError('Invalid ballots require a counted vote')
        return self


class MemberVote(Model):
    # Identity is local to the official ballot sheet, not a guessed cross-term MP ID.
    name: str = Field(min_length=1)
    group: str = Field(min_length=1)
    vote: Ballot
    source_row: int = Field(ge=2)


def official_vote_source(source: Source) -> bool:
    query = source.url.query or ''
    allowed_query = (not query or (source.url.host == 'www.bundestag.de' and (
        re.fullmatch(r'id=\d+', query) or (
            source.url.path.startswith('/ajax/filterlist/de/parlament/plenum/abstimmung/liste/')
            and re.fullmatch(r'limit=\d+&offset=\d+', query)))))
    return bool(source.sha256 and source.url.scheme == 'https' and source.url.port == 443 and source.url.host in {
        'search.dip.bundestag.de', 'dserver.bundestag.de', 'www.bundestag.de',
    } and not source.url.username and not source.url.password and allowed_query)


class VoteCrossCheck(Model):
    provider: Literal['abgeordnetenwatch'] = 'abgeordnetenwatch'
    status: Literal['matched', 'partial', 'mismatch', 'unmatched', 'not_found', 'ambiguous', 'source_error']
    checked_at: date
    poll_id: Annotated[str, Field(pattern=r'^\d+$')] | None = None
    source: Source | None = None
    total_members: int = Field(default=0, ge=0)
    compared_members: int = Field(default=0, ge=0)
    matched_members: int = Field(default=0, ge=0)
    note: str = ''

    @model_validator(mode='after')
    def supplementary_provenance(self):
        if self.source:
            url = self.source.url
            if (not self.source.sha256 or url.scheme != 'https' or url.port != 443
                    or url.host != 'www.abgeordnetenwatch.de' or url.username or url.password
                    or url.path != f'/api/v2/polls/{self.poll_id}' or url.query != 'related_data=votes'):
                raise ValueError('Cross-check requires a fingerprinted abgeordnetenwatch poll, without credentials')
        if not self.matched_members <= self.compared_members <= self.total_members:
            raise ValueError('Cross-check member counts do not reconcile')
        if self.status in ('matched', 'partial', 'mismatch'):
            if not self.source or not self.poll_id or not self.compared_members:
                raise ValueError('Cross-check result requires source and member-level comparison')
            if (self.matched_members == self.compared_members) != (self.status != 'mismatch'):
                raise ValueError('Cross-check status disagrees with member-level results')
            if self.status != 'mismatch' and (self.compared_members == self.total_members) != (self.status == 'matched'):
                raise ValueError('Partial cross-check is not a complete identity match')
        return self


class VoteEvidence(Model):
    method: Literal['bundestag-dip-v1', 'bundestag-structured-v2'] = 'bundestag-structured-v2'
    procedure_id: Annotated[str, Field(pattern=r'^\d+$')]
    position_id: Annotated[str, Field(pattern=r'^\d+$')]
    decision_index: int = Field(ge=0)
    law_match: Literal['official_reference', 'exact_title']
    procedure_source: Source
    position_source: Source
    protocol_source: Source | None = None
    protocol_page: str | None = None
    protocol_format: Literal['xml'] | None = None
    protocol_fallback: Literal['not_listed', 'opendata_unavailable'] | None = None
    protocol_agenda: str | None = None
    protocol_block: int | None = Field(default=None, ge=0)
    protocol_comment_spans: list[tuple[int, int]] = Field(default_factory=list)
    document_numbers: list[str] = Field(default_factory=list)
    position_status: Literal['decision_only', 'no_structured_transcript', 'passage_not_found',
                            'ambiguous_passage', 'no_explicit_groups', 'groups_found',
                            'roll_call_found', 'roll_call_unmatched', 'partial_decision'] = 'decision_only'
    # The preserved source excerpt and exact quoted decision are available in the API.
    text: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    roll_call_id: Annotated[str, Field(pattern=r'^\d+$')] | None = None
    roll_call_source: Source | None = None
    ballot_index_source: Source | None = None
    ballot_number: int | None = Field(default=None, ge=1)
    ballot_match: Literal['official_title_and_tallies', 'unique_official_tallies'] | None = None
    cross_check: VoteCrossCheck | None = None

    @model_validator(mode='after')
    def source_citation(self):
        previous = 0
        for start, end in self.protocol_comment_spans:
            if not previous <= start <= end <= len(self.text):
                raise ValueError('XML commentary ranges must be ordered within the preserved excerpt')
            previous = end
        if self.quote not in self.text:
            raise ValueError('Vote quote must occur verbatim in its source excerpt')
        for source in [self.procedure_source, self.position_source,
                       self.protocol_source, self.roll_call_source, self.ballot_index_source]:
            if source and not official_vote_source(source):
                raise ValueError('Vote evidence requires fingerprinted official sources without credentials')
        return self


class Vote(Record):
    law_id: Identifier
    date: date
    motion: str
    type: Literal['roll_call', 'group_record', 'plenary_record']
    source: Source
    stage: Literal['final_passage', 'second_reading', 'amendment', 'resolution', 'procedural', 'unknown'] = 'unknown'
    decision: str = ''
    scope: Literal['whole_law', 'partial_law'] = 'whole_law'
    # Only the confirmed final whole-law vote is comparable to the enacted law's effects.
    compares_to_law: bool = False
    groups: list[GroupVote] = Field(default_factory=list)
    members: list[MemberVote] = Field(default_factory=list)
    evidence: VoteEvidence | None = None
    note: str = ''
    review: Review = Field(default_factory=Review)
    # Detect citizen edits before refreshing an automatically imported record.
    import_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')] | None = None

    @model_validator(mode='after')
    def documented_ballots(self):
        if len({g.group for g in self.groups}) != len(self.groups):
            raise ValueError('Duplicate voting group')
        parties = [g.party_id for g in self.groups if g.party_id]
        if len(set(parties)) != len(parties):
            raise ValueError('Duplicate party in voting groups')
        if self.type == 'roll_call':
            if not self.groups or any(g.yes is None for g in self.groups):
                raise ValueError('Roll calls require exact group counts')
        elif self.members or any(g.yes is not None for g in self.groups):
            raise ValueError('Non-roll-call records cannot invent members or counts')
        if self.type == 'group_record' and not self.groups:
            raise ValueError('Group records need documented positions')
        if self.type == 'plenary_record' and self.groups:
            raise ValueError('Decision-only records have no group positions')
        if self.compares_to_law and (self.stage != 'final_passage' or self.scope != 'whole_law' or not self.evidence
                                    or self.evidence.law_match != 'official_reference'):
            raise ValueError('Programme comparisons need a confirmed final whole-law vote')
        if self.evidence:
            if not official_vote_source(self.source):
                raise ValueError('Imported votes need a fingerprinted official source without credentials')
            if self.type == 'roll_call' and (not self.members or not self.evidence.roll_call_source
                                            or any(g.invalid is None for g in self.groups)):
                raise ValueError('Imported roll calls require reconciled individual ballots and all five counts')
            if self.evidence.method == 'bundestag-structured-v2':
                if self.type == 'group_record' and (not self.evidence.protocol_source
                        or self.evidence.protocol_format != 'xml' or self.evidence.protocol_block is None):
                    raise ValueError('Structured group positions require an identified XML chair block')
                if self.type == 'roll_call' and (not self.evidence.ballot_index_source
                        or not self.evidence.ballot_number or not self.evidence.ballot_match):
                    raise ValueError('Structured roll calls require an identified official workbook')
                if (self.compares_to_law and self.evidence.cross_check
                        and self.evidence.cross_check.status == 'mismatch'):
                    raise ValueError('Conflicting ballot sources are excluded from programme comparisons')
            for group in self.groups:
                if self.type != 'roll_call' and (not group.evidence_quote
                                                or group.evidence_quote not in self.evidence.quote):
                    raise ValueError('Group position must quote the specific voting decision')
        if self.members:
            if len({m.source_row for m in self.members}) != len(self.members):
                raise ValueError('Duplicate member ballot row')
            if {m.group for m in self.members} != {g.group for g in self.groups}:
                raise ValueError('Member groups do not match totals')
            for group in self.groups:
                for choice in ('yes', 'no', 'abstain', 'absent', 'invalid'):
                    total = sum(m.group == group.group and m.vote == choice for m in self.members)
                    if total != (getattr(group, choice) or 0):
                        raise ValueError('Member ballots do not reconcile with group totals')
        return self


class LawVotingCoverage(Model):
    law_id: Identifier
    checked_at: date
    status: Literal['recorded', 'decision_only', 'not_found', 'ambiguous', 'source_error', 'source_changed']
    procedure_ids: list[str] = Field(default_factory=list)
    vote_ids: list[Identifier] = Field(default_factory=list)
    reason: str


class VotingCoverage(Model):
    schema_version: Literal['1.0'] = '1.0'
    dataset: Literal['live'] = 'live'
    items: list[LawVotingCoverage]
    note: str = ('Coverage of imported laws, not all Bundestag business. Missing evidence is unknown, '
                 'not proof that a vote did not take place. Named ballots exist only for roll calls.')

    @model_validator(mode='after')
    def unique_laws(self):
        if len({item.law_id for item in self.items}) != len(self.items):
            raise ValueError('Duplicate law in voting coverage')
        return self


class ArchiveSourcePage(Model):
    url: HttpUrl
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class LawCoverage(Model):
    schema_version: Literal["1.0"] = "1.0"
    dataset: Literal["live"]
    period_start: date
    as_of: date
    date_basis: Literal["promulgation"]
    inventory_mode: Literal['archive', 'snapshot-and-rss'] = 'archive'
    parts: list[Literal["I", "II"]]
    kind: Literal["Gesetz"]
    official_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    complete: bool
    expected_ids: list[Identifier]
    pending_ids: list[Identifier]
    source_pages: list[ArchiveSourcePage] = Field(min_length=1)
    note: str

    @model_validator(mode="after")
    def reconciled(self):
        expected, pending = set(self.expected_ids), set(self.pending_ids)
        if (len(expected) != len(self.expected_ids) or len(pending) != len(self.pending_ids)
                or not pending <= expected or self.official_count != len(expected)
                or self.imported_count != len(expected) - len(pending) or self.complete != (not pending)
                or self.as_of < self.period_start or set(self.parts) != {"I", "II"}):
            raise ValueError("Law archive coverage is inconsistent")
        return self


RECORD_TYPES = {"programs": Program, "criteria": Criterion, "laws": Law, "impacts": Impact, "votes": Vote}
