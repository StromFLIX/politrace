"""The canonical, strict contracts. JSON Schemas are exported for non-Python consumers."""
from __future__ import annotations

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
    status: Literal["unassessed", "partial", "fulfilled", "contradicted"] = "unassessed"
    rationale: str = "Noch keine redaktionelle Bewertung."
    reviewer: str | None = None
    assessed_at: date | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def sourced_assessment(self):
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
    review: Review = Field(default_factory=Review)
    generation: list[Generation] = Field(default_factory=list)


class GroupVote(Model):
    group: str
    party_id: Identifier | None = None
    yes: int = Field(ge=0)
    no: int = Field(ge=0)
    abstain: int = Field(ge=0)
    absent: int = Field(ge=0)


class Vote(Record):
    law_id: Identifier
    date: date
    motion: str
    type: Literal["roll_call", "group_record"]
    source: Source
    groups: list[GroupVote] = Field(min_length=1)
    review: Review


RECORD_TYPES = {"programs": Program, "criteria": Criterion, "laws": Law, "impacts": Impact, "votes": Vote}
