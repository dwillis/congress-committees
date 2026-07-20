"""Orchestrate discovery, XML parsing, action enrichment and bioguide resolution."""

import logging
from typing import Callable, List, Optional

from .api import extract_agreed_to_date
from .gpo import fetch_resolution_text, fetch_resolution_xml, html_url, xml_url
from .legislators import LegislatorIndex
from .models import CommitteeChangeEvent, ResolutionRecord, to_events
from .parser import classify_title, parse_resolution_text, parse_resolution_xml

logger = logging.getLogger(__name__)


def congress_gov_url(congress: int, number: str) -> str:
    return f"https://www.congress.gov/bill/{congress}th-congress/house-resolution/{number}"


def collect_committee_changes(
    congress: int,
    *,
    client,
    gpo_fetch: Callable = fetch_resolution_xml,
    gpo_fetch_text: Callable = fetch_resolution_text,
    legislators: Optional[LegislatorIndex] = None,
    since: Optional[str] = None,
) -> List[ResolutionRecord]:
    """Return committee-change resolution records for a Congress.

    `client` is a CongressGovClient (or compatible); `gpo_fetch` resolves bill
    XML; `legislators` supplies name->bioguide resolution when provided.

    Congresses before the 110th have no XML rendition on GovInfo at all --
    `gpo_fetch` correctly returns None for these, and `gpo_fetch_text` is
    tried as a fallback against the plain-text rendition instead.
    """
    records: List[ResolutionRecord] = []
    for bill in client.list_committee_change_resolutions(congress, since=since):
        number = str(bill.get("number"))
        fetched = gpo_fetch(congress, number)
        if fetched:
            xml, package_id, _stage = fetched
            record = parse_resolution_xml(xml)
            record.govinfo_xml_url = xml_url(package_id)
        else:
            text_fetched = gpo_fetch_text(congress, number)
            if not text_fetched:
                logger.warning(
                    "No bill XML or text found for HRES %s in congress %s", number, congress
                )
                continue
            text, package_id, stage = text_fetched
            _, default_change = classify_title(bill.get("title", ""))
            if default_change is None:
                default_change = "addition"
            committee_changes, date = parse_resolution_text(
                text, default_change, congress=str(congress)
            )
            record = ResolutionRecord(
                congress=str(congress), type="HRES", number=number,
                title=bill.get("title", ""), stage=stage, date=date,
                committee_changes=committee_changes,
            )
            record.govinfo_xml_url = html_url(package_id)

        record.congress_gov_url = congress_gov_url(congress, number)
        record.actions = client.get_actions(congress, number)
        record.agreed_to_date = extract_agreed_to_date(record.actions)

        # A resolution's title can match the addition/removal patterns (and
        # even have an "ih" (introduced) rendition on GovInfo) long before --
        # or without ever -- actually being voted on. H.Res.1113 (119th
        # Congress), "Censuring Representative ... and Removing Him from the
        # House Committee on Homeland Security", was merely referred to the
        # Ethics Committee and never agreed to, yet its title alone was
        # enough to fabricate a real removal event. Nothing here has
        # happened unless/until the House actually agreed to it.
        if record.agreed_to_date is None:
            logger.info(
                "Skipping HRES %s in congress %s: not yet agreed to (stage=%s)",
                number, congress, record.stage,
            )
            continue

        if legislators:
            on_date = record.agreed_to_date or record.date
            for change in record.committee_changes:
                change.bioguide_id = legislators.lookup(change.member_name, on_date=on_date)

        records.append(record)
    return records


def collect_committee_change_events(congress: int, **kwargs) -> List[CommitteeChangeEvent]:
    """Resolution path, flattened to unified committee-change events."""
    events: List[CommitteeChangeEvent] = []
    for record in collect_committee_changes(congress, **kwargs):
        events.extend(to_events(record))
    return events
