"""Orchestrate discovery, XML parsing, action enrichment and bioguide resolution."""

import logging
from typing import Callable, List, Optional

from .api import extract_agreed_to_date
from .gpo import fetch_resolution_xml, xml_url
from .legislators import LegislatorIndex
from .models import ResolutionRecord
from .parser import parse_resolution_xml

logger = logging.getLogger(__name__)


def congress_gov_url(congress: int, number: str) -> str:
    return f"https://www.congress.gov/bill/{congress}th-congress/house-resolution/{number}"


def collect_committee_changes(
    congress: int,
    *,
    client,
    gpo_fetch: Callable = fetch_resolution_xml,
    legislators: Optional[LegislatorIndex] = None,
    since: Optional[str] = None,
) -> List[ResolutionRecord]:
    """Return committee-change resolution records for a Congress.

    `client` is a CongressGovClient (or compatible); `gpo_fetch` resolves bill XML;
    `legislators` supplies name->bioguide resolution when provided.
    """
    records: List[ResolutionRecord] = []
    for bill in client.list_committee_change_resolutions(congress, since=since):
        number = str(bill.get("number"))
        fetched = gpo_fetch(congress, number)
        if not fetched:
            logger.warning("No bill XML found for HRES %s in congress %s", number, congress)
            continue
        xml, package_id, _stage = fetched

        record = parse_resolution_xml(xml)
        record.govinfo_xml_url = xml_url(package_id)
        record.congress_gov_url = congress_gov_url(congress, number)
        record.actions = client.get_actions(congress, number)
        record.agreed_to_date = extract_agreed_to_date(record.actions)

        if legislators:
            for change in record.committee_changes:
                change.bioguide_id = legislators.lookup(change.member_name)

        records.append(record)
    return records
