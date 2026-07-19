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


# --- accent folding --------------------------------------------------------

ACCENTED = [
    {
        "id": {"bioguide": "V000081"},
        "name": {"first": "Nydia", "last": "Velázquez"},
        "terms": [{"type": "rep", "state": "NY", "start": "1993-01-05"}],
    },
    {
        "id": {"bioguide": "B001300"},
        "name": {"first": "Nanette", "last": "Barragan"},  # YAML side unaccented
        "terms": [{"type": "rep", "state": "CA", "start": "2017-01-03"}],
    },
]


@pytest.fixture
def accented_index():
    return LegislatorIndex.from_records(ACCENTED)


def test_unaccented_signer_matches_accented_yaml_name(accented_index):
    # CREC letter text prints "Velazquez"; congress-legislators has "Velázquez".
    assert accented_index.lookup_full_name("Nydia", "Velazquez", "2026-01-15") == "V000081"


def test_accented_printed_name_matches_unaccented_yaml_name(accented_index):
    # The reverse direction: resolution prints the accent, YAML lacks it.
    assert accented_index.lookup("Ms. Barragán") == "B001300"


def test_accented_lookup_still_resolves(accented_index):
    assert accented_index.lookup("Ms. Velázquez") == "V000081"


# --- apostrophe folding -----------------------------------------------------

APOSTROPHE = [
    {
        "id": {"bioguide": "D000230"},
        "name": {"first": "Anthony", "last": "D'Esposito"},  # straight apostrophe, per YAML
        "terms": [{"type": "rep", "state": "NY", "start": "2023-01-07"}],
    },
]


@pytest.fixture
def apostrophe_index():
    return LegislatorIndex.from_records(APOSTROPHE)


def test_curly_apostrophe_printed_name_matches_straight_yaml_name(apostrophe_index):
    # Resolution/CREC text often prints a curly right single quote (’);
    # congress-legislators uses a straight apostrophe (').
    assert apostrophe_index.lookup("Mr. D’Esposito") == "D000230"


def test_straight_apostrophe_lookup_still_resolves(apostrophe_index):
    assert apostrophe_index.lookup("Mr. D'Esposito") == "D000230"


# --- hyphen/space surname folding -------------------------------------------

HYPHEN_SURNAME = [
    {
        "id": {"bioguide": "J000032"},
        "name": {"first": "Sheila", "last": "Jackson Lee"},  # space, per YAML
        "terms": [{"type": "rep", "state": "TX", "start": "1995-01-04"}],
    },
]


@pytest.fixture
def hyphen_index():
    return LegislatorIndex.from_records(HYPHEN_SURNAME)


def test_hyphenated_printed_surname_matches_space_separated_yaml_name(hyphen_index):
    # BILLS-110hres56eh.xml prints "Jackson-Lee" (hyphen); congress-legislators
    # stores her as "Jackson Lee" (space).
    assert hyphen_index.lookup("Ms. Jackson-Lee") == "J000032"


def test_space_separated_lookup_still_resolves(hyphen_index):
    assert hyphen_index.lookup("Ms. Jackson Lee") == "J000032"


# --- nickname first-name matching -------------------------------------------

TWO_DAVISES_VA = [
    {
        "id": {"bioguide": "D000136"},
        "name": {"first": "Thomas", "last": "Davis"},
        "terms": [{"type": "rep", "state": "VA", "start": "1995-01-04"}],
    },
    {
        "id": {"bioguide": "D000597"},
        "name": {"first": "Jo Ann", "last": "Davis"},
        "terms": [{"type": "rep", "state": "VA", "start": "2001-01-03"}],
    },
]


@pytest.fixture
def davis_va_index():
    return LegislatorIndex.from_records(TWO_DAVISES_VA)


def test_nickname_matches_formal_first_name(davis_va_index):
    # BILLS-110hres56eh.xml prints "Mr. Tom Davis of Virginia" -- "Tom" isn't
    # a prefix of "Thomas" (unlike "Chris"/"Christopher", which already
    # matches), so it needs an explicit nickname equivalence.
    assert davis_va_index.lookup("Mr. Tom Davis of Virginia") == "D000136"


def test_formal_first_name_lookup_still_resolves(davis_va_index):
    assert davis_va_index.lookup("Mr. Thomas Davis of Virginia") == "D000136"


# --- missing space after honorific -------------------------------------------

def test_honorific_without_trailing_space_still_strips(index):
    # BILLS-109hres48eh.htm: "Mr.McKeon" -- a genuine typo in the source
    # document (no space after the period). Without tolerating this, the
    # honorific never strips and "mr.mckeon" is looked up as one surname.
    assert index.lookup("Mr.Gallagher") == "G000587"


# --- "of"/"or" state-connector typo tolerance --------------------------------

from congress_committees.legislators import _strip_honorific_and_state


def test_or_typo_for_of_state_connector():
    # BILLS-109hres49eh.htm: "Ms. Hooley or Oregon" -- a genuine typo in the
    # source document ("or" instead of "of"). Small, bounded substitution in a
    # fixed grammatical position (the state connector), unlike a surname typo.
    name, state = _strip_honorific_and_state("Ms. Hooley or Oregon")
    assert name == "Hooley"
    assert state == "OR"


def test_of_state_connector_still_resolves():
    name, state = _strip_honorific_and_state("Ms. Hooley of Oregon")
    assert name == "Hooley"
    assert state == "OR"


# --- honorific gender disambiguates a same-state, same-date namesake --------


def test_honorific_gender_disambiguates_same_state_same_date_namesake(index):
    # H.Res.19 (107th Congress): "Mr. Johnson of Texas" is printed with no
    # first name -- Sam Johnson (M) and Eddie Bernice Johnson (F) both
    # represented Texas and were both serving on 2001-01-06, so state+date
    # alone leaves two candidates. The honorific ("Mr." vs "Ms./Mrs./Miss")
    # is a real, bounded gender signal already printed in the source that
    # breaks the tie.
    assert index.lookup("Mr. Johnson of Texas", on_date="2001-01-06") == "J000174"
    assert index.lookup("Ms. Johnson of Texas", on_date="2001-01-06") == "J000126"


def test_no_honorific_gender_signal_stays_ambiguous(index):
    # Without a date or state to narrow the pool at all, gender alone from
    # the honorific isn't enough on its own to guess between two Smiths of
    # the same apparent gender presentation -- unaffected by the new gender
    # tiebreak, still None.
    assert index.lookup("Mr. Smith") is None


# --- state-name typo tolerance ----------------------------------------------

from congress_committees.legislators import _normalize_state

TWO_GREENS = [
    {
        "id": {"bioguide": "G000590"},
        "name": {"first": "Mark", "last": "Green"},
        "terms": [{"type": "rep", "state": "TN", "start": "2019-01-03"}],
    },
    {
        "id": {"bioguide": "G000553"},
        "name": {"first": "Al", "last": "Green"},
        "terms": [{"type": "rep", "state": "TX", "start": "2005-01-04"}],
    },
]


@pytest.fixture
def greens_index():
    return LegislatorIndex.from_records(TWO_GREENS)


def test_normalize_state_tolerates_minor_typo():
    # Real bill XML typo (BILLS-117hres63eh.xml): "Tennnesse" for "Tennessee".
    assert _normalize_state("Tennnesse") == "TN"


def test_normalize_state_rejects_unrecognizable_input():
    assert _normalize_state("Nowhereland") is None


def test_misspelled_state_still_disambiguates_surname(greens_index):
    # Without state disambiguation, two Greens are both active and ambiguous.
    assert greens_index.lookup("Mr. Green") is None
    # A minor state-name typo should still resolve to the one from Tennessee.
    assert greens_index.lookup("Mr. Green of Tennnesse") == "G000590"


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


# --- hyphen mistakenly joining a middle name to the surname -----------------

MIDDLE_HYPHENATED_TO_LAST = [
    {
        "id": {"bioguide": "N000147"},
        "name": {"first": "Eleanor", "middle": "Holmes", "last": "Norton"},
        "terms": [{"type": "rep", "state": "DC", "start": "1991-01-03"}],
    },
    {
        "id": {"bioguide": "J000126"},
        "name": {"first": "Eddie", "middle": "Bernice", "last": "Johnson"},
        "terms": [{"type": "rep", "state": "TX", "start": "1993-01-05"}],
    },
    # A genuinely unrelated same-surname decoy in a DIFFERENT state -- the
    # real-world case this guards against: H.Res.434 (105th Congress) prints
    # "Ms. Christian-Green of the Virgin Islands" for Donna Christian-Green,
    # whose congress-legislators record only exists under her later married
    # name "Christensen" (a name-change gap, not fixable here) -- but the
    # after-hyphen fallback's bare surname "Green" DOES match an entirely
    # different, real person: Gene Green (D-TX). Without a state check
    # specific to this speculative fallback, that coincidence resolves
    # confidently to the WRONG bioguide instead of correctly staying None.
    {
        "id": {"bioguide": "G000410"},
        "name": {"first": "Gene", "last": "Green"},
        "terms": [{"type": "rep", "state": "TX", "start": "1993-01-05"}],
    },
]


@pytest.fixture
def middle_hyphenated_index():
    return LegislatorIndex.from_records(MIDDLE_HYPHENATED_TO_LAST)


def test_hyphen_joining_middle_name_to_surname_still_resolves(middle_hyphenated_index):
    # H.Res.13 (105th Congress) prints "Eleanor Holmes-Norton" and "Eddie
    # Bernice-Johnson" -- a hyphen mistakenly joining the MIDDLE name to the
    # surname, not a genuine two-word hyphenated surname (her real last name
    # is just "Norton"/"Johnson"; "Holmes"/"Bernice" are middle names). Unlike
    # "Jackson-Lee" (a genuine two-word surname stored as "Jackson Lee" in the
    # YAML), folding the hyphen to a space here produces "holmes norton" /
    # "bernice johnson", neither of which is an indexed surname.
    assert middle_hyphenated_index.lookup("Ms. Holmes-Norton") == "N000147"
    assert middle_hyphenated_index.lookup("Ms. Eleanor Holmes-Norton") == "N000147"
    assert middle_hyphenated_index.lookup("Mr. Eddie Bernice-Johnson of Texas") == "J000126"


def test_hyphen_fallback_does_not_false_match_an_unrelated_same_surname(middle_hyphenated_index):
    # "Ms. Christian-Green of the Virgin Islands" -- the after-hyphen
    # surname "Green" is real, but belongs to an unrelated Texas
    # representative (Gene Green), not the Virgin Islands delegate this text
    # actually names. The state doesn't match anyone, so this must stay
    # unresolved rather than confidently returning Gene Green's bioguide.
    assert middle_hyphenated_index.lookup("Ms. Christian-Green of the Virgin Islands") is None


# --- generational suffix (Jr./Sr./II/III) --------------------------------

SUFFIXED = [
    {
        "id": {"bioguide": "B000550"},
        "name": {"first": "George", "last": "Brown"},
        "terms": [{"type": "rep", "state": "CA", "start": "1963-01-09"}],
    },
]


@pytest.fixture
def suffixed_index():
    return LegislatorIndex.from_records(SUFFIXED)


def test_generational_suffix_stripped_before_surname_lookup(suffixed_index):
    # H.Res.13 (105th Congress) prints full names with a generational suffix
    # comma-separated from the state ("George Brown, Jr., California"),
    # reconstructed here as "George Brown Jr. of California" -- the
    # congress-legislators YAML has no "Jr."/"Sr."/"II"/"III" in `last` at
    # all, so it must be stripped before the surname lookup, not treated as
    # part of the surname.
    assert suffixed_index.lookup("George Brown Jr. of California") == "B000550"
    assert suffixed_index.lookup("George Brown of California") == "B000550"


# --- "the <Territory>" state-connector phrasing ------------------------------


def test_state_normalization_tolerates_leading_the():
    # H.Res.434 (105th Congress): "Ms. Christian-Green of the Virgin
    # Islands" -- "the" isn't part of the _STATES dict's key ("virgin
    # islands"), a common phrasing variant for territories/D.C., not a typo.
    assert _normalize_state("the Virgin Islands") == "VI"


def test_state_normalization_handles_dc_abbreviation():
    # H.Res.31 (104th Congress): "*Eleanor Holmes Norton, D.C. (Delegate)"
    # -- the printed member text's own general trailing-period cleanup
    # strips the final "." from "D.C.", so both forms must resolve.
    assert _normalize_state("D.C.") == "DC"
    assert _normalize_state("D.C") == "DC"
