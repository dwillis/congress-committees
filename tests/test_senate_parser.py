"""Tests for Senate S.Res. committee-assignment resolution parsing."""

from pathlib import Path

from congress_committees.senate_parser import (
    classify_senate_title,
    parse_senate_resolution_text,
    parse_senate_resolution_xml,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text()


# --- title classification ---------------------------------------------------


def test_classify_majority_title():
    title = (
        "To constitute the majority party's membership on certain committees "
        "for the One Hundred Nineteenth Congress, or until their successors "
        "are chosen."
    )
    assert classify_senate_title(title) == "majority"


def test_classify_minority_title():
    title = "A resolution making minority party appointments to Senate committees for the 106th Congress."
    assert classify_senate_title(title) == "minority"


def test_classify_non_committee_title_returns_none():
    assert classify_senate_title("A resolution to amend the Rules of the Senate.") is None


def test_classify_party_agnostic_appointment_title_returns_none():
    # S.Res.136 (102nd Congress) -- a known, accepted gap (see module docstring).
    assert classify_senate_title(
        "To make appointments to the Committee on Environment and Public "
        "Works, the Committee on Foreign Relations, and the Committee on "
        "Small Business."
    ) is None


# --- full-roster XML schema (119th Congress, S.Res.16) ----------------------


def test_parse_xml_full_roster_extracts_every_committee():
    rosters, single_adds = parse_senate_resolution_xml(_load("BILLS-119sres16ats.xml"))
    assert single_adds == []
    names = [r.committee for r in rosters]
    assert "Committee on Agriculture, Nutrition, and Forestry" in names
    assert "Committee on the Judiciary" in names
    assert "Select Committee on Ethics" in names


def test_parse_xml_full_roster_splits_members_and_keeps_state_disambiguator():
    rosters, _ = parse_senate_resolution_xml(_load("BILLS-119sres16ats.xml"))
    armed_services = next(r for r in rosters if r.committee == "Committee on Armed Services")
    names = [m for m, _raw in armed_services.members]
    assert "Mr. Wicker" in names
    # Two Senators named Scott sit on Armed Services (FL) and elsewhere --
    # the (FL)/(SC) disambiguator must survive into the clean name.
    assert "Mr. Scott (FL)" in names


def test_parse_xml_strips_chair_annotation_into_raw():
    rosters, _ = parse_senate_resolution_xml(_load("BILLS-119sres16ats.xml"))
    agriculture = next(
        r for r in rosters if r.committee == "Committee on Agriculture, Nutrition, and Forestry"
    )
    clean, raw = agriculture.members[0]
    assert clean == "Mr. Boozman"
    assert raw == "Mr. Boozman (Chair)"


def test_parse_xml_skips_blank_placeholder_seats():
    rosters, _ = parse_senate_resolution_xml(_load("BILLS-119sres16ats.xml"))
    agriculture = next(
        r for r in rosters if r.committee == "Committee on Agriculture, Nutrition, and Forestry"
    )
    names = [m for m, _raw in agriculture.members]
    assert all(n.strip("_") for n in names)


def test_parse_xml_committee_name_tag_supplies_code():
    # S.Res.26 uses <committee-name committee-id="SSAF00"> -- newer rendition.
    rosters, _ = parse_senate_resolution_xml(_load("BILLS-119sres26ats.xml"))
    agriculture = next(
        r for r in rosters if r.committee == "Committee on Agriculture, Nutrition, and Forestry"
    )
    assert agriculture.committee_code == "SSAF00"


def test_parse_xml_minority_resolution_parses_same_shape():
    rosters, single_adds = parse_senate_resolution_xml(_load("BILLS-119sres17ats.xml"))
    assert single_adds == []
    assert len(rosters) > 0


def test_parse_xml_strips_ranking_annotation_not_ranking_member():
    # The real minority resolution prints the bare word "(Ranking)", never
    # "(Ranking Member)" -- confirmed live in BILLS-119sres17ats.xml.
    rosters, _ = parse_senate_resolution_xml(_load("BILLS-119sres17ats.xml"))
    agriculture = next(
        r for r in rosters if r.committee == "Committee on Agriculture, Nutrition, and Forestry"
    )
    clean, raw = agriculture.members[0]
    assert clean == "Ms. Klobuchar"
    assert raw == "Ms. Klobuchar (Ranking)"


def test_parse_xml_strips_ex_officio_annotation():
    rosters, _ = parse_senate_resolution_xml(_load("BILLS-119sres17ats.xml"))
    intel = next(r for r in rosters if r.committee == "Select Committee on Intelligence")
    names = [m for m, _raw in intel.members]
    assert "Mr. Reed" in names
    assert "Mr. Schumer" in names
    assert not any("officio" in n.lower() for n in names)


# --- single-add plain-text schema (102nd Congress, S.Res.137) ---------------


def test_parse_text_single_add_schema():
    rosters, single_adds = parse_senate_resolution_text(_load_text("BILLS-102sres137ats.htm"))
    assert rosters == []
    assert len(single_adds) == 1
    addition = single_adds[0]
    assert addition.committee == "Committee on Banking, Housing, and Urban Affairs"
    assert addition.member == "Mr. Chafee"
    assert addition.until_date == "November 6, 1991"
