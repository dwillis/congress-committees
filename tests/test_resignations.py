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
