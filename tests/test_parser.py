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
