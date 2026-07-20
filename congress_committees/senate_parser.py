"""Parse Senate committee-assignment resolutions (S.Res.) into rosters.

Unlike House H.Res. resolutions -- where the XML/text directly states an
addition or removal -- Senate S.Res. resolutions almost always restate a
committee's ENTIRE current roster every time anything about it changes (see
the project's design notes: comparing two of a Congress's numbered
resolutions is the only way to detect a member's removal, since it's never
stated explicitly). This module extracts rosters -- and the older,
pre-108th-Congress single-add schema, which IS an explicit addition -- from
resolution XML/text; senate_collector.py does the actual diffing against
previously-seen rosters to produce addition/removal events.

Known gap: a small number of older (100th-102nd Congress era) resolutions
appoint a single Senator to one or more committees with NO majority/minority
party language at all (e.g. S.Res.136, 102nd Congress: "Resolved, That the
Senator from Pennsylvania (Mr. Wofford) is hereby appointed to serve as a
member on the Committee on..."). classify_senate_title() can't classify
these (there's no party to attribute the seat to), so they're skipped rather
than guessed at -- the same "strictly better than bad data" tradeoff the
House resignation pipeline makes for ambiguous multi-signer letters.
"""

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

from bs4 import BeautifulSoup

Party = Literal["majority", "minority"]

_MINORITY_TITLE_RE = re.compile(r"\bminority\s+party\b", re.IGNORECASE)
_MAJORITY_TITLE_RE = re.compile(r"\bmajority\s+party\b", re.IGNORECASE)


def classify_senate_title(title: str) -> Optional[Party]:
    """Return "majority"/"minority" for a Senate committee-assignment
    resolution title, or None if the title isn't recognized as one.

    Senate titles never use the House's "elect"/"designat...membership"
    phrasing -- they're always framed as one party's own membership
    ("...to constitute the majority party's membership on...", "...making
    minority party appointments to...", "...to make a minority party
    appointment to the Committee on..."), so party language is both the
    classifier AND tells us which party's roster a resolution updates.
    Checked minority-first since "bipartisan"/other combinations never occur
    in practice but there's no reason to prefer one order over the other.
    """
    if _MINORITY_TITLE_RE.search(title or ""):
        return "minority"
    if _MAJORITY_TITLE_RE.search(title or ""):
        return "majority"
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_member(text: str) -> str:
    return _clean(text).rstrip(".,;")


def _clean_committee_name(text: str) -> str:
    return _clean(text).rstrip(":.—–").strip()


# A trailing role annotation ("(Chair)", "(Ranking)" -- confirmed live: the
# minority-party resolution prints the bare word, never "Ranking Member" --
# and "(ex officio)" for a party leader's ex officio seat on Intelligence) is
# a note about the preceding member, not part of their name -- strip it into
# `raw` the same way the House parser strips "Chairman"/"to rank..."
# qualifiers. Crucially, this does NOT match a state-disambiguation
# parenthetical ("(FL)", "(SC)", used only when two sitting Senators share a
# surname) -- that stays part of the clean name, since legislators.py's
# Senate lookup path parses it out from there (mirroring how the House's "of
# Texas" suffix stays in the name).
_SENATE_ROLE_QUALIFIER_RE = re.compile(
    r"\s*\(\s*(?:Chair|Vice\s+Chair(?:man|woman)?|Ranking(?:\s+Member)?|[Ee]x\s+[Oo]fficio)\s*\)\s*$",
    re.IGNORECASE,
)
_BLANK_SEAT_RE = re.compile(r"^_+$")


def _split_senate_members(text: str) -> List[Tuple[str, Optional[str]]]:
    """Split a Senate committee roster's member text into (clean, raw_or_None)
    pairs, same shape as CommitteeChange's member_name/member_name_raw.

    Rosters are comma-separated ("Mr. Boozman (Chair), Mr. McConnell, ...").
    A not-yet-filled seat prints as a run of underscores ("_______") and is
    skipped entirely -- it isn't a member.
    """
    fragments = [
        f.strip()
        for f in re.split(r"[,;](?![^(]*\))|\s+(?:and|&)\s+(?![^(]*\))", _clean(text))
        if f.strip()
    ]
    results = []
    for raw in fragments:
        raw = re.sub(r"^(?:and|&)\s+", "", raw, flags=re.IGNORECASE).strip()
        raw = _clean_member(raw)
        if not raw or _BLANK_SEAT_RE.match(raw):
            continue
        clean = _clean_member(_SENATE_ROLE_QUALIFIER_RE.sub("", raw))
        if not clean:
            continue
        results.append((clean, raw if raw != clean else None))
    return results


@dataclass
class SenateCommitteeRoster:
    """One committee's full restated membership from a single resolution."""

    committee: str
    committee_code: Optional[str]
    members: List[Tuple[str, Optional[str]]] = field(default_factory=list)


@dataclass
class SenateSingleAddition:
    """A single explicit addition (the older, pre-108th-Congress schema)."""

    committee: str
    member: str
    member_raw: Optional[str]
    until_date: Optional[str]


# The older single-add schema (100th-107th Congress era): "Resolved, That the
# following Senator shall be added to the majority/minority party's
# membership on the [Senate] Committee on X for the ... Congress [until
# DATE]: Mr. Chafee." Confirmed live against S.Res.137 (102nd Congress).
_SINGLE_ADD_RE = re.compile(
    r"the\s+following\s+Senator\s+shall\s+be\s+added\s+to\s+the\s+(?:majority|minority)\s+party.?s\s+"
    r"membership\s+on\s+the\s+(?:Senate\s+)?"
    r"(?P<committee>(?:Select\s+|Special\s+)?Committee\s+on\s+.+?)\s+for\s+the\s+.+?"
    # Non-greedy up to here, but the member name (always the resolution's
    # final sentence) must be matched GREEDILY to end-of-text -- "Mr." itself
    # contains a period, so a non-greedy `.+?\.` would stop at "Mr" and leave
    # "Chafee." behind.
    r"(?:\s+until\s+(?P<until>[A-Za-z]+\s+\d{1,2},?\s*\d{4}))?\s*:\s*(?P<member>.+)\.\s*$",
    re.IGNORECASE | re.DOTALL,
)


def parse_senate_resolution_xml(
    xml: bytes,
) -> Tuple[List[SenateCommitteeRoster], List[SenateSingleAddition]]:
    """Parse a Senate resolution bill XML document into committee rosters.

    Mirrors the House's <committee-appointment-paragraph>/<header>/<text>
    shape exactly (same DTD family) -- <committee-name committee-id="..."> is
    nested inside <header> in newer renditions, absent (plain text header) in
    older ones, same tolerant either/or handling as parser.parse_resolution_xml.
    """
    soup = BeautifulSoup(xml, "xml")
    rosters = []
    for para in soup.find_all("committee-appointment-paragraph"):
        header_tag = para.find("header")
        if not header_tag:
            continue
        name_tag = header_tag.find("committee-name")
        if name_tag:
            committee = _clean_committee_name(name_tag.get_text())
            code = name_tag.get("committee-id")
        else:
            committee = _clean_committee_name(header_tag.get_text())
            code = None
        if not committee:
            continue
        member_tag = para.find(name="text")
        member_text = member_tag.get_text() if member_tag else ""
        rosters.append(
            SenateCommitteeRoster(
                committee=committee, committee_code=code,
                members=_split_senate_members(member_text),
            )
        )
    return rosters, []


def parse_senate_resolution_text(
    text: str,
) -> Tuple[List[SenateCommitteeRoster], List[SenateSingleAddition]]:
    """Parse GovInfo/congress.gov's plain-text Senate resolution rendition.

    Handles both schemas: the single-add sentence (older era) and, for
    completeness, a full-roster restatement should one ever appear only in
    plain text (no XML rendition) -- structured the same way as the XML
    path's "Committee on X:\\n  members." paragraphs.
    """
    import html as _html

    flat = _clean(_html.unescape(re.sub(r"<[^>]+>", "", text)))
    resolved_idx = flat.find("Resolved,")
    operative = flat[resolved_idx:] if resolved_idx != -1 else flat

    m = _SINGLE_ADD_RE.search(operative)
    if m:
        member_raw = _clean_member(m.group("member"))
        member = _clean_member(_SENATE_ROLE_QUALIFIER_RE.sub("", member_raw))
        return [], [
            SenateSingleAddition(
                committee=_clean_committee_name(m.group("committee")),
                member=member,
                member_raw=member_raw if member_raw != member else None,
                until_date=m.group("until"),
            )
        ]

    # Full-roster text-mode schema: "Committee on X: Mr. Y, Mr. Z." blocks,
    # same boundary shape as the House's plain-text committee blocks.
    rosters = []
    for cm in re.finditer(
        r"Committee\s+on\s+(?P<committee>.+?)\s*:\s*(?P<members>.+?)"
        r"(?=Committee\s+on\s+[A-Za-z]|Attest\s*:|<all>|\Z)",
        operative,
        re.IGNORECASE | re.DOTALL,
    ):
        committee = _clean_committee_name(f"Committee on {cm.group('committee')}")
        if not committee:
            continue
        rosters.append(
            SenateCommitteeRoster(
                committee=committee, committee_code=None,
                members=_split_senate_members(cm.group("members")),
            )
        )
    return rosters, []
