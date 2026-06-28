"""Parse GPO bill XML for House committee-change resolutions."""

import re
from typing import Optional, Tuple

from bs4 import BeautifulSoup

from .models import ChangeType, CommitteeChange, ResolutionRecord

# Title patterns that mark a resolution as effecting committee membership changes,
# paired with the default change type they imply.
_ADDITION_PATTERNS = (
    re.compile(r"\belecting\b.*\bcommittee", re.IGNORECASE),
    re.compile(r"\belection of\b.*\bcommittee", re.IGNORECASE),
)
_REMOVAL_PATTERNS = (
    re.compile(r"\bdischarg\w*\b.*\bcommittee", re.IGNORECASE),
    re.compile(r"\bresign\w*\b.*\bcommittee", re.IGNORECASE),
    re.compile(r"\bremov\w*\b.*\bcommittee", re.IGNORECASE),
)


def classify_title(title: str) -> Tuple[bool, Optional[ChangeType]]:
    """Return (is_committee_change, default_change_type) for a resolution title."""
    for pat in _REMOVAL_PATTERNS:
        if pat.search(title):
            return True, "removal"
    for pat in _ADDITION_PATTERNS:
        if pat.search(title):
            return True, "addition"
    return False, None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_member(text: str) -> str:
    return _clean(text).rstrip(".,;")


def parse_resolution_xml(xml: bytes) -> ResolutionRecord:
    """Parse a GPO resolution bill XML document into a ResolutionRecord."""
    soup = BeautifulSoup(xml, "xml")

    title = _clean(soup.find("official-title").get_text()) if soup.find("official-title") else ""

    # dc:title looks like "119 HRES 1381 EH: Electing a Member ...".
    congress = number = ""
    bill_type = "HRES"
    dc_title = soup.find("title")
    if dc_title:
        m = re.match(
            r"\s*(?P<congress>\d+)\s+(?P<type>[A-Z]+)\s+(?P<number>\d+)",
            dc_title.get_text(),
        )
        if m:
            congress = m.group("congress")
            bill_type = m.group("type")
            number = m.group("number")

    resolution = soup.find("resolution")
    stage = resolution.get("resolution-stage") if resolution else None

    date = None
    action_date = soup.find("action-date")
    if action_date and action_date.get("date"):
        raw = action_date["date"]  # e.g. "20260624"
        if len(raw) == 8 and raw.isdigit():
            date = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    _, default_change = classify_title(title)
    if default_change is None:
        default_change = "addition"

    committee_changes = []
    for para in soup.find_all("committee-appointment-paragraph"):
        name_tag = para.find("committee-name")
        if not name_tag:
            continue
        member_tag = para.find(name="text")
        committee_changes.append(
            CommitteeChange(
                change_type=default_change,
                committee=_clean(name_tag.get_text()),
                committee_code=name_tag.get("committee-id"),
                member_name=_clean_member(member_tag.get_text()) if member_tag else "",
            )
        )

    return ResolutionRecord(
        congress=congress,
        type=bill_type,
        number=number,
        title=title,
        stage=stage,
        date=date,
        committee_changes=committee_changes,
    )
