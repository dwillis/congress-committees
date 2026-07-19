"""Tests for parsing GPO bill XML into committee-change records."""

from pathlib import Path

import pytest

from congress_committees.parser import classify_title, parse_resolution_xml

FIXTURE = Path(__file__).parent / "fixtures" / "BILLS-119hres1381eh.xml"


def test_classify_title_recognizes_designating_membership_wording():
    # H.Res.33/34 (108th Congress): "Designating majority membership on
    # certain standing committees of the House." -- no "electing" at all, a
    # completely different title convention from every other Congress seen
    # so far. Without recognizing it, these bills are invisible to discovery
    # itself (filter_committee_change_bills uses classify_title too), not
    # just misclassified once found.
    assert classify_title(
        "Designating majority membership on certain standing committees of the House."
    ) == (True, "addition")
    assert classify_title(
        "Designating minority membership on certain standing committees of the House."
    ) == (True, "addition")


@pytest.fixture
def hres1381():
    return parse_resolution_xml(FIXTURE.read_bytes())


def test_extracts_resolution_identity(hres1381):
    assert hres1381.congress == "119"
    assert hres1381.type == "HRES"
    assert hres1381.number == "1381"


def test_extracts_title_and_stage(hres1381):
    assert hres1381.title == (
        "Electing a Member to certain standing committees "
        "of the House of Representatives."
    )
    assert hres1381.stage == "Engrossed-in-House"


def test_extracts_action_date(hres1381):
    assert hres1381.date == "2026-06-24"


def test_extracts_three_committee_changes(hres1381):
    assert len(hres1381.committee_changes) == 3


def test_committee_changes_carry_codes_and_members(hres1381):
    by_code = {c.committee_code: c for c in hres1381.committee_changes}
    assert set(by_code) == {"HFA00", "HJU00", "HGO00"}

    foreign = by_code["HFA00"]
    assert foreign.committee == "Committee on Foreign Affairs"
    assert foreign.member_name == "Mr. Gallagher"
    assert foreign.change_type == "addition"


def test_all_changes_are_additions_for_election_resolution(hres1381):
    assert {c.change_type for c in hres1381.committee_changes} == {"addition"}


def test_single_member_paragraph_yields_one_change_each(hres1381):
    # Each Gallagher paragraph names one member -> one change apiece (unchanged).
    assert [c.member_name for c in hres1381.committee_changes] == [
        "Mr. Gallagher",
        "Mr. Gallagher",
        "Mr. Gallagher",
    ]


# --- joint committee resolutions (a different XML schema entirely) --------

JOINT_FIXTURE = Path(__file__).parent / "fixtures" / "BILLS-114hres171eh.xml"


@pytest.fixture
def hres171():
    return parse_resolution_xml(JOINT_FIXTURE.read_bytes())


def test_joint_committee_resolution_extracts_all_members(hres171):
    # H.Res.171 (114th Congress) elects members to the Joint Committee of
    # Congress on the Library and the Joint Committee on Printing. Joint
    # Committee resolutions don't use <committee-appointment-paragraph> at
    # all -- each committee gets its own <subsection> with a plain-text
    # <header> (the name) and one <paragraph> per elected member.
    assert len(hres171.committee_changes) == 7
    assert all(c.change_type == "addition" for c in hres171.committee_changes)
    assert all(c.committee_code is None for c in hres171.committee_changes)


def test_joint_committee_resolution_groups_members_by_committee(hres171):
    by_committee = {}
    for c in hres171.committee_changes:
        by_committee.setdefault(c.committee, []).append(c.member_name)
    assert by_committee == {
        "Joint Committee of Congress on the Library": [
            "Mr. Harper", "Mr. Brady of Pennsylvania", "Ms. Zoe Lofgren of California",
        ],
        "Joint Committee on Printing": [
            "Mr. Harper", "Mr. Rodney Davis of Illinois",
            "Mr. Brady of Pennsylvania", "Mr. Vargas",
        ],
    }


def test_non_committee_subsections_are_not_mistaken_for_committee_lists():
    # A subsection with a header and paragraphs that ISN'T introduced by
    # "elected" text must not be treated as a committee roster.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>114 HRES 999 EH: Providing for consideration</title>"
        "<official-title>Providing for consideration of a bill.</official-title>"
        "<resolution-body>"
        "<section><subsection>"
        "<header>General Debate</header>"
        "<text>General debate shall proceed as follows:</text>"
        "<paragraph><text>Mr. Smith.</text></paragraph>"
        "</subsection></section>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert record.committee_changes == []


# --- enumerated-paragraph resolutions (a third schema variant) ------------

HRES8_FIXTURE = Path(__file__).parent / "fixtures" / "BILLS-111hres8eh.xml"


@pytest.fixture
def hres8():
    return parse_resolution_xml(HRES8_FIXTURE.read_bytes())


def test_enumerated_paragraph_resolution_extracts_all_committees(hres8):
    # H.Res.8 (111th Congress) elects the chairs of 19 standing committees
    # (plus the full Rules committee roster) using yet another schema:
    # enumerated <paragraph> elements directly in a <section>, each with
    # <enum>, <header>Committee name</header>, and <text>members</text> --
    # no <committee-appointment-paragraph> and no <subsection> anywhere.
    assert len({c.committee for c in hres8.committee_changes}) == 19
    assert len(hres8.committee_changes) == 27  # 18 chairs + 9 Rules members
    first = hres8.committee_changes[0]
    assert first.committee == "Committee on Agriculture"
    assert first.member_name == "Mr. Peterson of Minnesota"
    assert first.member_name_raw == "Mr. Peterson of Minnesota, Chairman"
    # Explicitly named chair in the organizing window -> rank 1.
    assert first.party_rank == 1
    # The Rules paragraph elects its chairman AND eight members in one list.
    rules = [c for c in hres8.committee_changes if c.committee == "Committee on Rules"]
    assert [(c.member_name, c.party_rank) for c in rules[:3]] == [
        ("Ms. Slaughter", 1),
        ("Mr. McGovern", 2),
        ("Mr. Hastings of Florida", 3),
    ]


def test_enumerated_paragraph_multi_member_list_splits():
    # H.Res.24-style: the same enumerated-paragraph schema carrying a full
    # comma-separated roster per committee.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<form>"
        '<congress display="no">111th CONGRESS</congress>'
        "<legis-num>H. RES. 24</legis-num>"
        '<action><action-date date="20090106">January 6, 2009</action-date></action>'
        '<official-title display="no">Electing Members to certain standing committees '
        "of the House of Representatives.</official-title>"
        "</form>"
        "<resolution-body>"
        "<section><text>That the following named Members be and are hereby elected "
        "to the following standing committees of the House of Representatives:</text>"
        "<paragraph><enum>(1)</enum><header>Committee on Appropriations</header>"
        "<text>Mr. Murtha, Mr. Dicks, Mr. Mollohan.</text></paragraph>"
        "</section>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [(c.member_name, c.party_rank) for c in record.committee_changes] == [
        ("Mr. Murtha", 2),
        ("Mr. Dicks", 3),
        ("Mr. Mollohan", 4),
    ]
    assert all(c.committee == "Committee on Appropriations" for c in record.committee_changes)


def test_enumerated_paragraphs_ignored_without_elect_intro():
    # Enumerated paragraphs with headers appear in ordinary rules resolutions
    # too -- without an "elected ..." intro sentence they must not be
    # mistaken for committee rosters.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<official-title>Providing for consideration of a bill.</official-title>"
        "<resolution-body>"
        "<section><text>The following procedures shall apply:</text>"
        "<paragraph><enum>(1)</enum><header>General Debate</header>"
        "<text>Mr. Smith may speak.</text></paragraph>"
        "</section>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert record.committee_changes == []


# --- pre-dc:title-era resolutions (no <metadata>/<title> block at all) ----

HRES80_FIXTURE = Path(__file__).parent / "fixtures" / "BILLS-111hres80eh.xml"


@pytest.fixture
def hres80():
    return parse_resolution_xml(HRES80_FIXTURE.read_bytes())


def test_congress_and_number_fall_back_to_form_tags_when_no_dc_title(hres80):
    # H.Res.80 (111th Congress) has no <metadata>/<dc:title> block at all --
    # congress/number must fall back to the <congress>/<legis-num> tags in
    # <form>, which every resolution has regardless of era.
    assert hres80.congress == "111"
    assert hres80.type == "HRES"
    assert hres80.number == "80"


def test_committee_header_strips_trailing_em_dash(hres80):
    # <header>Committee on Standards of Official Conduct.—</header> --
    # trailing period + em dash, not just the usual colon.
    assert hres80.committee_changes[0].committee == "Committee on Standards of Official Conduct"


# --- <committee-name> misplaced outside <header> -----------------------

HRES131_FIXTURE = Path(__file__).parent / "fixtures" / "BILLS-115hres131eh.xml"


@pytest.fixture
def hres131():
    return parse_resolution_xml(HRES131_FIXTURE.read_bytes())


def test_committee_name_tag_misplaced_in_member_text_falls_back_to_header(hres131):
    # H.Res.131 (115th Congress): a genuine GPO XML authoring error --
    # <committee-name> is nested inside <text> (the MEMBER list) instead of
    # <header>, and its text is the member's own rank-qualifier sentence, not
    # a committee name: "<text><committee-name committee-id="HBU00">Mr. Smith
    # of Missouri, to rank immediately after Mr. Johnson of Ohio.</committee-
    # name></text>", while the correct name is separately in
    # "<header>Committee on the Budget:</header>". Searching the whole
    # paragraph for <committee-name> (instead of only inside <header>, where
    # every OTHER Congress's XML nests it) picked up the misplaced tag and
    # turned the member's own qualifier sentence into the "committee".
    committees = [c.committee for c in hres131.committee_changes]
    assert "Committee on the Budget" in committees
    assert "Committee on Education and the Workforce" in committees
    assert not any("rank immediately after" in c for c in committees)


def test_committee_name_tag_misplaced_does_not_corrupt_member_name(hres131):
    budget = [c for c in hres131.committee_changes if c.committee == "Committee on the Budget"]
    assert len(budget) == 1
    assert budget[0].member_name == "Mr. Smith of Missouri"


def test_committee_header_normalizes_inconsistent_casing():
    # BILLS-110hres56eh.xml: several headers in the SAME document are
    # all-lowercase after "Committee on" ("Committee on agriculture:",
    # "Committee on rules:", "Committee on financial services:", "Committee
    # on homeland security:") while others are correctly title-cased
    # ("Committee on Foreign Affairs:") -- an inconsistency in the source
    # document itself. Must normalize to title case either way.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on agriculture:</header><text>Mr. Peterson.</text>"
        "</committee-appointment-paragraph>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Foreign Affairs:</header><text>Mr. Lantos.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.committee for c in record.committee_changes] == [
        "Committee on Agriculture",
        "Committee on Foreign Affairs",
    ]


def test_mixed_semicolon_and_comma_delimiters_all_split(hres80):
    # "Ms. Zoe Lofgren of California, Chairman; Mr. Chandler, Mr. Butterfield,
    # Ms. Castor of Florida, Mr. Welch." -- the semicolon appears ONCE, only
    # to escape the Chairman's own qualifier comma; the rest of the list
    # reverts to plain commas. Switching to semicolon-EXCLUSIVE splitting
    # (because a semicolon is present anywhere) would leave the four
    # comma-separated names glued into one bogus "member" -- silently
    # resolving to whichever of them matches a unique surname (Welch) while
    # dropping the other three entirely.
    assert [c.member_name for c in hres80.committee_changes] == [
        "Ms. Zoe Lofgren of California",
        "Mr. Chandler",
        "Mr. Butterfield",
        "Ms. Castor of Florida",
        "Mr. Welch",
    ]
    assert hres80.committee_changes[0].member_name_raw == "Ms. Zoe Lofgren of California, Chairman"
    assert all(c.member_name_raw is None for c in hres80.committee_changes[1:])


# --- _split_members -------------------------------------------------------

from congress_committees.parser import _split_members


def test_split_members_single():
    assert _split_members("Mr. Gallagher.") == ["Mr. Gallagher"]


def test_split_members_comma_list():
    assert _split_members("Mr. Hoyer, Ms. Kaptur, Mr. Clyburn") == [
        "Mr. Hoyer",
        "Ms. Kaptur",
        "Mr. Clyburn",
    ]


def test_split_members_preserves_of_state_and_two_word_surnames():
    text = "Mr. Bishop of Georgia, Ms. Wasserman Schultz, Mrs. Torres of California"
    assert _split_members(text) == [
        "Mr. Bishop of Georgia",
        "Ms. Wasserman Schultz",
        "Mrs. Torres of California",
    ]


def test_split_members_strips_leading_and_on_final_name():
    assert _split_members("Mr. Hoyer, Ms. Kaptur, and Mr. Ivey") == [
        "Mr. Hoyer",
        "Ms. Kaptur",
        "Mr. Ivey",
    ]


def test_split_members_empty():
    assert _split_members("") == []


def test_committee_appointment_without_committee_name_tag_uses_header_text():
    # Pre-119th-Congress GPO resolution XML never wraps the committee name in a
    # <committee-name> tag -- it's plain text in <header>, colon and all.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>117 HRES 1471 EH: Electing a certain Member</title>"
        "<official-title>Electing a certain Member to a certain standing committee.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Foreign Affairs:</header>"
        "<text>Mrs. Cherfilus-McCormick, to rank immediately after Ms. Manning.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert len(record.committee_changes) == 1
    change = record.committee_changes[0]
    assert change.committee == "Committee on Foreign Affairs"
    assert change.committee_code is None
    assert change.member_name == "Mrs. Cherfilus-McCormick"


def test_committee_name_tag_with_colon_inside_is_stripped():
    # Some resolutions (e.g. real H.Res.22, 119th Congress) put the trailing
    # colon INSIDE the <committee-name> tag rather than after it.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>119 HRES 22 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph><header>"
        '<committee-name committee-id="HAP00"> Committee on Appropriations:</committee-name>'
        "</header><text>Mr. Hoyer.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert record.committee_changes[0].committee == "Committee on Appropriations"


def test_member_text_strips_trailing_chair_designation():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>117 HRES 9 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Agriculture:</header>"
        "<text>Mr. David Scott of Georgia, Chair.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == [
        "Mr. David Scott of Georgia",
    ]


def test_member_text_strips_trailing_chairman_designation():
    # BILLS-113hres6eh.xml (Committee on Agriculture): "Chairman" (not
    # "Chair") -- a distinct word our qualifier regexes didn't recognize,
    # leaving "Chairman" as its own bogus "member" entry.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>113 HRES 6 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Agriculture:</header>"
        "<text>Mr. Lucas, Chairman.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == ["Mr. Lucas"]
    assert record.committee_changes[0].member_name_raw == "Mr. Lucas, Chairman"


def test_semicolon_list_with_chairman_designation():
    # BILLS-113hres6eh.xml (Committee on Ethics): semicolon-separated list
    # whose first entry has a ", Chairman" qualifier.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>113 HRES 6 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Ethics:</header>"
        "<text>Mr. Conaway, Chairman; Mr. Dent; Mr. Meehan; Mr. Gowdy; and "
        "Mrs. Brooks of Indiana.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == [
        "Mr. Conaway", "Mr. Dent", "Mr. Meehan", "Mr. Gowdy", "Mrs. Brooks of Indiana",
    ]
    assert record.committee_changes[0].member_name_raw == "Mr. Conaway, Chairman"


def test_member_text_strips_trailing_rank_qualifier():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>117 HRES 1347 EH: Electing certain Members</title>"
        "<official-title>Electing certain Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Armed Services:</header>"
        "<text>Mr. Ryan of New York, to rank immediately after Ms. Strickland.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == [
        "Mr. Ryan of New York",
    ]


def test_member_text_strips_parenthesized_rank_qualifier():
    # The rank qualifier also appears parenthesized, possibly mid-list:
    # "Mr. LaLota (to rank immediately after Mr. Crane), Mr. Fry."
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>119 HRES 500 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Armed Services:</header>"
        "<text>Mr. LaLota (to rank immediately after Mr. Crane), Mr. Fry.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == [
        "Mr. LaLota",
        "Mr. Fry",
    ]


def test_member_text_strips_rank_ahead_of_qualifier():
    # BILLS-109hres778eh.xml: "Mr. Berman (to rank immediately ahead of Mrs.
    # Jones of Ohio)." -- "ahead of" instead of "after", the only direction
    # previously recognized.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>109 HRES 778 EH: Electing a certain Member</title>"
        "<official-title>Electing a certain Member to a certain standing committee.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Standards of Official Conduct:</header>"
        "<text>Mr. Berman (to rank immediately ahead of Mrs. Jones of Ohio).</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    change = record.committee_changes[0]
    assert change.member_name == "Mr. Berman"
    assert change.member_name_raw == (
        "Mr. Berman (to rank immediately ahead of Mrs. Jones of Ohio)"
    )


def test_qualifier_note_preserved_in_raw_field_parenthesized():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>119 HRES 500 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Armed Services:</header>"
        "<text>Mr. LaLota (to rank immediately after Mr. Crane), Mr. Fry.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    lalota, fry = record.committee_changes
    assert lalota.member_name == "Mr. LaLota"
    assert lalota.member_name_raw == "Mr. LaLota (to rank immediately after Mr. Crane)"
    # Fry carries no qualifier -- raw stays unset.
    assert fry.member_name == "Mr. Fry"
    assert fry.member_name_raw is None


def test_two_members_joined_by_and_with_parenthesized_qualifiers_split():
    # BILLS-116hres85eh.xml: two members joined by "and" with no comma at all,
    # each carrying its own parenthesized rank qualifier.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>116 HRES 85 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on the Budget:</header>"
        "<text>Mr. Higgins of New York (to rank immediately after Mr. Jeffries) and "
        "Mr. Brendan F. Boyle of Pennsylvania (to rank immediately after Mr. Higgins "
        "of New York).</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert len(record.committee_changes) == 2
    higgins, boyle = record.committee_changes
    assert higgins.member_name == "Mr. Higgins of New York"
    assert higgins.member_name_raw == (
        "Mr. Higgins of New York (to rank immediately after Mr. Jeffries)"
    )
    assert boyle.member_name == "Mr. Brendan F. Boyle of Pennsylvania"
    assert boyle.member_name_raw == (
        "Mr. Brendan F. Boyle of Pennsylvania (to rank immediately after "
        "Mr. Higgins of New York)"
    )


def test_semicolon_separated_list_with_embedded_qualifier_comma():
    # BILLS-114hres6eh.xml (Committee on House Administration): "Mrs. Miller
    # of Michigan, Chair; Mr. Harper; Mr. Schock; Mr. Nugent; Mr. Rodney Davis
    # of Illinois; and Mrs. Comstock." -- the FIRST member's own qualifier
    # comma (", Chair") means the list can't use commas as its separator, so
    # it switches to semicolons instead.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>114 HRES 6 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on House Administration:</header>"
        "<text>Mrs. Miller of Michigan, Chair; Mr. Harper; Mr. Schock; Mr. Nugent; "
        "Mr. Rodney Davis of Illinois; and Mrs. Comstock.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == [
        "Mrs. Miller of Michigan",
        "Mr. Harper",
        "Mr. Schock",
        "Mr. Nugent",
        "Mr. Rodney Davis of Illinois",
        "Mrs. Comstock",
    ]
    assert record.committee_changes[0].member_name_raw == "Mrs. Miller of Michigan, Chair"
    assert all(c.member_name_raw is None for c in record.committee_changes[1:])


def test_when_sworn_qualifier_stripped_from_member_name():
    # BILLS-114hres7eh.xml (Committee on Foreign Affairs): "Mr. Engel (when
    # sworn)." -- a newly-elected member not yet sworn in at vote time.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>114 HRES 7 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Foreign Affairs:</header>"
        "<text>Mr. Engel (when sworn).</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    change = record.committee_changes[0]
    assert change.member_name == "Mr. Engel"
    assert change.member_name_raw == "Mr. Engel (when sworn)"


def test_when_sworn_qualifier_in_semicolon_separated_list():
    # BILLS-114hres7eh.xml (Committee on Ways and Means): semicolon-separated
    # list combined with two "(when sworn)" qualifiers.
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>114 HRES 7 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Ways and Means:</header>"
        "<text>Mr. Levin; Mr. Rangel (when sworn); Mr. McDermott; and "
        "Ms. Linda T. Sanchez of California.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert [c.member_name for c in record.committee_changes] == [
        "Mr. Levin", "Mr. Rangel", "Mr. McDermott", "Ms. Linda T. Sanchez of California",
    ]
    assert record.committee_changes[1].member_name_raw == "Mr. Rangel (when sworn)"


def test_qualifier_note_preserved_in_raw_field_comma_form():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>117 HRES 1347 EH: Electing certain Members</title>"
        "<official-title>Electing certain Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Armed Services:</header>"
        "<text>Mr. Ryan of New York, to rank immediately after Ms. Strickland.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    change = record.committee_changes[0]
    assert change.member_name == "Mr. Ryan of New York"
    assert change.member_name_raw == (
        "Mr. Ryan of New York, to rank immediately after Ms. Strickland"
    )


def test_chair_designation_preserved_in_raw_field():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>117 HRES 9 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph>"
        "<header>Committee on Agriculture:</header>"
        "<text>Mr. David Scott of Georgia, Chair.</text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    change = record.committee_changes[0]
    assert change.member_name == "Mr. David Scott of Georgia"
    assert change.member_name_raw == "Mr. David Scott of Georgia, Chair"


def test_plain_multi_member_list_has_no_raw_notes():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>119 HRES 22 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph><header>"
        '<committee-name committee-id="HAP00">Committee on Appropriations</committee-name>:'
        "</header><text> Mr. Hoyer, Ms. Kaptur, Mr. Bishop of Georgia. </text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    assert all(c.member_name_raw is None for c in record.committee_changes)


# --- party_rank (organizing-window multi-member lists) ---------------------


def _organizing_xml(action_date, *paragraphs):
    body = "".join(paragraphs)
    return (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>119 HRES 22 EH: Electing Members</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        f'<action-date date="{action_date}"/>'
        f"<resolution-body>{body}</resolution-body></resolution>"
    ).encode()


def _paragraph(committee_id, committee, members):
    return (
        "<committee-appointment-paragraph><header>"
        f'<committee-name committee-id="{committee_id}">{committee}</committee-name>:'
        f"</header><text>{members}.</text>"
        "</committee-appointment-paragraph>"
    )


def test_organizing_window_multi_member_paragraph_gets_ranks_starting_at_two():
    xml = _organizing_xml(
        "20250114",
        _paragraph("HAP00", "Committee on Appropriations", "Mr. Hoyer, Ms. Kaptur, Mr. Clyburn"),
    )
    record = parse_resolution_xml(xml)
    assert [(c.member_name, c.party_rank) for c in record.committee_changes] == [
        ("Mr. Hoyer", 2),
        ("Ms. Kaptur", 3),
        ("Mr. Clyburn", 4),
    ]


def test_single_member_paragraph_in_organizing_window_has_no_rank():
    xml = _organizing_xml(
        "20250114",
        _paragraph("HAP00", "Committee on Appropriations", "Mr. Hoyer, Ms. Kaptur"),
        _paragraph("HBU00", "Committee on the Budget", "Mr. Boyle"),
    )
    record = parse_resolution_xml(xml)
    by_committee = {c.committee: c.party_rank for c in record.committee_changes if c.committee == "Committee on the Budget"}
    assert by_committee == {"Committee on the Budget": None}
    multi = [c.party_rank for c in record.committee_changes if c.committee == "Committee on Appropriations"]
    assert multi == [2, 3]


def test_multi_member_paragraph_outside_organizing_window_has_no_ranks():
    # Same shape as a January organizing list, but dated mid-Congress (e.g. an
    # H.Res.111-style append to an existing roster) -- printed order there is
    # not party seniority, so no ranks should be assigned.
    xml = _organizing_xml(
        "20250624",
        _paragraph("HAP00", "Committee on Appropriations", "Mr. Hoyer, Ms. Kaptur, Mr. Clyburn"),
    )
    record = parse_resolution_xml(xml)
    assert all(c.party_rank is None for c in record.committee_changes)


def test_explicitly_named_chair_gets_rank_one():
    # BILLS-113hres6eh.xml (Committee on Ethics): "Mr. Conaway, Chairman;
    # Mr. Dent; Mr. Meehan; Mr. Gowdy; and Mrs. Brooks of Indiana." -- THIS
    # resolution names the chair explicitly, so Conaway is rank 1 (not the
    # usual offset-by-2 that assumes the chair was elected in a separate
    # resolution).
    xml = _organizing_xml(
        "20250114",
        _paragraph(
            "HSSO00", "Committee on Ethics",
            "Mr. Conaway, Chairman; Mr. Dent; Mr. Meehan; Mr. Gowdy; and Mrs. Brooks of Indiana",
        ),
    )
    record = parse_resolution_xml(xml)
    assert [(c.member_name, c.party_rank) for c in record.committee_changes] == [
        ("Mr. Conaway", 1),
        ("Mr. Dent", 2),
        ("Mr. Meehan", 3),
        ("Mr. Gowdy", 4),
        ("Mrs. Brooks of Indiana", 5),
    ]


def test_explicitly_named_single_chair_gets_rank_one():
    # BILLS-113hres6eh.xml (Committee on Agriculture): "Mr. Lucas, Chairman."
    # -- a single-member paragraph, but the chair designation alone still
    # earns rank 1 (unlike an ordinary single-member addition, which gets no
    # rank at all).
    xml = _organizing_xml(
        "20250114",
        _paragraph("HSAG00", "Committee on Agriculture", "Mr. Lucas, Chairman"),
    )
    record = parse_resolution_xml(xml)
    assert [(c.member_name, c.party_rank) for c in record.committee_changes] == [
        ("Mr. Lucas", 1),
    ]


def test_chair_rank_only_applies_within_organizing_window():
    xml = _organizing_xml(
        "20250624",
        _paragraph("HSSO00", "Committee on Ethics", "Mr. Conaway, Chairman; Mr. Dent"),
    )
    record = parse_resolution_xml(xml)
    assert all(c.party_rank is None for c in record.committee_changes)


def test_golden_fixture_outside_window_has_no_ranks(hres1381):
    # BILLS-119hres1381eh.xml is dated 2026-06-24 -- outside any organizing window.
    assert all(c.party_rank is None for c in hres1381.committee_changes)


def test_multi_member_paragraph_explodes_into_one_change_per_member():
    xml = (
        '<?xml version="1.0"?>'
        "<resolution resolution-stage=\"Engrossed-in-House\">"
        "<title>119 HRES 22 EH: Electing Members to committees</title>"
        "<official-title>Electing Members to certain standing committees.</official-title>"
        "<resolution-body>"
        "<committee-appointment-paragraph><header>"
        '<committee-name committee-id="HAP00">Committee on Appropriations</committee-name>:'
        "</header><text> Mr. Hoyer, Ms. Kaptur, Mr. Bishop of Georgia. </text>"
        "</committee-appointment-paragraph>"
        "</resolution-body></resolution>"
    )
    record = parse_resolution_xml(xml.encode())
    changes = record.committee_changes
    assert [c.member_name for c in changes] == [
        "Mr. Hoyer",
        "Ms. Kaptur",
        "Mr. Bishop of Georgia",
    ]
    # Every exploded change keeps the same committee identity and change type.
    assert {c.committee_code for c in changes} == {"HAP00"}
    assert {c.committee for c in changes} == {"Committee on Appropriations"}
    assert {c.change_type for c in changes} == {"addition"}
