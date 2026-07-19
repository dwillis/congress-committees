"""End-to-end resignation collection with injected fakes (no network)."""

from pathlib import Path

from congress_committees.committees import CommitteeIndex
from congress_committees.legislators import LegislatorIndex
from congress_committees.resignations import collect_resignations

FIX = Path(__file__).parent / "fixtures"
INTEL_TEXT = (FIX / "CREC-2001-02-08-pt1-PgH228-resignation.txt").read_text()

COMMITTEE_RECORDS = [
    {"systemCode": "hlig00", "name": "Permanent Select Committee on Intelligence",
     "previous_names": []},
]


class FakeCREC:
    def discover_resignations(self, start, end):
        return [{"granuleId": "CREC-2001-02-08-pt1-PgH228", "packageId": "CREC-2001-02-08",
                 "title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE"}]

    def fetch_granule(self, package_id, granule_id):
        return INTEL_TEXT, {"granule_id": granule_id, "page": "H228",
                            "url": "https://www.govinfo.gov/app/details/CREC-2001-02-08"}


def _collect():
    committees = CommitteeIndex.from_records(COMMITTEE_RECORDS)
    legislators = LegislatorIndex.from_yaml_files([FIX / "legislators-sample.yaml"])
    return collect_resignations(
        congress=107, client=FakeCREC(), start="2001-02-08", end="2001-02-09",
        committees=committees, legislators=legislators,
    )


def test_collect_resignations_emits_removal_event():
    events = _collect()
    assert len(events) == 1
    ev = events[0]
    assert ev.change_type == "removal"
    assert ev.committee == "House Permanent Select Committee on Intelligence"
    assert ev.system_code == "hlig00"
    assert ev.gpo_code is None
    assert ev.member_name == "Charles F. Bass"
    assert ev.bioguide_id == "B000220"
    assert ev.source == "congressional_record"
    assert ev.source_ref.type == "congressional_record"
    assert ev.source_ref.page == "H228"
    assert ev.date == "2001-02-08"


MULTI_TEXT = (FIX / "CREC-2001-02-08-multi-resignation.txt").read_text()

MULTI_COMMITTEE_RECORDS = [
    {"systemCode": "hsag00", "name": "Agriculture Committee"},
    {"systemCode": "hsii00", "name": "Natural Resources Committee",
     "previous_names": ["Committee on Resources"]},
]


class FakeMultiCREC:
    def discover_resignations(self, start, end):
        return [{"granuleId": "CREC-2001-02-08-multi", "packageId": "CREC-2001-02-08",
                 "title": "RESIGNATION AS MEMBER OF COMMITTEE ON AGRICULTURE AND COMMITTEE ON RESOURCES"}]

    def fetch_granule(self, package_id, granule_id):
        return MULTI_TEXT, {"granule_id": granule_id, "page": "H228",
                            "url": "https://www.govinfo.gov/app/details/CREC-2001-02-08"}


def test_collect_resignations_fans_out_per_committee():
    committees = CommitteeIndex.from_records(MULTI_COMMITTEE_RECORDS)
    events = collect_resignations(
        congress=107, client=FakeMultiCREC(), start="2001-02-08", end="2001-02-09",
        committees=committees, legislators=None,
    )
    assert len(events) == 2
    assert all(ev.change_type == "removal" for ev in events)
    assert [ev.committee for ev in events] == ["Committee on Agriculture", "Committee on Resources"]
    assert [ev.system_code for ev in events] == ["hsag00", "hsii00"]
    # Signer "Jane Q. Member" does not resolve, and no legislator index is given.
    assert all(ev.bioguide_id is None for ev in events)


MULTI_WORD_SURNAME_RECORDS = [
    {
        "id": {"bioguide": "H001056"},
        "name": {"first": "Jaime", "last": "Herrera Beutler"},
        "terms": [{"type": "rep", "state": "WA", "start": "2011-01-05"}],
    },
]


class FakeMultiWordSurnameCREC:
    def discover_resignations(self, start, end):
        return [{"granuleId": "CREC-2020-01-16-pt1-PgH318-4", "packageId": "CREC-2020-01-16",
                 "title": "RESIGNATION AS MEMBER OF COMMITTEE ON SCIENCE, SPACE, AND TECHNOLOGY"}]

    def fetch_granule(self, package_id, granule_id):
        text = (
            "Washington, DC, January 15, 2020. Hon. Nancy Pelosi, Speaker, "
            "House of Representatives, Washington, DC. Dear Speaker Pelosi: "
            "I write to resign from the Committee on Science, Space, and "
            "Technology.\n"
            "     Sincerely,\n"
            "          Jaime Herrera Beutler,\n"
            "          Member of Congress.\n"
        )
        return text, {"granule_id": granule_id, "page": "H318",
                      "url": "https://www.govinfo.gov/app/details/CREC-2020-01-16"}


def test_collect_resignations_resolves_multi_word_surname():
    # CREC-2020-01-16-pt1-PgH318-4: "Jaime Herrera Beutler" -- her real
    # surname is two words. Naive last-token-only splitting would look up
    # "Beutler" alone and fail to find her in the index.
    legislators = LegislatorIndex.from_records(MULTI_WORD_SURNAME_RECORDS)
    events = collect_resignations(
        congress=116, client=FakeMultiWordSurnameCREC(), start="2020-01-16", end="2020-01-17",
        committees=None, legislators=legislators,
    )
    assert len(events) == 1
    assert events[0].member_name == "Jaime Herrera Beutler"
    assert events[0].bioguide_id == "H001056"


# --- signer-name splitting --------------------------------------------------

from congress_committees.resignations import _clean_signer_name


def test_clean_signer_name_plain():
    assert _clean_signer_name("Charles F. Bass") == "Charles F. Bass"


def test_clean_signer_name_drops_generational_suffix():
    assert _clean_signer_name("Rudy Yakym III") == "Rudy Yakym"
    assert _clean_signer_name("Donald S. Beyer Jr.") == "Donald S. Beyer"
    assert _clean_signer_name("Donald S. Beyer, Jr.") == "Donald S. Beyer"


def test_clean_signer_name_drops_post_nominal_credentials():
    assert _clean_signer_name("Rich McCormick, MD, MBA") == "Rich McCormick"


def test_clean_signer_name_drops_credential_with_no_comma():
    # CREC-2019-03-28-pt1-PgH2900: "Neal P. Dunn M.D." -- no comma before the
    # credential at all, unlike the comma-separated "McCormick, MD, MBA" case.
    assert _clean_signer_name("Neal P. Dunn M.D.") == "Neal P. Dunn"


def test_clean_signer_name_drops_leading_rep_honorific():
    # CREC-2020-01-15-pt1-PgH258-4: signed "Rep. Peter T. King," -- without
    # dropping "Rep.", the surname lookup gets "Rep." as an extra leading
    # token instead of the real first name.
    assert _clean_signer_name("Rep. Peter T. King") == "Peter T. King"


def test_clean_signer_name_drops_leading_congressman_title():
    # CREC-2015-12-08-pt1-PgH9032-6: signed "Congressman Vern Buchanan." --
    # "Congressman"/"Congresswoman" used as a name-line title prefix, same
    # noise category as "Rep."
    assert _clean_signer_name("Congressman Vern Buchanan") == "Vern Buchanan"
    assert _clean_signer_name("Congresswoman Jane Smith") == "Jane Smith"


def test_clean_signer_name_preserves_multi_word_surname():
    # CREC-2020-01-16-pt1-PgH318-4: "Jaime Herrera Beutler" -- her real
    # surname is the two-word "Herrera Beutler". Naively taking only the last
    # whitespace token ("Beutler") breaks the surname lookup; cleaning must
    # leave the full name intact for LegislatorIndex.lookup()'s own
    # multi-word-surname handling to work.
    assert _clean_signer_name("Jaime Herrera Beutler") == "Jaime Herrera Beutler"


def test_clean_signer_name_drops_district_code():
    # CREC-2007-05-16-pt1-PgH5060: signed "Ken Calvert (CA-44)," -- a
    # parenthesized state-district code glued directly to the name, which
    # breaks the surname lookup if left attached (the last "token" becomes
    # "(CA-44)" instead of "Calvert").
    assert _clean_signer_name("Ken Calvert (CA-44)") == "Ken Calvert"


def test_clean_signer_name_empty():
    assert _clean_signer_name(None) == ""
    assert _clean_signer_name("  ") == ""


class FakeNoCommitteeCREC:
    def discover_resignations(self, start, end):
        # A title with no committee tail yields an empty committees list.
        return [{"granuleId": "CREC-2001-02-08-nocmte", "packageId": "CREC-2001-02-08",
                 "title": "RESIGNATION AS MEMBER OF"}]

    def fetch_granule(self, package_id, granule_id):
        return ("No committee named here. Sincerely, Foo Bar, Member of Congress.",
                {"granule_id": granule_id, "page": "H228", "url": None})


def test_collect_resignations_no_committee_fallback():
    events = collect_resignations(
        congress=107, client=FakeNoCommitteeCREC(), start="2001-02-08", end="2001-02-09",
        committees=None, legislators=None,
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.change_type == "removal"
    assert ev.committee == ""
    assert ev.system_code is None


class FakeMultiSignerCREC:
    def discover_resignations(self, start, end):
        # CREC-1994-05-19-pt1-PgH44 (103rd Congress): a real committee
        # resignation notice, but from TWO signers in one granule, followed
        # by unrelated committee-roster content that itself contains another
        # "Without objection" phrase.
        return [{"granuleId": "CREC-1994-05-19-pt1-PgH44", "packageId": "CREC-1994-05-19",
                 "title": "TEMPORARY RESIGNATIONS AS MEMBERS OF COMMITTEE ON SCIENCE, "
                          "SPACE, AND TECHNOLOGY"}]

    def fetch_granule(self, package_id, granule_id):
        text = (
            "House of Representatives, Washington, DC, February 10, 1994.\n"
            "Hon. Thomas S. Foley, The Speaker.\n"
            "Dear Mr. Speaker: I hereby submit my temporary resignation as a "
            "Member of the Committee on Science, Space, and Technology.\n"
            "     Sincerely,\n"
            "          Lynn C. Woolsey.\n"
            "                                  ____\n"
            "House of Representatives, Washington, DC, May 12, 1994.\n"
            "Hon. Thomas S. Foley, Speaker.\n"
            "Dear Mr. Speaker: I hereby submit my temporary resignation as a "
            "member of the Committee on Science, Space and Technology.\n"
            "     Sincerely,\n"
            "          Glen Browder.\n"
            "\n"
            "  The SPEAKER pro tempore. Without objection, the resignations "
            "are accepted.\n"
            "  There was no objection.\n"
            "\n"
            "                announcement by the speaker pro tempore\n"
            "\n"
            "  The SPEAKER pro tempore. Without objection, the Democratic "
            "membership is revised for the following listed committees.\n"
        )
        return text, {"granule_id": granule_id, "page": "H44",
                      "url": "https://www.govinfo.gov/app/details/CREC-1994-05-19"}


def test_collect_resignations_skips_multi_signer_granule_instead_of_guessing(caplog):
    # A granule whose title says "RESIGNATIONS AS MEMBERS" (plural) holds
    # more than one signer's letter, a shape the single-signer extractor
    # isn't built for -- attempting it anyway previously produced a WRONG,
    # non-empty "member_name" ("announcement by the speaker pro tempore",
    # a section heading from the unrelated trailing content) rather than
    # correctly recognizing it couldn't confidently parse this granule.
    # Skipping it (with a warning) is strictly better than emitting bad data.
    events = collect_resignations(
        congress=103, client=FakeMultiSignerCREC(), start="1994-05-19", end="1994-05-20",
        committees=None, legislators=None,
    )
    assert events == []
