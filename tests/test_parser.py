"""Tests for parsing GPO bill XML into committee-change records."""

from pathlib import Path

import pytest

from congress_committees.parser import parse_resolution_xml

FIXTURE = Path(__file__).parent / "fixtures" / "BILLS-119hres1381eh.xml"


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
