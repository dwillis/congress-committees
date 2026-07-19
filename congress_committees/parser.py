"""Parse GPO bill XML for House committee-change resolutions."""

import html
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from .dates import organizing_window
from .legislators import _STATES
from .models import ChangeType, CommitteeChange, ResolutionRecord

# Title patterns that mark a resolution as effecting committee membership changes,
# paired with the default change type they imply.
_ADDITION_PATTERNS = (
    re.compile(r"\belecting\b.*\bcommittee", re.IGNORECASE),
    re.compile(r"\belection of\b.*\bcommittee", re.IGNORECASE),
    # H.Res.33/34 (108th Congress): "Designating majority/minority membership
    # on certain standing committees of the House." -- no "electing" at all.
    re.compile(r"\bdesignat\w*\b.*\bmembership\b.*\bcommittee", re.IGNORECASE),
)
_REMOVAL_PATTERNS = (
    re.compile(r"\bdischarg\w*\b.*\bcommittee", re.IGNORECASE),
    re.compile(r"\bresign\w*\b.*\bcommittee", re.IGNORECASE),
    re.compile(r"\bremov\w*\b.*\bcommittee", re.IGNORECASE),
)

# A trailing qualifier clause on a member entry (e.g. "Mr. Ryan of New York, to
# rank immediately after Ms. Strickland." or "Ms. DeLauro, Chair.") names a
# role/seniority note, not a second member -- strip it before comma-splitting
# the member list, or it gets misread as an extra name. The comma is optional:
# GPO's pre-XML-era plain-text bill rendition sometimes omits it entirely
# ("Mr. Crenshaw to rank after Mr. Ryun of Kansas").
# "following" is only safe as a rank-qualifier preposition when the "to/shall
# rank" verb phrase is right there with it ("shall rank immediately following
# Mr. Camp") -- unlike "after"/"ahead of", it's an ordinary English word that
# also shows up in unrelated constructions (e.g. "both to rank in the named
# order following Mr. Ryun of Kansas", where "following" just introduces the
# shared reference point for a NAMED-ORDER clause, not a rank-qualifier of its
# own). Bare "after"/"ahead of" with no verb at all is still allowed, matching
# the pre-existing (verb-optional) behavior for those two. "who will rank"
# (H.Res.166, 104th Congress: "Mr. Skelton of Missouri, who will rank after
# Mr. LaFalce of New York") is the same clause with a relative-pronoun lead-in
# and "will" instead of "to"/"shall".
_RANK_QUALIFIER_CORE = (
    r"(?:(?:who\s+)?(?:to|shall|will)\s+rank(?:\s+immediately)?\s+(?:after|ahead\s+of|following)"
    r"|(?:after|ahead\s+of))"
)
_TRAILING_QUALIFIER_RE = re.compile(
    r",?\s*(?:"
    rf"{_RANK_QUALIFIER_CORE}\s+.+"
    r"|(?:Vice\s+)?Chair(?:man|woman)?"
    r"|Ranking(?:\s+Minority)?\s+Member"
    r")\.?\s*$",
    re.IGNORECASE,
)

# The same qualifiers also appear parenthesized, possibly mid-list:
# "Mr. LaLota (to rank immediately after Mr. Crane), Mr. Fry." A newly-elected
# member not yet sworn in at vote time carries "(when sworn)" instead.
_PAREN_QUALIFIER_RE = re.compile(
    r"\s*\((?:"
    rf"{_RANK_QUALIFIER_CORE}\s+[^)]*"
    r"|(?:Vice\s+)?Chair(?:man|woman)?"
    r"|Ranking(?:\s+Minority)?\s+Member"
    r"|when\s+sworn"
    r")\)",
    re.IGNORECASE,
)

# A fragment that, on its own, IS just a bare qualifier clause (no name) --
# produced when the comma-form qualifier (not parenthesized) gets split off
# from its member by the naive comma split below and needs reattaching. A
# generational suffix followed by "of <State>" (H.Res.337, 104th Congress:
# "Mr. Jesse Jackson, Jr. of Illinois") is the same shape -- the comma before
# "Jr." splits it off from the name it actually belongs to.
_BARE_QUALIFIER_RE = re.compile(
    r"^(?:"
    rf"{_RANK_QUALIFIER_CORE}\s+.+"
    r"|(?:Vice\s+)?Chair(?:man|woman)?"
    r"|Ranking(?:\s+Minority)?\s+Member"
    r"|(?:Jr|Sr|II|III|IV)\.?\s+of\s+.+"
    r")\.?$",
    re.IGNORECASE,
)

# Distinguishes a Chair/Chairman/Chairwoman qualifier from the OTHER
# qualifier types (rank-order, "when sworn", Ranking Member) that also
# survive into member_name_raw -- used to tell whether THIS resolution names
# its own chair (rank 1), rather than assuming the chair was elected
# separately (see _rank_offset below).
_CHAIR_DESIGNATION_RE = re.compile(r"\b(?:Vice\s+)?Chair(?:man|woman)?\b", re.IGNORECASE)


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


def _clean_committee_name(text: str) -> str:
    # Older resolution XML sometimes trails a committee header with a period
    # and em/en dash instead of (or in addition to) a colon, e.g. "Committee
    # on Standards of Official Conduct.—". Some (older) documents also print
    # a header in all-lowercase ("Committee on agriculture:") inconsistently
    # alongside correctly title-cased ones in the SAME resolution -- normalize
    # with the same title-casing already used for resignation committee names.
    cleaned = _clean(text).rstrip(":.—–").strip()
    return _titlecase_committee(cleaned) if cleaned else cleaned


def _split_members(text: str) -> List[str]:
    """Split a committee-appointment paragraph's member text into printed names.

    The text lists members comma-separated, e.g. "Mr. Hoyer, Ms. Kaptur, Mr.
    Bishop of Georgia." A name may carry an "of <State>" suffix or a multi-word
    surname (no internal comma), so the comma is a safe delimiter. A leading
    "and "/"& " (as in "X, Y, and Z") is stripped from the final fragment.
    """
    members = []
    for part in _clean(text).split(","):
        member = re.sub(r"^(?:and|&)\s+", "", part.strip(), flags=re.IGNORECASE)
        member = _clean_member(member)
        if member:
            members.append(member)
    return members


def _split_members_with_notes(text: str) -> List[Tuple[str, Optional[str]]]:
    """Split a member-list paragraph into (clean_name, raw_or_None) pairs.

    ``raw`` is the full printed entry and is populated only when it carries a
    rank/qualifier note beyond the plain name (e.g. "Mr. LaLota (to rank
    immediately after Mr. Crane)" or "Mr. Ryan of New York, to rank immediately
    after Ms. Strickland"); otherwise it's None.

    Splits on commas, semicolons, AND standalone " and "/" & " that are NOT
    inside parentheses, so a parenthesized qualifier's internal punctuation or
    "and" isn't mistaken for a list separator -- but two members can also be
    joined by "and" alone with no comma at all (e.g. "Mr. Higgins ... (to rank
    immediately after Mr. Jeffries) and Mr. Boyle ... (to rank immediately
    after Mr. Higgins)"). A non-parenthesized qualifier still lands in its own
    split-off fragment (it has no name of its own) -- that bare fragment is
    reattached to the preceding member rather than treated as an extra one.

    Commas and semicolons are BOTH always split points -- never mutually
    exclusive. A member's own qualifier comma ("Mrs. Miller of Michigan,
    Chair") sometimes prompts the list to use semicolons between the OTHER
    entries too ("...Chair; Mr. Harper; ...; and Mrs. Comstock."), but a
    document can also mix conventions, using a semicolon only once to escape
    that one qualifier comma while the rest of the list stays comma-separated
    ("Ms. Lofgren ..., Chairman; Mr. Chandler, Mr. Butterfield, ...").
    Switching to semicolon-EXCLUSIVE splitting whenever a semicolon appears
    anywhere would leave that comma-separated remainder glued into one bogus
    "member" -- so both delimiters always apply, and the bare-qualifier
    reattachment below (which already handles the equivalent case for commas
    alone) fixes up whichever fragment was actually just a qualifier.
    """
    raw_fragments = [
        f.strip()
        for f in re.split(r"[,;](?![^(]*\))|\s+(?:and|&)\s+(?![^(]*\))", _clean(text))
        if f.strip()
    ]

    merged: List[str] = []
    for frag in raw_fragments:
        candidate = re.sub(r"^(?:and|&)\s+", "", frag, flags=re.IGNORECASE).strip()
        if merged and _BARE_QUALIFIER_RE.match(candidate):
            merged[-1] = f"{merged[-1]}, {frag}"
        else:
            merged.append(frag)

    results = []
    for raw in merged:
        raw = re.sub(r"^(?:and|&)\s+", "", raw, flags=re.IGNORECASE).strip()
        clean = _PAREN_QUALIFIER_RE.sub("", raw)
        clean = _TRAILING_QUALIFIER_RE.sub("", clean)
        clean = _clean_member(clean)
        if not clean:
            continue
        raw = _clean_member(raw)
        results.append((clean, raw if raw != clean else None))
    return results


def _rank_offset(pairs: List[Tuple[str, Optional[str]]], in_organizing_window: bool):
    """Return (assign_ranks, offset) for a committee's ordered member list.

    Normally the chair/ranking member holds rank 1 via a separate,
    single-member resolution, so the first printed name in a multi-member
    list here is rank 2 -- UNLESS this resolution names its own chair
    explicitly (e.g. "Mr. Conaway, Chairman; Mr. Dent; ..."), in which case
    that entry IS rank 1 and the offset shifts down by one. An explicitly
    named chair earns rank 1 even alone in an otherwise single-member list.
    """
    if not in_organizing_window:
        return False, None
    if pairs and pairs[0][1] and _CHAIR_DESIGNATION_RE.search(pairs[0][1]):
        return True, 1
    if len(pairs) > 1:
        return True, 2
    return False, None


def _parse_joint_committee_changes(
    soup: BeautifulSoup, default_change: ChangeType, in_organizing_window: bool
) -> List[CommitteeChange]:
    """Parse Joint Committee elections (Library, Printing, ...), a different
    XML schema entirely from standing-committee resolutions.

    There's no <committee-appointment-paragraph> at all -- each joint
    committee gets its own <subsection> with a plain-text <header> (the
    committee name) and one <paragraph> per elected member, introduced by a
    sentence containing "elected" (checked so an unrelated subsection in the
    same resolution, e.g. procedural boilerplate, isn't mistaken for a
    committee roster).
    """
    changes = []
    for subsection in soup.find_all("subsection"):
        header = subsection.find("header")
        intro = subsection.find("text")
        if not header or not intro or "elect" not in intro.get_text().lower():
            continue
        committee = _clean_committee_name(header.get_text())
        if not committee:
            continue
        pairs = []
        for para in subsection.find_all("paragraph"):
            member_tag = para.find(name="text")
            if member_tag:
                pairs.extend(_split_members_with_notes(member_tag.get_text()))
        assign_ranks, offset = _rank_offset(pairs, in_organizing_window)
        for i, (member, raw) in enumerate(pairs):
            changes.append(
                CommitteeChange(
                    change_type=default_change,
                    committee=committee,
                    committee_code=None,
                    member_name=member,
                    member_name_raw=raw,
                    party_rank=(i + offset) if assign_ranks else None,
                )
            )
    return changes


def _parse_enumerated_paragraph_changes(
    soup: BeautifulSoup, default_change: ChangeType, in_organizing_window: bool
) -> List[CommitteeChange]:
    """Parse a third schema variant (e.g. 111th Congress organizing
    resolutions): enumerated <paragraph> elements directly in a <section>,
    each carrying <enum>, <header>Committee name</header>, and <text>members</text>.

    Guards: the enclosing section's intro sentence must mention "elect" (so
    header-bearing paragraphs in ordinary rules resolutions aren't mistaken
    for committee rosters), and paragraphs inside a <subsection> are skipped
    (those belong to the Joint Committee schema, whose member paragraphs have
    no headers anyway -- this keeps the two parsers strictly disjoint).
    """
    changes = []
    for para in soup.find_all("paragraph"):
        header = para.find("header")
        member_tag = para.find(name="text")
        if not header or not member_tag:
            continue
        if para.find_parent("subsection") is not None:
            continue
        section = para.find_parent("section")
        intro = section.find(name="text") if section else None
        if not intro or "elect" not in intro.get_text().lower():
            continue
        committee = _clean_committee_name(header.get_text())
        if not committee:
            continue
        pairs = _split_members_with_notes(member_tag.get_text())
        assign_ranks, offset = _rank_offset(pairs, in_organizing_window)
        for i, (member, raw) in enumerate(pairs):
            changes.append(
                CommitteeChange(
                    change_type=default_change,
                    committee=committee,
                    committee_code=None,
                    member_name=member,
                    member_name_raw=raw,
                    party_rank=(i + offset) if assign_ranks else None,
                )
            )
    return changes


def parse_resolution_xml(xml: bytes) -> ResolutionRecord:
    """Parse a GPO resolution bill XML document into a ResolutionRecord."""
    soup = BeautifulSoup(xml, "xml")

    title = _clean(soup.find("official-title").get_text()) if soup.find("official-title") else ""

    # dc:title looks like "119 HRES 1381 EH: Electing a Member ...". Some
    # older resolution XML has no <metadata>/<dc:title> block at all -- fall
    # back to the <congress>/<legis-num> tags in <form>, which every
    # resolution has regardless of era.
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
    if not congress:
        congress_tag = soup.find("congress")
        if congress_tag:
            cm = re.match(r"\s*(\d+)", congress_tag.get_text())
            if cm:
                congress = cm.group(1)
    if not number:
        legis_num = soup.find("legis-num")
        if legis_num:
            nm = re.search(r"(\d+)\s*$", legis_num.get_text().strip())
            if nm:
                number = nm.group(1)

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

    # Rank-and-file members of an organizing resolution are printed in party-
    # seniority order; the chair/ranking member holds rank 1 via a separate,
    # single-member resolution, so the first printed name here is rank 2. Only
    # meaningful within a Congress's opening organizing window -- a later
    # multi-member resolution appends members to the bottom of a roster, not a
    # fresh seniority list.
    in_organizing_window = False
    if congress and date:
        try:
            lo, hi = organizing_window(int(congress))
            in_organizing_window = lo <= date <= hi
        except ValueError:
            pass

    committee_changes = []
    for para in soup.find_all("committee-appointment-paragraph"):
        name_tag = para.find("committee-name")
        header_tag = para.find("header")
        if name_tag:
            committee = _clean_committee_name(name_tag.get_text())
            code = name_tag.get("committee-id")
        elif header_tag:
            # Pre-119th-Congress GPO resolution XML has no <committee-name> tag --
            # the name is plain text directly in <header>, colon and all.
            committee = _clean_committee_name(header_tag.get_text())
            code = None
        else:
            continue
        if not committee:
            continue
        member_tag = para.find(name="text")
        member_text = member_tag.get_text() if member_tag else ""
        pairs = _split_members_with_notes(member_text)
        assign_ranks, offset = _rank_offset(pairs, in_organizing_window)
        for i, (member, raw) in enumerate(pairs):
            committee_changes.append(
                CommitteeChange(
                    change_type=default_change,
                    committee=committee,
                    committee_code=code,
                    member_name=member,
                    member_name_raw=raw,
                    party_rank=(i + offset) if assign_ranks else None,
                )
            )
    committee_changes.extend(
        _parse_joint_committee_changes(soup, default_change, in_organizing_window)
    )
    committee_changes.extend(
        _parse_enumerated_paragraph_changes(soup, default_change, in_organizing_window)
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


_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}

# GovInfo never digitized bill XML for Congresses before the 110th -- only a
# plain-text rendition exists. Structurally it's a "Committee: Member,
# Qualifier, Member, ...." line per committee (the "on" in "Committee on X"
# is sometimes dropped as a typo in the source, and older resolutions use a
# numbered "(1) Committee on X.--Member." form instead of a colon), so the
# same member-splitting/qualifier/rank logic already built for XML applies
# once the raw text is isolated per committee via regex.
#
# The preamble format itself varies by era/stage: "eh"-era text reads "In the
# House of Representatives, U.S.,\n\nJanuary 4, 2005." (comma, "U.S.,",
# trailing period); the older "ath" (Agreed to House) stage instead reads
# "IN THE HOUSE OF REPRESENTATIVES\n\nFebruary 13, 2003" (all-caps, no
# "U.S.,", no comma, no trailing period) -- both optional pieces below.
_TEXT_DATE_RE = re.compile(
    r"House\s+of\s+Representatives,?\s*(?:U\.?\s*S\.?,\s*)?"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})\.?",
    re.IGNORECASE,
)
# "Attest:" ends most-era resolutions; older "ath"-stage ones instead end with
# a bare "<all>" end-of-bill-text marker and no "Attest:" at all.
_TEXT_COMMITTEE_BLOCK_RE = re.compile(
    r"(?:\(\d+\)\s*)?Committee\s+(?:on\s+)?(?P<committee>.+?)\s*(?:\.--|:|\.)\s*"
    r"(?P<members>.+?)(?=(?:\(\d+\)\s*)?Committee\s+(?:on\s+)?[A-Za-z]"
    r"|Resolved,\s*That\b|In\s+lieu\s+of\b|Attest\s*:|<all>|\Z)",
    re.DOTALL,
)

# A trailing GROUP qualifier applies to the whole preceding member list at
# once, not to a single member ("Mr. Collins of Georgia and Mr. Wamp of
# Tennessee, both to rank in the named order following Mr. Ryun of Kansas.");
# HRES.30 (106th Congress) uses "all" for a three-member list the same way.
# H.Res.166 (104th Congress) phrases the same shape differently: "Mr. Pickett
# of Virginia and Mr. Pallone of New Jersey, both of whom will rank in order
# after Mr. Ortiz of Texas." -- "of whom" added, "will" instead of "to", and
# "in order" instead of "in the named order". Unlike the per-member
# qualifiers above, it doesn't attach to any ONE preceding name, so it can't
# be recovered by the bare-qualifier reattachment in _split_members_with_notes
# -- strip it from the members text before splitting, or it gets misread as
# its own bogus extra "member".
_NAMED_ORDER_GROUP_QUALIFIER_RE = re.compile(
    r"[,;]?\s*(?:both|all)(?:\s+of\s+whom)?\s+(?:to|will)\s+rank\s+in\s+"
    r"(?:the\s+named\s+)?order\s+(?:after|ahead\s+of|following)\s+.+?\.\s*$",
    re.IGNORECASE,
)

# An older (105th-Congress-and-earlier) member-list schema drops the "Mr./
# Ms./Mrs./Miss" honorific entirely and instead prints "Full Name, State;"
# pairs, semicolon-delimited: "Charles Stenholm, Texas; George Brown, Jr.,
# California; ...; and Chris John, Louisiana." (H.Res.13, 105th Congress).
# The comma here separates NAME from STATE, not one member from the next --
# splitting on comma the same way the "Mr. X of State" schema does breaks
# each entry into two bogus "members" (the name, then the bare state name).
# A name suffix (Jr./Sr./II/III) is ALSO comma-separated ("George Brown,
# Jr., California"), so a 3-way comma split is just as valid as a 2-way one:
# the LAST comma-segment is always the state, everything before it is the
# name (suffix included).
# A leading "*" flags a Delegate/Resident Commissioner in some renditions
# (H.Res.31, 104th Congress) -- not part of the name. A trailing parenthetical
# annotation is comma-separated in some documents ("Victor O. Frazer, Virgin
# Islands, (Delegate).", H.Res.46) and NOT in others ("*Eleanor Holmes Norton,
# D.C. (Delegate);", H.Res.31) -- the comma is optional either way. The
# parenthetical's own CONTENT varies too -- "(Delegate)", "(When Sworn)", "(to
# rank following Gary A. Condit, California)" (with an internal comma of its
# own -- another member's own "Name, State" pair), "(in lieu of ranking as
# provided for in H. Res. 8)" (103rd Congress) -- rather than enumerate every
# phrase, match ANY single trailing parenthetical: in this schema a state name
# is never itself parenthesized, so a trailing "(...)" is always an
# annotation, never part of the state. Without recognizing it, the naive
# "last comma-segment is the state" rule takes the parenthetical (or its
# LAST internal comma-segment) as the state instead.
_HONORIFIC_PRESENT_RE = re.compile(r"\b(?:Mr|Ms|Mrs|Miss)\.", re.IGNORECASE)
_NAME_STATE_QUALIFIER_RE = re.compile(r"\s*,?\s*\([^()]*\)\s*$")

# The classic "Mr. X of State" schema always introduces the state with " of "
# -- it never has a bare comma directly followed by a state name. Some
# documents (H.Res.187, 103rd Congress: "Mr. Smith, Michigan; and Mr.
# Everett, Alabama.") combine BOTH conventions: an honorific IS present (the
# schema detector's original sole signal for "NOT name-state"), but the state
# is still comma-separated. Checking for this structural shape directly --
# not just honorific absence -- catches that hybrid too.
_COMMA_STATE_RE = re.compile(
    r",\s*(?:" + "|".join(sorted((re.escape(s) for s in _STATES), key=len, reverse=True)) + r")\s*(?:[;.(]|$)",
    re.IGNORECASE,
)


def _is_name_state_schema(members_text: str) -> bool:
    if _COMMA_STATE_RE.search(members_text):
        return True
    return not _HONORIFIC_PRESENT_RE.search(members_text)


def _split_name_state_members(text: str) -> List[Tuple[str, Optional[str]]]:
    fragments = [
        re.sub(r"^(?:and|&)\s+", "", f.strip(), flags=re.IGNORECASE)
        for f in re.split(r";\s*", _clean(text))
        if f.strip()
    ]
    results = []
    for frag in fragments:
        frag = re.sub(r"^\*+\s*", "", frag).rstrip(".").strip()
        raw = None
        qm = _NAME_STATE_QUALIFIER_RE.search(frag)
        if qm:
            raw = _clean_member(frag)
            frag = frag[: qm.start()].rstrip()
        # A bare role qualifier ("John Joseph Moakley, Massachusetts, Ranking
        # Minority Member", H.Res.34) is ALSO just another comma-segment in
        # this schema -- strip it the same way the "Mr. X of State" schema
        # does, or the naive split takes the qualifier itself as the state.
        tm = _TRAILING_QUALIFIER_RE.search(frag)
        if tm:
            if raw is None:
                raw = _clean_member(frag)
            frag = _TRAILING_QUALIFIER_RE.sub("", frag).strip()
        parts = [p.strip() for p in frag.split(",")]
        if len(parts) < 2:
            continue
        state = parts[-1]
        name = ", ".join(parts[:-1])
        member = _clean_member(f"{name} of {state}")
        if member:
            results.append((member, raw))
    return results

# A single-member rank-adjustment resolution has no "Committee on X:" block
# header at all -- the whole thing is one sentence naming the committee and
# the member together, in either order: "Resolved, That on the Committee on
# Resources, Mr. Hayworth of Arizona shall rank after Mr. Tancredo of
# Colorado." (H.Res.176, 107th Congress) or "Resolved, That Mr. Lynch of
# Massachusetts shall rank after Mr. Shows of Mississippi on the Committee on
# Veterans' Affairs." (H.Res.282). Without recognizing this shape,
# _TEXT_COMMITTEE_BLOCK_RE's next-boundary lookahead has nothing to stop at
# but "Attest:", swallowing the entire sentence as a bogus committee name with
# "Clerk" misread as the member.
_RANK_ONLY_COMMITTEE_FIRST_RE = re.compile(
    r"Resolved,\s*That\s+on\s+the\s+Committee\s+on\s+(?P<committee>[^,]+),\s*"
    r"(?P<member>.+?)\s+"
    r"(?P<qualifier>(?:to|shall)\s+rank\s+(?:immediately\s+)?(?:after|ahead\s+of|following)\s+.+?)"
    # Non-greedy up to a period, but the "Mr./Mrs./Ms./Miss" in the qualifier's
    # own referenced name has periods too -- the SENTENCE-ending period is
    # specifically the one right before "Attest:" or the end of the text.
    r"\.(?=\s*(?:Attest|\Z))",
    re.IGNORECASE,
)
_RANK_ONLY_MEMBER_FIRST_RE = re.compile(
    r"Resolved,\s*That\s+(?P<member>(?:Mr|Mrs|Ms|Miss)\.\s+.+?)\s+"
    r"(?P<qualifier>(?:to|shall)\s+rank\s+(?:immediately\s+)?(?:after|ahead\s+of|following)\s+.+?)"
    r"\s+on\s+the\s+Committee\s+on\s+(?P<committee>[^.]+)"
    r"\.(?=\s*(?:Attest|\Z))",
    re.IGNORECASE,
)

# Joint Committee elections (Library, Printing) in the pre-XML plain-text
# rendition use a schema entirely different from both the standard
# "Committee on X:" block above and the XML-era Joint Committee schema (see
# _parse_joint_committee_changes): lettered subsections, e.g. "(a) Joint
# Committee on Printing.--The following Members are hereby elected to the
# Joint Committee on Printing, to serve with the chair of the Committee on
# House Administration: (1) Mr. Doolittle. (2) Mr. Linder. ... (b) Joint
# Committee of Congress on the Library.--...". Guarded by requiring "elected"
# in the resolution text (checked by the caller) so it never fires for an
# ordinary standing-committee resolution.
_TEXT_JOINT_COMMITTEE_BLOCK_RE = re.compile(
    r"\([a-z]\)\s*(?P<committee>Joint\s+Committee[^.]*?)\s*\.--\s*"
    r"The\s+following\s+Members?\s+are\s+hereby\s+elected\s+to\s+[^:]+:\s*"
    r"(?P<members>.+?)(?=\([a-z]\)\s*Joint\s+Committee|Attest\s*:|<all>|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# A second text-mode Joint Committee schema has no lettered subsections at
# all -- just a shared intro sentence ("Resolved, That the following named
# Members be, and they are hereby, elected to the following joint committees
# of Congress, to serve with the chairman of the Committee on House
# Administration:") followed directly by "Joint Committee X: members." blocks
# (H.Res.78/87, 106th Congress). Anchored on the literal "Joint Committee"
# (not just "Committee") so it never collides with the intro sentence's OWN
# "Committee on House Administration" mention -- _TEXT_COMMITTEE_BLOCK_RE
# would otherwise match THAT phrase first and swallow the entire joint
# committee list as its "members".
_TEXT_JOINT_COMMITTEE_INLINE_RE = re.compile(
    r"Joint\s+Committee\s+(?P<committee>(?:on|of)\s+.+?)\s*:\s*"
    r"(?P<members>.+?)(?=Joint\s+Committee\s+(?:on|of)\s+|Attest\s*:|<all>|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _split_numbered_members(text: str) -> List[Tuple[str, Optional[str]]]:
    """Split a "(1) Mr. X. (2) Mr. Y." numbered list (the text-mode Joint
    Committee schema's member format) into (clean_name, None) pairs -- one
    member per number, not comma-separated like a standing-committee roster."""
    items = [m.strip() for m in re.split(r"\(\d+\)\s*", text) if m.strip()]
    return [(_clean_member(item), None) for item in items if _clean_member(item)]


def parse_resolution_text(
    text: str, default_change: ChangeType, congress: Optional[str] = None
) -> Tuple[List[CommitteeChange], Optional[str]]:
    """Parse GovInfo's plain-text bill rendition -- the fallback for
    Congresses with no XML rendition available (109th and earlier).

    Unlike parse_resolution_xml, this can't classify addition/removal from an
    embedded title (there isn't one in this rendition) -- the caller supplies
    ``default_change`` from the congress.gov API's own bill title instead.

    Returns (committee_changes, date). ``date`` comes from the resolution's
    own "In the House of Representatives, U.S., <Month> <Day>, <Year>." line,
    used only to decide organizing-window party-rank eligibility here -- the
    caller still gets the authoritative agreed-to date from the congress.gov
    API separately, same as the XML path.
    """
    # The rendition is the raw <html><body><pre>...</pre></body></html>
    # response body -- strip the wrapper tags (real markup, not escaped) so
    # they can't leak into the last committee block when there's no "Attest:"
    # trailer to stop at, then decode entities ("&lt;all&gt;" -> "<all>") so
    # that marker is recognizable as literal text by _TEXT_COMMITTEE_BLOCK_RE.
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    # A hyphenated surname that wraps exactly at the hyphen ("Mario Diaz-\n
    # Balart") must rejoin with no space -- do this BEFORE _clean() collapses
    # the newline into a space, or "Diaz-Balart" becomes "Diaz- Balart".
    text = re.sub(r"-\s*\n\s*", "-", text)
    flat = _clean(text)

    date = None
    dm = _TEXT_DATE_RE.search(flat)
    if dm:
        month = _MONTHS.get(dm.group("month").title())
        if month:
            date = f"{dm.group('year')}-{month:02d}-{int(dm.group('day')):02d}"

    in_organizing_window = False
    if congress and date:
        try:
            lo, hi = organizing_window(int(congress))
            in_organizing_window = lo <= date <= hi
        except ValueError:
            pass

    # The title is printed TWICE in some renditions (once as a document
    # header, again right before "RESOLUTION") and can itself contain the
    # words "Committee"/"Joint Committee" (e.g. "Electing members of the
    # Joint Committee on Printing..."). Restrict block-matching to the
    # operative resolving clause onward, or that repeated title text gets
    # matched as if it were real committee-membership content.
    resolved_idx = flat.find("Resolved,")
    operative = flat[resolved_idx:] if resolved_idx != -1 else flat

    rank_only_match = _RANK_ONLY_COMMITTEE_FIRST_RE.search(operative) or (
        _RANK_ONLY_MEMBER_FIRST_RE.search(operative)
    )
    if rank_only_match:
        committee = _clean_committee_name(f"Committee on {rank_only_match.group('committee')}")
        member = _clean_member(rank_only_match.group("member"))
        raw = _clean_member(f"{member} {rank_only_match.group('qualifier')}")
        return [
            CommitteeChange(
                change_type=default_change,
                committee=committee,
                committee_code=None,
                member_name=member,
                member_name_raw=raw,
                party_rank=None,
            )
        ], date

    joint_matches = list(_TEXT_JOINT_COMMITTEE_BLOCK_RE.finditer(operative))
    numbered = True
    if not joint_matches:
        joint_matches = list(_TEXT_JOINT_COMMITTEE_INLINE_RE.finditer(operative))
        numbered = False
    if joint_matches:
        changes = []
        for m in joint_matches:
            committee = _clean_committee_name(
                m.group("committee") if numbered else f"Joint Committee {m.group('committee')}"
            )
            if not committee:
                continue
            pairs = (
                _split_numbered_members(m.group("members"))
                if numbered
                else _split_members_with_notes(m.group("members"))
            )
            assign_ranks, offset = _rank_offset(pairs, in_organizing_window)
            for i, (member, raw) in enumerate(pairs):
                changes.append(
                    CommitteeChange(
                        change_type=default_change,
                        committee=committee,
                        committee_code=None,
                        member_name=member,
                        member_name_raw=raw,
                        party_rank=(i + offset) if assign_ranks else None,
                    )
                )
        return changes, date

    changes = []
    for m in _TEXT_COMMITTEE_BLOCK_RE.finditer(operative):
        # The "Committee "/"on " literals are consumed by the regex, not
        # captured (so a missing "on" typo, e.g. "Committee Resources:",
        # doesn't leave it out of the group) -- reconstruct the full name and
        # let _clean_committee_name normalize casing either way.
        committee = _clean_committee_name(f"Committee on {m.group('committee')}")
        if not committee:
            continue
        members_text = _NAMED_ORDER_GROUP_QUALIFIER_RE.sub("", m.group("members"))
        pairs = (
            _split_name_state_members(members_text)
            if _is_name_state_schema(members_text)
            else _split_members_with_notes(members_text)
        )
        assign_ranks, offset = _rank_offset(pairs, in_organizing_window)
        for i, (member, raw) in enumerate(pairs):
            changes.append(
                CommitteeChange(
                    change_type=default_change,
                    committee=committee,
                    committee_code=None,
                    member_name=member,
                    member_name_raw=raw,
                    party_rank=(i + offset) if assign_ranks else None,
                )
            )
    return changes, date

# Signature block: a valediction, the signer's printed name, then USUALLY (but
# not always -- some letters just end "Sincerely, <Name>." with nothing more)
# a role line ("Member of Congress."/"Congressman."/"Congresswoman,
# <district>."). Valediction wording is an open-ended, creative space --
# "Sincerely,", "Respectfully,", "Semper Fidelis,", "With my deepest
# appreciation," and no doubt more that haven't shown up yet -- so rather than
# enumerate phrases, anchor on two markers that ARE a closed vocabulary: the
# role clause, and the trailer sentence ("... Without objection, the
# resignation is accepted.") that follows every signature block and reliably
# distinguishes the letter's end from its "laid before the House ..." opening
# sentence (which looks similar but never contains "Without objection"). The
# signer's name is always the line immediately above whichever of those is
# found closest to the end.
#
# The lookahead requires the role phrase to be immediately followed by "." or
# "," (i.e. it's the WHOLE line, maybe with a trailing district clause) -- not
# a space and more text. That distinguishes a true bare role line ("Member of
# Congress." / "Congresswoman," continuing to a district line) from a title
# used as a name-line PREFIX with no separate role line at all ("Congressman
# Vern Buchanan."), which would otherwise wrongly grab the line above it (the
# valediction) as the "name". This same lookahead is what keeps a leadership
# title (below) from colliding with the letter's own addressee line ("Hon.
# Nancy Pelosi,\nSpeaker of the House, ...") -- "Speaker" isn't in this
# alternation at all, but even a title that WAS would fail to match there
# since more words follow it on that line, not a bare "." or ",".
#
# Bare "Representative" is anchored the same as every other alternative here
# -- it must be the WHOLE line (immediately followed by "." or "," or line
# end, per the lookahead below), not just appear somewhere in the text. A
# body-prose mention ("the newly elected Representative from Florida's 20th
# Congressional District") is virtually never the entire content of one
# physical line in CREC's fixed-layout signature block, so the anchor makes
# it safe -- unlike a bare substring match, which would collide. House
# leadership titles (Whip/Leader) and committee-officer titles (Chairman/
# Ranking Member) are small, official, bounded sets, unlike valediction
# wording -- safe to enumerate, but a novel one not listed here would still
# fall through to the same failure mode.
#
# A role line can also give a district instead of a formal title ("First
# District, Arizona.") -- structurally regular ("<ordinal> District,
# <State>."), not open-ended prose, so it's recognized the same way.
_ROLE_LINE_RE = re.compile(
    r"^(?:Member\s+of\s+Congress"
    r"|(?:U\.?S\.?|United\s+States)\s+Congress(?:woman|man)"
    r"|Congress(?:woman|man)"
    r"|(?:U\.?S\.?|United\s+States)\s+Representative"
    r"|Representative"
    r"|(?:Majority|Minority|Republican|Democratic)\s+(?:Whip|Leader)"
    r"|(?:Vice\s+)?Chair(?:man|woman)?"
    r"|Ranking(?:\s+Minority)?\s+Member"
    r"|[A-Za-z][A-Za-z\-]*\s+District,\s+[A-Za-z ]+"
    r")(?=[.,]|\s*$)",
    re.IGNORECASE,
)
_LETTER_TRAILER_RE = re.compile(r"Without\s+objection|resignation\s+is\s+accepted", re.IGNORECASE)

# GovInfo's editorial correction marker (" =========== NOTE =========== ").
_NOTE_MARKER_RE = re.compile(r"={3,}\s*NOTE\s*={3,}", re.IGNORECASE)


def _extract_signer(text: str) -> Optional[str]:
    """Find the signer's printed name from a resignation letter's closing lines."""
    # A run of underscores is a decorative separator marking the end of the
    # granule/document (e.g. after "Ed Bryant." with no role line at all and
    # no "Without objection" trailer in that granule) -- not real content, but
    # it WOULD otherwise be mistaken for the line-before-trailer fallback's
    # "name" when nothing else follows it.
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not re.fullmatch(r"_+", ln.strip())
    ]
    if not lines:
        return None
    # GovInfo sometimes appends an editorial "NOTE" below the letter, correcting
    # a typo elsewhere on the same page. It's not part of the letter and often
    # repeats trailer-like phrases ("Without objection", "resignation is
    # accepted"), which would otherwise push the trailer anchor deep into the
    # note when the actual letter has no role-clause line to fall back on.
    note_hits = [i for i, ln in enumerate(lines) if _NOTE_MARKER_RE.search(ln)]
    if note_hits:
        lines = lines[: note_hits[0]]
    if not lines:
        return None
    # The trailer sentence is usually short enough to land on one physical
    # line, but CREC's column-width wrapping can still split it mid-phrase
    # (CREC-2004-03-25-pt1-PgH1566-3: "...the resignation is" / "accepted."
    # across a line break, compounded by a genuine source typo -- "objecton"
    # -- that also broke the OTHER alternative on its own line). Check each
    # line joined with the next too, so a phrase split across the wrap still
    # matches; the hit still anchors at the line where the phrase STARTS.
    trailer_hits = [
        i for i, ln in enumerate(lines)
        if _LETTER_TRAILER_RE.search(ln)
        or (i + 1 < len(lines) and _LETTER_TRAILER_RE.search(f"{ln} {lines[i + 1]}"))
    ]
    end = trailer_hits[-1] if trailer_hits else len(lines)
    role_hits = [i for i in range(end) if _ROLE_LINE_RE.match(lines[i])]
    name_idx = (role_hits[-1] if role_hits else end) - 1
    if name_idx < 0:
        return None
    name = _clean(lines[name_idx])
    # Strip exactly the ONE trailing separator (a comma before a role line
    # that follows, or a period when there's no role line at all) -- not a
    # full rstrip, so an abbreviation's own period ("Jr.") survives when only
    # the line's own structural punctuation needs removing.
    if name and name[-1] in ".,;":
        name = name[:-1]
    return name


@dataclass
class ResignationParse:
    committees: List[str] = field(default_factory=list)
    member_name: Optional[str] = None
    signed_date: Optional[str] = None


def _titlecase_committee(raw: str) -> str:
    """Normalize a TITLE-cased committee phrase to canonical title case."""
    text = _clean(raw).title()
    for small in ("On", "Of", "And", "The"):
        text = re.sub(rf"\b{small}\b", small.lower(), text)
    text = text[0].upper() + text[1:]
    return text


def _split_committees(title_tail: str) -> List[str]:
    """Split 'COMMITTEE ON A AND COMMITTEE ON B' into individual committee names.

    Also handles a 3+-item Oxford-comma list ("COMMITTEE ON A, COMMITTEE ON
    B, AND COMMITTEE ON C"), where only the last pair is joined by "AND" and
    the rest are comma-separated. Splits on a comma and/or " AND " only when
    the next name starts a committee -- optionally qualified ("SELECT
    COMMITTEE", "PERMANENT SELECT COMMITTEE") or "HOUSE ..." -- so neither an
    "AND" nor a comma inside a single committee's own name (e.g. "...AND THE
    CHINESE COMMUNIST PARTY", or "COMMITTEE ON SCIENCE, SPACE, AND
    TECHNOLOGY") splits it.
    """
    parts = re.split(
        r"(?:,\s*(?:AND\s+)?|\s+AND\s+)(?:THE\s+)?"
        r"(?=(?:(?:PERMANENT|SELECT|JOINT|SPECIAL)\s+)*COMMITTEE\b|HOUSE\b)",
        title_tail.strip(),
    )
    return [_titlecase_committee(p) for p in parts if p.strip()]


def parse_resignation_granule(title: str, text: str) -> ResignationParse:
    """Parse a CREC resignation granule (title + TXT) into structured fields."""
    result = ResignationParse()

    m = re.search(r"RESIGNATION AS MEMBER OF\s+(.*)", _clean(title), re.IGNORECASE)
    if m:
        result.committees = _split_committees(m.group(1))

    flat = _clean(text)

    d = re.search(r"Washington, DC,\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", flat)
    if d:
        month = _MONTHS.get(d.group(1))
        if month:
            result.signed_date = f"{d.group(3)}-{month:02d}-{int(d.group(2)):02d}"

    result.member_name = _extract_signer(text)

    return result
