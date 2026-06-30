"""Tests for resolving printed member names to bioguide IDs."""

from pathlib import Path

import pytest

from congress_committees.legislators import LegislatorIndex

SAMPLE = Path(__file__).parent / "fixtures" / "legislators-sample.yaml"


@pytest.fixture
def index():
    return LegislatorIndex.from_yaml_files([SAMPLE])


def test_unique_surname_resolves(index):
    assert index.lookup("Mr. Gallagher") == "G000587"


def test_ambiguous_surname_returns_none(index):
    # Two Representatives named Smith and no state given.
    assert index.lookup("Mr. Smith") is None


def test_state_disambiguates_surname(index):
    assert index.lookup("Mr. Smith of Missouri") == "S001195"
    assert index.lookup("Ms. Smith of Washington") == "S000510"


def test_unknown_member_returns_none(index):
    assert index.lookup("Mrs. Nobody") is None


def test_only_house_members_considered(index):
    # Feinstein only ever served in the Senate, so she is not a candidate.
    assert index.lookup("Mrs. Feinstein") is None


def test_lookup_full_name_with_date(index):
    assert index.lookup_full_name("Charles", "Bass", "2001-02-08") == "B000220"
    # No one named that serving in 1990 -> None
    assert index.lookup_full_name("Charles", "Bass", "1990-01-01") is None


def test_lookup_full_name_disambiguates_surname(index):
    # Two House "Smith" reps in the fixture; first name disambiguates.
    assert index.lookup_full_name("Adam", "Smith", None) == "S000510"
    # No first-name match -> fallback restores both -> ambiguous -> None.
    assert index.lookup_full_name("Robert", "Smith", None) is None


# --- multi-word surname resolution ---------------------------------------

MULTI_WORD = [
    {
        "id": {"bioguide": "W000797"},
        "name": {"first": "Debbie", "last": "Wasserman Schultz"},
        "terms": [{"type": "rep", "state": "FL", "start": "2005-01-03"}],
    },
    {
        "id": {"bioguide": "W000822"},
        "name": {"first": "Bonnie", "last": "Watson Coleman"},
        "terms": [{"type": "rep", "state": "NJ", "start": "2015-01-06"}],
    },
    {
        "id": {"bioguide": "P000618"},
        "name": {"first": "Marie", "last": "Gluesenkamp Perez"},
        "terms": [{"type": "rep", "state": "WA", "start": "2023-01-03"}],
    },
    {
        "id": {"bioguide": "S001157"},
        "name": {"first": "David", "last": "Scott"},
        "terms": [{"type": "rep", "state": "GA", "start": "2003-01-07"}],
    },
]


@pytest.fixture
def multi_index():
    return LegislatorIndex.from_records(MULTI_WORD)


def test_two_word_surname_resolves(multi_index):
    assert multi_index.lookup("Ms. Wasserman Schultz") == "W000797"
    assert multi_index.lookup("Mrs. Watson Coleman") == "W000822"
    assert multi_index.lookup("Ms. Gluesenkamp Perez") == "P000618"


def test_first_name_before_surname_resolves(multi_index):
    # "Mr. David Scott of Georgia": David is a first name, Scott the surname.
    assert multi_index.lookup("Mr. David Scott of Georgia") == "S001157"


# --- date-based disambiguation -------------------------------------------

DATED = [
    {
        "id": {"bioguide": "F000001"},
        "name": {"first": "Bill", "last": "Foster"},
        "terms": [{"type": "rep", "state": "IL", "start": "2008-03-08"}],  # still serving
    },
    {
        "id": {"bioguide": "F000002"},
        "name": {"first": "Ezra", "last": "Foster"},
        "terms": [{"type": "rep", "state": "NY", "start": "1899-01-01", "end": "1905-01-01"}],
    },
]


@pytest.fixture
def dated_index():
    return LegislatorIndex.from_records(DATED)


def test_agreed_to_date_disambiguates_same_surname(dated_index):
    # Two Fosters, no state printed: ambiguous without a date...
    assert dated_index.lookup("Mr. Foster") is None
    # ...but only one was serving on the resolution date.
    assert dated_index.lookup("Mr. Foster", on_date="2025-01-09") == "F000001"


def test_date_with_no_one_serving_stays_ambiguous(dated_index):
    # A date that narrows to nobody must not silently pick someone.
    assert dated_index.lookup("Mr. Foster", on_date="1950-01-01") is None


def test_resolve_files_with_directory():
    from congress_committees.legislators import resolve_legislator_files

    files = resolve_legislator_files("/data/cl", ".cache")
    assert [f.name for f in files] == [
        "legislators-current.yaml",
        "legislators-historical.yaml",
    ]
    assert all(str(f).startswith("/data/cl") for f in files)


def test_resolve_files_with_explicit_yaml():
    from congress_committees.legislators import resolve_legislator_files

    files = resolve_legislator_files("/data/custom.yaml", ".cache")
    assert [str(f) for f in files] == ["/data/custom.yaml"]


def test_resolve_files_defaults_to_cache():
    from congress_committees.legislators import resolve_legislator_files

    files = resolve_legislator_files(None, "/tmp/clcache")
    assert [str(f) for f in files] == [
        "/tmp/clcache/legislators-current.yaml",
        "/tmp/clcache/legislators-historical.yaml",
    ]
