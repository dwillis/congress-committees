"""Collect committee resignations from Congressional Record granules into events."""

import logging
import re
from typing import List, Optional

from .committees import CommitteeIndex
from .legislators import LegislatorIndex
from .models import CommitteeChangeEvent, RecordRef
from .parser import parse_resignation_granule

logger = logging.getLogger(__name__)

# A granule titled "RESIGNATIONS AS MEMBERS OF..." (plural) holds more than
# one signer's letter (CREC-1994-05-19, 103rd Congress: two members
# temporarily giving up a committee seat to serve on another). The
# single-signer extraction below (_extract_signer/parse_resignation_granule)
# isn't built for that shape -- it anchors on ONE trailer sentence and ONE
# role line, and a second, unrelated "Without objection" phrase elsewhere in
# the granule (e.g. a following committee-roster announcement) can make it
# confidently extract the WRONG text as a "name" instead of failing loudly.
# Skipping here, rather than guessing, is strictly better than bad data.
_MULTI_SIGNER_TITLE_RE = re.compile(r"\bRESIGNATIONS\b", re.IGNORECASE)


# Generational suffixes and post-nominal credentials that must not be
# mistaken for the surname token. Covers both comma-separated ("Rich
# McCormick, MD, MBA") and bare-appended ("Neal P. Dunn M.D.") forms -- the
# comma form is also handled by the split below, but a credential can appear
# with no comma at all before it.
_TRAILING_SUFFIXES = {
    "jr", "sr", "ii", "iii", "iv", "v",
    "md", "do", "phd", "jd", "esq", "dds", "dvm", "rn", "mba", "cpa", "mph", "edd",
}

# A leading title before the actual first name ("Rep. Peter T. King,",
# "Congressman Vern Buchanan.") -- otherwise the "first" token becomes the
# title itself, which fails first-name disambiguation against another member
# sharing the surname.
_LEADING_TITLE_RE = re.compile(
    r"^(?:Rep|Representative|Congressman|Congresswoman|Hon|Dr|Mr|Mrs|Ms|Miss)\.?\s+",
    re.IGNORECASE,
)

# A state-district code glued directly to the name ("Ken Calvert (CA-44)")
# -- otherwise the surname lookup's last "token" becomes "(CA-44)" instead of
# the real surname.
_DISTRICT_CODE_RE = re.compile(r"\s*\([A-Z]{2}-\d+\)\s*$")


def _clean_signer_name(full: Optional[str]) -> str:
    """Strip noise from a signer's printed name, keeping it as one string.

    Signatures carry noise the legislator lookup can't use: a leading title
    ("Rep. Peter T. King"), post-nominal credentials, comma-separated ("Rich
    McCormick, MD, MBA") or bare-appended ("Neal P. Dunn M.D."), generational
    suffixes ("Rudy Yakym III", "Donald S. Beyer Jr."), and a glued-on
    state-district code ("Ken Calvert (CA-44)"). All are dropped.

    Deliberately NOT split into (first, last) tokens here -- a real surname
    can be multiple words ("Herrera Beutler", "Wasserman Schultz"), and there's
    no reliable way to tell that apart from "First Middle Last" by shape alone
    (a middle initial like "F." looks just as short as a real surname's first
    word). LegislatorIndex.lookup() already solves this correctly by trying
    progressively shorter surname candidates against the actual index; passing
    it the whole cleaned name lets it do that instead of us guessing here.
    """
    if not full:
        return ""
    base = re.sub(r"\s+", " ", full).strip().split(",")[0].strip()
    base = _LEADING_TITLE_RE.sub("", base)
    base = _DISTRICT_CODE_RE.sub("", base)
    parts = base.split(" ") if base else [""]
    while len(parts) > 1 and parts[-1].replace(".", "").lower() in _TRAILING_SUFFIXES:
        parts.pop()
    return " ".join(parts)


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
        title = granule.get("title", "")
        if _MULTI_SIGNER_TITLE_RE.search(title):
            logger.warning(
                "Skipping multi-signer resignation granule %s (%r) -- not supported", gid, title
            )
            continue
        text, meta = client.fetch_granule(pid, gid)
        parsed = parse_resignation_granule(title, text)
        if not parsed.member_name:
            logger.warning("No signer parsed for granule %s", gid)
        issue_date = _issue_date_from_package(pid)
        cleaned_name = _clean_signer_name(parsed.member_name)
        bioguide = (legislators.lookup(cleaned_name, on_date=issue_date)
                    if legislators and cleaned_name else None)
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
