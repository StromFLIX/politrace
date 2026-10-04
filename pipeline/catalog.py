"""Auditable source inventory and fail-closed permission gate for public backfills."""
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from pipeline.models import Identifier, Model


class Rights(Model):
    status: Literal["permission-required", "noncommercial-text-permitted"]
    terms_url: HttpUrl
    license_url: HttpUrl | None = None
    note: str = Field(min_length=20)


class ProgrammeSource(Model):
    id: Identifier
    party_id: Identifier
    members: list[str] = Field(min_length=1)
    title: str
    pdf_url: HttpUrl
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    pages: int = Field(ge=1)
    textless_pages: list[int]
    published: date | None
    publication_note: str
    transcription_note: str
    rights: Rights

    @model_validator(mode="after")
    def inspected_pages(self):
        if len(set(self.textless_pages)) != len(self.textless_pages) or any(
            p < 1 or p > self.pages for p in self.textless_pages
        ):
            raise ValueError("Invalid inspected textless pages")
        if self.rights.status == "noncommercial-text-permitted" and (
            not self.published or not self.rights.license_url
        ):
            raise ValueError("Permitted imports require publication metadata and an actual licence")
        return self

    def require_publication_basis(self):
        if self.rights.status != "noncommercial-text-permitted":
            raise PermissionError(f"{self.id}: public full-text reuse permission is not established; see {self.rights.terms_url}")


class SourceCatalog(Model):
    schema_version: Literal["1.0"]
    period_start: date
    election_year: int
    checked_at: date
    representation_source: HttpUrl
    period_source: HttpUrl
    scope_note: str
    law_date_basis: str
    programs: list[ProgrammeSource]

    @model_validator(mode="after")
    def complete_scope(self):
        parties = {p.party_id for p in self.programs}
        if parties != {"cdu-csu", "spd", "gruene", "afd", "linke", "ssw"} or len(self.programs) != 6:
            raise ValueError("The 21st Bundestag catalog must include all six programme groups, including SSW")
        if len({p.id for p in self.programs}) != len(self.programs):
            raise ValueError("Duplicate programme ID in source catalog")
        if any(p.published and p.published > self.period_start for p in self.programs):
            raise ValueError("Programme postdates comparison window")
        return self


def load_catalog(root: Path):
    return SourceCatalog.model_validate_json((root / "sources" / "bundestag-21.json").read_text())
