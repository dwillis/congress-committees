"""Tests for parsing Congressional Record committee-resignation letters."""

from pathlib import Path

from congress_committees.parser import parse_resignation_granule

FIX = Path(__file__).parent / "fixtures"
INTEL = (FIX / "CREC-2001-02-08-pt1-PgH228-resignation.txt").read_text()
INTEL_TITLE = "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE"
MULTI = (FIX / "CREC-2001-02-08-multi-resignation.txt").read_text()
MULTI_TITLE = "RESIGNATION AS MEMBER OF COMMITTEE ON AGRICULTURE AND COMMITTEE ON RESOURCES"


def test_parses_single_committee_resignation():
    result = parse_resignation_granule(INTEL_TITLE, INTEL)
    assert result.committees == ["House Permanent Select Committee on Intelligence"]
    assert result.member_name == "Charles F. Bass"
    assert result.signed_date == "2001-02-07"


def test_parses_multi_committee_resignation():
    result = parse_resignation_granule(MULTI_TITLE, MULTI)
    assert result.committees == ["Committee on Agriculture", "Committee on Resources"]
    assert result.member_name == "Jane Q. Member"


def test_split_tolerates_and_the_committee_joiner():
    # Some titles use "... AND THE COMMITTEE ON ..." — must still split into two.
    title = "RESIGNATION AS MEMBER OF COMMITTEE ON SCIENCE AND THE COMMITTEE ON VETERANS' AFFAIRS"
    result = parse_resignation_granule(title, "")
    assert result.committees == ["Committee on Science", "Committee on Veterans' Affairs"]


def test_does_not_split_on_non_committee_and():
    # "AND" not followed by COMMITTEE/HOUSE must NOT split the name.
    title = "RESIGNATION AS MEMBER OF COMMITTEE ON BANKING AND FINANCIAL SERVICES"
    result = parse_resignation_granule(title, "")
    assert result.committees == ["Committee on Banking and Financial Services"]
