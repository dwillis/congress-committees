"""Pydantic models for committee-change resolution output."""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field

ChangeType = Literal["addition", "removal"]


class CommitteeChange(BaseModel):
    """A single committee membership change effected by a resolution."""

    change_type: ChangeType = Field(
        ..., description="Whether the member is added to or removed from the committee"
    )
    committee: str = Field(..., description="Committee name as printed in the resolution")
    committee_code: Optional[str] = Field(
        None, description="House committee system code (e.g. 'HFA00') from the bill XML"
    )
    member_name: str = Field(..., description="Member name as printed (e.g. 'Mr. Gallagher')")
    bioguide_id: Optional[str] = Field(
        None, description="Bioguide ID of the member, if resolved"
    )


class BillAction(BaseModel):
    """A single action on the resolution from the congress.gov actions endpoint."""

    date: Optional[str] = Field(None, description="Action date (YYYY-MM-DD)")
    text: str = Field(..., description="Action text")
    type: Optional[str] = Field(None, description="Action type")


class ResolutionRecord(BaseModel):
    """A committee-change resolution with its changes and (optionally) actions."""

    congress: str
    type: str
    number: str
    title: str
    stage: Optional[str] = None
    date: Optional[str] = Field(
        None, description="Date from the bill XML action-date (YYYY-MM-DD)"
    )
    govinfo_xml_url: Optional[str] = None
    congress_gov_url: Optional[str] = None
    actions: List[BillAction] = Field(default_factory=list)
    agreed_to_date: Optional[str] = None
    committee_changes: List[CommitteeChange] = Field(default_factory=list)


Source = Literal["resolution", "congressional_record"]


class ResolutionRef(BaseModel):
    """Source reference for a resolution-derived committee change."""

    type: Literal["resolution"] = "resolution"
    number: str
    stage: Optional[str] = None
    agreed_to_date: Optional[str] = None
    congress_gov_url: Optional[str] = None
    govinfo_xml_url: Optional[str] = None


class RecordRef(BaseModel):
    """Source reference for a Congressional Record resignation letter."""

    type: Literal["congressional_record"] = "congressional_record"
    volume: Optional[str] = None
    issue: Optional[str] = None
    page: Optional[str] = None
    granule_id: Optional[str] = None
    signed_date: Optional[str] = None
    url: Optional[str] = None


SourceRef = Annotated[Union[ResolutionRef, RecordRef], Field(discriminator="type")]


class CommitteeChangeEvent(BaseModel):
    """A single committee membership change, from either source."""

    congress: str
    change_type: ChangeType
    committee: str
    system_code: Optional[str] = Field(None, description="congress.gov system code, e.g. hsfa00")
    gpo_code: Optional[str] = Field(None, description="GPO bill-XML code, e.g. HFA00")
    member_name: Optional[str] = None
    bioguide_id: Optional[str] = None
    date: Optional[str] = None
    source: Source
    source_ref: SourceRef


def to_events(record: ResolutionRecord) -> List[CommitteeChangeEvent]:
    """Flatten a resolution record's nested changes into unified events."""
    ref = ResolutionRef(
        number=record.number, stage=record.stage,
        agreed_to_date=record.agreed_to_date,
        congress_gov_url=record.congress_gov_url,
        govinfo_xml_url=record.govinfo_xml_url,
    )
    return [
        CommitteeChangeEvent(
            congress=record.congress, change_type=c.change_type, committee=c.committee,
            gpo_code=c.committee_code, member_name=c.member_name,
            bioguide_id=c.bioguide_id,
            date=record.agreed_to_date or record.date,
            source="resolution", source_ref=ref,
        )
        for c in record.committee_changes
    ]
