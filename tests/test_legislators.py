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
