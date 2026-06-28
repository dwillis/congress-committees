"""Collect committee resignations from Congressional Record granules into events."""

import logging
import re
from typing import List, Optional

from .committees import CommitteeIndex
from .legislators import LegislatorIndex
from .models import CommitteeChangeEvent, RecordRef
from .parser import parse_resignation_granule

logger = logging.getLogger(__name__)


# Best-effort: does not strip generational suffixes (e.g. "Jr."/"III"), so such a
# suffix may become the surname token; acceptable since lookup is best-effort.
def _split_name(full: Optional[str]):
    if not full:
        return "", ""
    parts = re.sub(r"\s+", " ", full).strip().split(" ")
    return parts[0], parts[-1]


def _issue_date_from_package(package_id: str) -> Optional[str]:
    m = re.search(r"CREC-(\d{4})-(\d{2})-(\d{2})", package_id or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def collect_resignations(
    *, congress: int, client, start: str, end: str,
    committees: Optional[CommitteeIndex] = None,
    legislators: Optional[LegislatorIndex] = None,
) -> List[CommitteeChangeEvent]:
    events: List[CommitteeChangeEvent] = []
    for granule in client.discover_resignations(start, end):
        gid = granule["granuleId"]
        pid = granule.get("packageId", "")
        text, meta = client.fetch_granule(pid, gid)
        parsed = parse_resignation_granule(granule.get("title", ""), text)
        if not parsed.member_name:
            logger.warning("No signer parsed for granule %s", gid)
        issue_date = _issue_date_from_package(pid)
        first, last = _split_name(parsed.member_name)
        bioguide = (legislators.lookup_full_name(first, last, issue_date)
                    if legislators and parsed.member_name else None)
        ref = RecordRef(granule_id=gid, page=meta.get("page"),
                        signed_date=parsed.signed_date, url=meta.get("url"))
        for committee in parsed.committees or [None]:
            system_code = committees.code_for(committee) if (committees and committee) else None
            events.append(CommitteeChangeEvent(
                congress=str(congress), change_type="removal",
                committee=committee or "", system_code=system_code,
                member_name=parsed.member_name, bioguide_id=bioguide,
                date=issue_date, source="congressional_record", source_ref=ref,
            ))
    return events
