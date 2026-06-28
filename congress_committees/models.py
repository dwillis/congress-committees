"""Pydantic models for committee-change resolution output."""

from typing import List, Literal, Optional

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
