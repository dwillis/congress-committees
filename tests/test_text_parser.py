"""Tests for parsing GPO's plain-text bill rendition (pre-XML-era Congresses,
109th and earlier, where GovInfo never digitized bill XML)."""

from pathlib import Path

from congress_committees.parser import parse_resolution_text

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return (FIX / name).read_text()


def test_single_committee_semicolon_list_with_named_chair():
    # H.Res.6 (109th Congress): "Committee on Rules: Mr. Dreier, Chairman;
    # Mr. Lincoln Diaz-Balart of Florida; ...; and Mr. Bishop of Utah." --
    # same mixed comma(qualifier)/semicolon(list) shape as the XML era.
    text = _load("BILLS-109hres6eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="109")
    assert date == "2005-01-04"
    assert [c.committee for c in changes] == ["Committee on Rules"] * 8
    assert [c.member_name for c in changes] == [
        "Mr. Dreier",
        "Mr. Lincoln Diaz-Balart of Florida",
        "Mr. Hastings of Washington",
        "Mr. Sessions",
        "Mr. Putnam",
        "Mrs. Capito",
        "Mr. Cole",
        "Mr. Bishop of Utah",
    ]
    # Explicitly named chair, in the organizing window -> rank 1.
    assert [c.party_rank for c in changes] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert changes[0].member_name_raw == "Mr. Dreier, Chairman"


def test_multiple_committees_with_mixed_shapes_and_on_typo():
    # H.Res.32 (109th Congress): many committees in one resolution --
    # single-chair-only entries ("Committee on Agriculture: Mr. Goodlatte,
    # Chairman."), a comma-separated multi-member roster (Appropriations), a
    # missing-"on" typo ("Committee Resources:" instead of "Committee on
    # Resources:"), and a bare single member with no chair qualifier at all
    # ("Committee on Rules: Mr. Gingrey.").
    text = _load("BILLS-109hres32eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="109")
    assert date == "2005-01-06"

    by_committee = {}
    for c in changes:
        by_committee.setdefault(c.committee, []).append((c.member_name, c.party_rank))

    assert by_committee["Committee on Agriculture"] == [("Mr. Goodlatte", 1)]
    assert by_committee["Committee on Resources"] == [("Mr. Pombo", 1)]
    assert by_committee["Committee on Rules"] == [("Mr. Gingrey", None)]

    appropriations = by_committee["Committee on Appropriations"]
    assert appropriations[0] == ("Mr. Jerry Lewis of California", 1)
    assert appropriations[1] == ("Mr. C.W. Bill Young of Florida", 2)
    assert len(appropriations) == 37
    assert appropriations[-1] == ("Mr. Alexander", 37)


def test_rank_after_qualifier_without_leading_comma():
    # H.Res.64 (109th Congress): "Mr. Crenshaw to rank after Mr. Ryun of
    # Kansas; Mr. Wicker to rank after Mr. Putnam and Ms. Ros-Lehtinen to rank
    # after Mr. Hensarling." -- no comma before "to rank after" at all
    # (unlike every XML-era example, which always has one), and "rank after"
    # instead of "rank immediately after".
    text = _load("BILLS-109hres64eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="109")
    assert date == "2005-02-02"
    assert [c.member_name for c in changes] == [
        "Mr. Crenshaw", "Mr. Wicker", "Ms. Ros-Lehtinen",
    ]
    assert [c.member_name_raw for c in changes] == [
        "Mr. Crenshaw to rank after Mr. Ryun of Kansas",
        "Mr. Wicker to rank after Mr. Putnam",
        "Ms. Ros-Lehtinen to rank after Mr. Hensarling",
    ]
    assert all(c.committee == "Committee on the Budget" for c in changes)
    # Outside the organizing window (Feb, not Jan) -- no ranks regardless.
    assert all(c.party_rank is None for c in changes)


def test_numbered_dash_separator_variant():
    # H.Res.161 (109th Congress): "(1) Committee on rules.--Ms. Matsui." --
    # a numbered-enum prefix and ".--" instead of ":" as the separator.
    text = _load("BILLS-109hres161eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="109")
    assert date == "2005-03-16"
    assert len(changes) == 1
    assert changes[0].committee == "Committee on Rules"
    assert changes[0].member_name == "Ms. Matsui"


def test_numbered_list_with_lowercase_committee_descriptors_splits_correctly():
    # H.Res.62 (109th Congress): a 7-item numbered list -- "(2) Committee on
    # the budget.--Mr. Kind.", "(3) Committee on government reform.--Ms.
    # Norton.", etc. -- where EVERY descriptive committee name after
    # "Committee on" is all-lowercase. The block-boundary lookahead required
    # an uppercase letter there, so none of these registered as a new block:
    # all 7 committees' entries collapsed into one giant "Committee on
    # Agriculture" blob (32 members glued together instead of split across 7
    # committees).
    text = _load("BILLS-109hres62eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="109")
    assert date == "2005-02-02"

    by_committee = {}
    for c in changes:
        by_committee.setdefault(c.committee, []).append(c.member_name)

    assert by_committee["Committee on Agriculture"] == [
        "Mr. Pomeroy", "Mr. Boswell", "Mr. Larsen of Washington",
        "Mr. Davis of Tennessee", "Mr. Chandler",
    ]
    assert by_committee["Committee on the Budget"] == ["Mr. Kind"]
    assert by_committee["Committee on Government Reform"] == ["Ms. Norton"]
    assert by_committee["Committee on Resources"] == [
        "Mr. George Miller of California", "Mr. Markey", "Mr. DeFazio",
        "Mr. Inslee", "Mr. Udall of Colorado", "Mr. Cardoza", "Ms. Herseth",
    ]
    assert by_committee["Committee on Science"][0] == "Ms. Hooley of Oregon"
    assert len(by_committee["Committee on Small Business"]) == 10
    assert len(by_committee["Committee on Veterans' Affairs"]) == 5
    assert sum(len(v) for v in by_committee.values()) == 38


def test_new_resolved_clause_ends_prior_committee_block():
    # H.Res.664 (109th Congress): TWO separate "Resolved, That ..." clauses
    # in one bill, each targeting the SAME committee ("Committee on House
    # Administration" appears twice). With only a "next Committee heading" as
    # a boundary signal, the first block's member text swallowed the entire
    # second "Resolved, That the following named Member be, ... ranked as
    # follows ..." sentence as if it were part of the member list.
    text = _load("BILLS-109hres664eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="109")
    assert date == "2006-02-01"
    assert [(c.member_name, c.member_name_raw) for c in changes] == [
        ("Mr. Ehlers", "Mr. Ehlers, Chairman"),
        ("Mr. Ney", "Mr. Ney, after Mr. Ehlers"),
    ]
    assert all(c.committee == "Committee on House Administration" for c in changes)


def test_missing_space_after_honorific():
    # H.Res.48 (109th Congress): "Mr.McKeon" -- a genuine typo in the source
    # document (no space after the period).
    text = _load("BILLS-109hres48eh.htm")
    changes, _ = parse_resolution_text(text, "addition", congress="109")
    workforce = [c.member_name for c in changes if c.committee == "Committee on Education and the Workforce"]
    assert "Mr.McKeon" in workforce


def test_hyphenated_surname_split_across_a_line_wrap():
    # H.Res.48 (109th Congress): "Mr. Mario Diaz-\nBalart of Florida" wraps
    # exactly at the hyphen in the source; naive whitespace-collapsing turns
    # the line break into a space, producing "Diaz- Balart" instead of
    # "Diaz-Balart".
    text = _load("BILLS-109hres48eh.htm")
    changes, _ = parse_resolution_text(text, "addition", congress="109")
    names = [c.member_name for c in changes if c.committee == "Committee on Transportation and Infrastructure"]
    assert "Mr. Mario Diaz-Balart of Florida" in names
    assert not any("Diaz- " in n for n in names)


def test_ath_stage_date_format_without_us_comma():
    # BILLS-108hres79ath.htm: the "Agreed to House" (ath) stage's preamble is
    # entirely different from the "eh"-era one -- "IN THE HOUSE OF
    # REPRESENTATIVES\n\nFebruary 13, 2003" instead of "In the House of
    # Representatives, U.S.,\n\nJanuary 4, 2005.": all-caps, no "U.S.,", no
    # comma before the date, no trailing period after the year.
    text = _load("BILLS-108hres79ath.htm")
    changes, date = parse_resolution_text(text, "addition", congress="108")
    assert date == "2003-02-13"


def test_ath_stage_html_wrapper_and_all_marker_excluded_from_last_block():
    # BILLS-108hres79ath.htm has no "Attest:" trailer at all -- it ends with
    # an HTML-escaped "<all>" end-of-bill-text marker ("&lt;all&gt;"), still
    # wrapped in the raw <html><body><pre>...</pre></body></html>. Without
    # stripping the wrapper and recognizing "<all>" as a stop boundary, the
    # last committee's member list swallows the marker and the closing tags.
    text = _load("BILLS-108hres79ath.htm")
    changes, _ = parse_resolution_text(text, "addition", congress="108")
    veterans = [c.member_name for c in changes if c.committee == "Committee on Veterans' Affairs"]
    assert veterans == [
        "Ms. Hooley of Oregon", "Mr. Reyes", "Mr. Strickland", "Ms. Berkley",
        "Mr. Udall of New Mexico", "Mrs. Davis of California", "Mr. Ryan of Ohio",
    ]
    assert not any("<" in n or ">" in n or "pre" in n.lower() for n in veterans)


def test_rank_only_resolution_with_committee_named_before_member():
    # H.Res.176 (107th Congress): a single-member rank-adjustment resolution
    # has no "Committee on X:" block header at all -- the whole thing is one
    # sentence: "Resolved, That on the Committee on Resources, Mr. Hayworth of
    # Arizona shall rank after Mr. Tancredo of Colorado." Without recognizing
    # this shape, the block regex's only boundary to stop at is "Attest:",
    # swallowing the entire sentence as a bogus committee name with "Clerk"
    # misread as the member.
    text = _load("BILLS-107hres176eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="107")
    assert date == "2001-06-21"
    assert len(changes) == 1
    assert changes[0].committee == "Committee on Resources"
    assert changes[0].member_name == "Mr. Hayworth of Arizona"
    assert changes[0].member_name_raw == "Mr. Hayworth of Arizona shall rank after Mr. Tancredo of Colorado"


def test_rank_only_resolution_with_committee_named_after_member():
    # H.Res.282 (107th Congress): the same single-sentence rank-adjustment
    # shape, but with the committee name AFTER the qualifier instead of
    # before: "Resolved, That Mr. Lynch of Massachusetts shall rank after Mr.
    # Shows of Mississippi on the Committee on Veterans' Affairs."
    text = _load("BILLS-107hres282eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="107")
    assert date == "2001-11-08"
    assert len(changes) == 1
    assert changes[0].committee == "Committee on Veterans' Affairs"
    assert changes[0].member_name == "Mr. Lynch of Massachusetts"
    assert changes[0].member_name_raw == "Mr. Lynch of Massachusetts shall rank after Mr. Shows of Mississippi"


def test_shall_rank_qualifier_inside_a_committee_block():
    # H.Res.85 (107th Congress): "Committee on Transportation and
    # Infrastructure: Mr. Pombo shall rank immediately after Mr. Moran of
    # Kansas." -- "shall rank" instead of "to rank", which the qualifier
    # regexes didn't recognize, truncating the member to "Mr. Pombo shall
    # rank immediately" instead of stripping the whole qualifier clause.
    text = _load("BILLS-107hres85eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="107")
    assert date == "2001-03-08"
    assert len(changes) == 1
    assert changes[0].committee == "Committee on Transportation and Infrastructure"
    assert changes[0].member_name == "Mr. Pombo"
    assert changes[0].member_name_raw == "Mr. Pombo shall rank immediately after Mr. Moran of Kansas"


def test_text_mode_joint_committee_election_with_lettered_subsections():
    # H.Res.148 (107th Congress): Joint Committee elections in the pre-XML
    # plain-text rendition use an entirely different schema from both the
    # standard "Committee on X:" block and the XML-era Joint Committee
    # schema -- lettered subsections "(a) Joint Committee on Printing.--The
    # following Members are hereby elected to ... : (1) Mr. Doolittle. (2)
    # Mr. Linder. ..." Without recognizing this shape, the block regex
    # anchors on the FIRST "Committee" substring anywhere in the document
    # (including the title/header text before "Resolved,"), producing
    # garbage committee names and member blobs.
    text = _load("BILLS-107hres148ih.htm")
    changes, date = parse_resolution_text(text, "addition", congress="107")
    # The "ih" (Introduced in House) rendition's own date line is the
    # introduction date -- the caller uses the congress.gov API's agreed-to
    # date (2001-06-05) as the authoritative one, same as every other bill.
    assert date == "2001-05-24"

    by_committee = {}
    for c in changes:
        by_committee.setdefault(c.committee, []).append(c.member_name)

    assert by_committee["Joint Committee on Printing"] == [
        "Mr. Doolittle", "Mr. Linder", "Mr. Hoyer", "Mr. Fattah",
    ]
    assert by_committee["Joint Committee of Congress on the Library"] == [
        "Mr. Ehlers", "Mr. Hoyer", "Mr. Davis of Florida",
    ]


def test_rank_only_resolution_with_following_instead_of_after():
    # H.Res.73 (106th Congress): "Resolved, That Mr. Portman shall rank
    # immediately following Mr. Camp on the Committee on Standards of
    # Official Conduct." -- "following" instead of "after"/"ahead of", the
    # only qualifier prepositions previously recognized.
    text = _load("BILLS-106hres73eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="106")
    assert date == "1999-02-23"
    assert len(changes) == 1
    assert changes[0].committee == "Committee on Standards of Official Conduct"
    assert changes[0].member_name == "Mr. Portman"
    assert changes[0].member_name_raw == "Mr. Portman shall rank immediately following Mr. Camp"


def test_text_mode_joint_committee_election_without_lettered_subsections():
    # H.Res.78 (106th Congress): a SECOND text-mode Joint Committee schema --
    # no lettered "(a)/(b)" subsections at all, just a shared intro sentence
    # ("Resolved, That the following named Members be, and they are hereby,
    # elected to the following joint committees of Congress, to serve with
    # the chairman of the Committee on House Administration:") followed
    # directly by "Joint Committee X: members." blocks. The intro sentence's
    # OWN "Committee on House Administration" mention was matched by the
    # generic block regex first, swallowing the entire joint-committee list
    # as a bogus "Committee on House Administration" addition.
    text = _load("BILLS-106hres78ih.htm")
    changes, date = parse_resolution_text(text, "addition", congress="106")
    assert date == "1999-02-23"

    by_committee = {}
    for c in changes:
        by_committee.setdefault(c.committee, []).append(c.member_name)

    assert by_committee["Joint Committee of Congress on the Library"] == [
        "Mr. Boehner", "Mr. Ehlers", "Mr. Davis of Florida", "Mr. Hoyer",
    ]
    assert by_committee["Joint Committee on Printing"] == [
        "Mr. Boehner", "Mr. Ney", "Mr. Fattah", "Mr. Hoyer",
    ]
    assert "Committee on House Administration" not in by_committee


def test_group_qualifier_with_both_does_not_become_a_bogus_member():
    # H.Res.21 (106th Congress): "Committee on the Budget: Mr. Collins of
    # Georgia and Mr. Wamp of Tennessee, both to rank in the named order
    # following Mr. Ryun of Kansas." -- the trailing "both to rank in the
    # named order following X" clause applies to BOTH preceding members at
    # once, not to a single one, so it can't be reattached by the normal
    # bare-qualifier-reattachment logic and was misread as its own bogus
    # third "member" ("both to rank in the named order").
    text = _load("BILLS-106hres21eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="106")
    assert date == "1999-01-19"
    assert [c.member_name for c in changes] == [
        "Mr. Collins of Georgia", "Mr. Wamp of Tennessee",
    ]
    assert all(c.committee == "Committee on the Budget" for c in changes)


def test_group_qualifier_with_all_does_not_become_a_bogus_member():
    # H.Res.30 (106th Congress): same "named order" group-qualifier shape,
    # but with "all" instead of "both" for a three-member list: "Mr. Hansen,
    # Mr. McKeon, and Mr. Gibbons; all to rank in the named order following
    # Mr. LaHood."
    text = _load("BILLS-106hres30eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="106")
    assert date == "1999-02-02"
    veterans = [c.member_name for c in changes if c.committee == "Committee on Veterans' Affairs"]
    assert veterans == ["Mr. Hansen", "Mr. McKeon", "Mr. Gibbons"]


def test_name_state_schema_with_no_honorific_at_all():
    # H.Res.13 (105th Congress): an older member-list schema entirely without
    # "Mr./Ms./Mrs./Miss" -- semicolon-delimited "Full Name, State" pairs
    # instead, e.g. "Charles Stenholm, Texas; George Brown, Jr., California;
    # ...; and Chris John, Louisiana." Splitting on comma the same way the
    # "Mr. X of State" schema does breaks each entry into two bogus
    # "members" (the name, then the bare state name alone) -- 257 of them
    # across this one resolution. A suffix (Jr.) is ALSO comma-separated
    # from the state ("George Brown, Jr., California"), so the LAST
    # comma-segment must always be treated as the state, not just the second.
    text = _load("BILLS-105hres13eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="105")
    assert date == "1997-01-07"

    agriculture = [c.member_name for c in changes if c.committee == "Committee on Agriculture"]
    assert agriculture[0] == "Charles Stenholm of Texas"
    assert agriculture[1] == "George Brown, Jr. of California"
    assert agriculture[-1] == "Chris John of Louisiana"
    assert len(agriculture) == 21

    # "(When Sworn)" is a qualifier, not part of the state name.
    national_security = {
        c.member_name: c.member_name_raw
        for c in changes
        if c.committee == "Committee on National Security"
    }
    assert "Frank Tejeda of Texas" in national_security
    assert national_security["Frank Tejeda of Texas"] == "Frank Tejeda, Texas (When Sworn)"


def test_in_lieu_of_sentence_between_blocks_is_not_swallowed_as_members():
    # H.Res.42 (105th Congress): between two committee blocks sits a plain
    # sentence -- "In lieu of the Members elected in H. Res. 36 to the
    # following committees, the following Members:" -- with no literal
    # "Committee" in it at all (just lowercase "committees"), so it wasn't a
    # recognized block boundary and got swallowed as trailing "members" text
    # of the PRECEDING committee ("Committee on Science: Mr. Brown of
    # California."), producing two bogus extra "members".
    text = _load("BILLS-105hres42eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="105")
    assert date == "1997-02-06"

    science = [c.member_name for c in changes if c.committee == "Committee on Science"]
    assert science == ["Mr. Brown of California"]

    small_business = [
        c.member_name for c in changes if c.committee == "Committee on Small Business"
    ]
    assert small_business[0] == "Mr. LaFalce"
    assert small_business[-1] == "Mr. Goode"
    assert len(small_business) == 16


def test_bare_period_committee_separator_instead_of_colon():
    # H.Res.12 (105th Congress): every committee header uses ":" except ONE
    # -- "Committee on Education and the Workforce. Mr. Goodling, Chairman;
    # ..." uses a bare "." instead. Since the block regex only recognized
    # ".--" or ":" as a valid separator, the committee-name capture kept
    # extending PAST this one, swallowing the entire block (including the
    # NEXT committee's real header and members) as a single bogus committee
    # name, with the actual next committee's roster misattributed to it.
    text = _load("BILLS-105hres12eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="105")
    assert date == "1997-01-07"

    by_committee = {}
    for c in changes:
        by_committee.setdefault(c.committee, []).append(c.member_name)

    workforce = by_committee["Committee on Education and the Workforce"]
    assert workforce[0] == "Mr. Goodling"
    assert workforce[-1] == "Mr. Bob Schaffer of Colorado"
    assert len(workforce) == 21

    reform = by_committee["Committee on Government Reform and Oversight"]
    assert reform[0] == "Mr. Burton of Indiana"
    assert len(reform) == 24
    assert not any("Committee" in name for name in workforce + reform)


def test_generational_suffix_comma_in_mr_x_of_state_schema():
    # H.Res.337 (104th Congress): "Committee on Banking and Financial
    # Services: Mr. Jesse Jackson, Jr. of Illinois." -- a single member, but
    # the comma before "Jr." makes the naive comma-split treat "Jr. of
    # Illinois" as a second, bogus "member" instead of part of the same name.
    text = _load("BILLS-104hres337eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="104")
    assert date == "1996-01-05"
    assert len(changes) == 1
    assert changes[0].committee == "Committee on Banking and Financial Services"
    assert changes[0].member_name == "Mr. Jesse Jackson, Jr. of Illinois"


def test_single_member_who_will_rank_qualifier_amid_a_longer_list():
    # H.Res.166 (104th Congress): "Committee on Small Business: Mr. Skelton
    # of Missouri, who will rank after Mr. LaFalce of New York, and Mr.
    # Baldacci of Maine." -- "who will rank after X" (not "to/shall rank")
    # qualifies ONLY Skelton; Baldacci is a separate, second member in the
    # same list.
    text = _load("BILLS-104hres166eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="104")
    assert date == "1995-06-13"

    small_business = [
        (c.member_name, c.member_name_raw)
        for c in changes
        if c.committee == "Committee on Small Business"
    ]
    assert small_business == [
        ("Mr. Skelton of Missouri", "Mr. Skelton of Missouri, who will rank after Mr. LaFalce of New York"),
        ("Mr. Baldacci of Maine", None),
    ]


def test_group_qualifier_with_of_whom_will_rank_in_order_wording():
    # H.Res.166 (104th Congress): "Committee on Resources: Mr. Pickett of
    # Virginia and Mr. Pallone of New Jersey, both of whom will rank in
    # order after Mr. Ortiz of Texas." -- a differently-worded variant of
    # the same shared GROUP qualifier shape already handled for "both to
    # rank in the named order following X" (106th Congress): "of whom"
    # instead of nothing, "will rank" instead of "to rank", "in order"
    # instead of "in the named order".
    text = _load("BILLS-104hres166eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="104")
    resources = [c.member_name for c in changes if c.committee == "Committee on Resources"]
    assert resources == ["Mr. Pickett of Virginia", "Mr. Pallone of New Jersey"]


def test_name_state_schema_delegate_annotation_after_state():
    # H.Res.46 (104th Congress): "Committee on International Relations:
    # Victor O. Frazer, Virgin Islands, (Delegate)." -- a THIRD comma
    # segment, "(Delegate)", trailing the state, not part of it -- naive
    # "last comma-segment is always the state" logic wrongly took
    # "(Delegate)" as the state and left "Victor O. Frazer, Virgin Islands"
    # glued together as the "name".
    text = _load("BILLS-104hres46eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="104")
    assert date == "1995-01-27"
    assert len(changes) == 1
    assert changes[0].member_name == "Victor O. Frazer of Virgin Islands"


def test_name_state_schema_leading_asterisk_and_delegate_no_comma():
    # H.Res.31 (104th Congress): "*Eleanor Holmes Norton, D.C. (Delegate);
    # ... *Eni F.H. Faleomavaega, American Samoa (Delegate); ... *Robert A.
    # Underwood, Guam (Delegate);" -- a leading "*" marks a delegate, and
    # here "(Delegate)" trails the state with NO comma before it at all
    # (unlike H.Res.46's "Virgin Islands, (Delegate)"). Also exercises
    # "D.C." as a state abbreviation, which isn't in the state name dict
    # (only "district of columbia" is).
    text = _load("BILLS-104hres31eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="104")
    assert date == "1995-01-09"

    reform = [c.member_name for c in changes if c.committee == "Committee on Government Reform and Oversight"]
    # The trailing period is stripped by the same general member-cleanup
    # rule applied everywhere else (member names never keep a trailing
    # sentence-style period) -- "D.C" without it still normalizes correctly.
    assert "Eleanor Holmes Norton of D.C" in reform

    resources = [c.member_name for c in changes if c.committee == "Committee on Resources"]
    assert "Eni F.H. Faleomavaega of American Samoa" in resources
    assert "Robert A. Underwood of Guam" in resources


def test_name_state_schema_bare_group_role_qualifier():
    # H.Res.34 (104th Congress): "Committee on Rules: John Joseph Moakley,
    # Massachusetts, Ranking Minority Member; Anthony C. Beilenson,
    # California; ..." -- in the "Name, State" schema, a role qualifier
    # ("Ranking Minority Member") is ALSO just another comma-segment, so the
    # naive "last comma-segment is the state" logic took the qualifier
    # itself as the state ("of Ranking Minority Member") and glued the real
    # state into the name.
    text = _load("BILLS-104hres34eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="104")
    assert date == "1995-01-11"
    rules = [(c.member_name, c.member_name_raw) for c in changes]
    assert rules[0] == (
        "John Joseph Moakley of Massachusetts",
        "John Joseph Moakley, Massachusetts, Ranking Minority Member",
    )
    assert rules[1] == ("Anthony C. Beilenson of California", None)


def test_name_state_schema_parenthetical_qualifier_with_internal_comma():
    # H.Res.34 (103rd Congress): "Committee on Government Operations: Collin
    # Peterson, Minnesota (to rank following Gary A. Condit, California);
    # ..." and "Committee on Merchant Marine and Fisheries: Tom Andrews,
    # Maine (to rank following H. Maring Lancaster, North Carolina); ..." --
    # the parenthetical qualifier ITSELF contains a comma (another member's
    # own "Name, State" pair), so the previous keyword-specific parenthetical
    # regex (only "(When Sworn)"/"(Delegate)") didn't recognize it, and the
    # naive "last comma-segment is the state" logic took the parenthetical's
    # inner state as the real one, gluing everything else into the "name".
    text = _load("BILLS-103hres34eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="103")
    assert date == "1993-01-21"

    gov_ops = {c.member_name: c.member_name_raw for c in changes if c.committee == "Committee on Government Operations"}
    assert gov_ops["Collin Peterson of Minnesota"] == (
        "Collin Peterson, Minnesota (to rank following Gary A. Condit, California)"
    )

    merchant = {
        c.member_name: c.member_name_raw
        for c in changes
        if c.committee == "Committee on Merchant Marine and Fisheries"
    }
    assert merchant["Tom Andrews of Maine"] == (
        "Tom Andrews, Maine (to rank following H. Maring Lancaster, North Carolina)"
    )


def test_name_state_schema_in_lieu_of_ranking_parenthetical():
    # H.Res.34 (103rd Congress): "Committee on Science, Space and
    # Technology: ...; and Xavier Becerra, California (in lieu of ranking as
    # provided for in H. Res. 8)." and "Committee on Small Business: ...;
    # Tom Andrews, Maine (in lieu of ranking as provided for in H. Res. 8);
    # ..." -- a differently-worded parenthetical qualifier, same shape.
    text = _load("BILLS-103hres34eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="103")

    science = [c.member_name for c in changes if c.committee == "Committee on Science, Space and Technology"]
    assert "Xavier Becerra of California" in science

    small_business = [c.member_name for c in changes if c.committee == "Committee on Small Business"]
    assert "Tom Andrews of Maine" in small_business


def test_name_state_schema_vacancy_placeholders_are_skipped():
    # H.Res.34 (103rd Congress) fills out short committee rosters with
    # "[vacancy]" placeholders -- these have no comma-separated state at all
    # and must not become bogus "members".
    text = _load("BILLS-103hres34eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="103")
    armed_services = [c.member_name for c in changes if c.committee == "Committee on Armed Services"]
    assert armed_services == ["Tim Holden of Pennsylvania"]
    assert not any("vacancy" in c.member_name.lower() for c in changes)


def test_name_state_schema_with_honorific_and_no_first_name():
    # H.Res.187 (103rd Congress): "Committee on Agriculture: Mr. Smith,
    # Michigan; and Mr. Everett, Alabama." -- a hybrid of both schemas: an
    # "Mr./Mrs." honorific IS present (which the schema detector had been
    # using as its sole signal for "NOT the name-state schema"), but the
    # state is still comma-separated rather than introduced with "of". The
    # naive detector routed this through the wrong splitter, breaking "Mr.
    # Smith, Michigan" into two bogus members ("Mr. Smith" and "Michigan").
    text = _load("BILLS-103hres187eh.htm")
    changes, date = parse_resolution_text(text, "addition", congress="103")
    assert date == "1993-05-27"

    agriculture = [c.member_name for c in changes if c.committee == "Committee on Agriculture"]
    assert agriculture == ["Mr. Smith of Michigan", "Mr. Everett of Alabama"]

    merchant = [
        c.member_name for c in changes if c.committee == "Committee on Merchant Marine and Fisheries"
    ]
    assert merchant == [
        "Mrs. Bentley of Maryland", "Mr. Taylor of North Carolina", "Mr. Torkildsen of Massachusetts",
    ]
