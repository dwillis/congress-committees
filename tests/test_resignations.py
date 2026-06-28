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
