"""End-to-end orchestration test with injected fakes (no network)."""

from pathlib import Path

from congress_committees.api import parse_actions
from congress_committees.collector import collect_committee_changes
from congress_committees.legislators import LegislatorIndex

FIXTURES = Path(__file__).parent / "fixtures"
XML = (FIXTURES / "BILLS-119hres1381eh.xml").read_bytes()

ACTIONS = parse_actions(
    {
        "actions": [
            {
                "actionDate": "2026-06-24",
                "text": "On agreeing to the resolution Agreed to without objection.",
                "type": "Floor",
            }
        ]
    }
)


class FakeClient:
    def list_committee_change_resolutions(self, congress, since=None):
        return [{"congress": 119, "type": "HRES", "number": "1381", "title": "Electing..."}]

    def get_actions(self, congress, number):
        return ACTIONS


def fake_gpo_fetch(congress, number, **kwargs):
    return XML, "BILLS-119hres1381eh", "eh"


def collect():
    legislators = LegislatorIndex.from_yaml_files([FIXTURES / "legislators-sample.yaml"])
    return collect_committee_changes(
        119, client=FakeClient(), gpo_fetch=fake_gpo_fetch, legislators=legislators
    )


def test_returns_one_resolution_record():
    records = collect()
    assert len(records) == 1
    assert records[0].number == "1381"


def test_record_has_actions_and_agreed_to_date():
    record = collect()[0]
    assert record.agreed_to_date == "2026-06-24"
    assert len(record.actions) == 1


def test_record_has_source_urls():
    record = collect()[0]
    assert record.govinfo_xml_url.endswith("BILLS-119hres1381eh.xml")
    assert record.congress_gov_url == (
        "https://www.congress.gov/bill/119th-congress/house-resolution/1381"
    )


def test_member_bioguide_resolved():
    record = collect()[0]
    assert {c.bioguide_id for c in record.committee_changes} == {"G000587"}


def test_multi_member_paragraph_resolves_each_bioguide():
    # A paragraph naming several members explodes into one change per member,
    # each resolved to its own bioguide (state disambiguates the two Smiths).
    multi_xml = (
        '<?xml version="1.0"?>'
        '<resolution resolution-stage="Engrossed-in-House">'
        "<title>119 HRES 22 EH: Electing Members</title>"
        "<official-title>Electing Members to committees.</official-title>"
        "<resolution-body><committee-appointment-paragraph><header>"
        '<committee-name committee-id="HAP00">Committee on Appropriations</committee-name>:'
        "</header><text> Mr. Gallagher, Mr. Smith of Missouri, Ms. Smith of Washington. </text>"
        "</committee-appointment-paragraph></resolution-body></resolution>"
    )

    class MultiClient(FakeClient):
        def list_committee_change_resolutions(self, congress, since=None):
            return [{"congress": 119, "type": "HRES", "number": "22", "title": "Electing..."}]

    legislators = LegislatorIndex.from_yaml_files([FIXTURES / "legislators-sample.yaml"])
    records = collect_committee_changes(
        119,
        client=MultiClient(),
        gpo_fetch=lambda c, n, **k: (multi_xml.encode(), "BILLS-119hres22eh", "eh"),
        legislators=legislators,
    )
    changes = records[0].committee_changes
    assert {(c.member_name, c.bioguide_id) for c in changes} == {
        ("Mr. Gallagher", "G000587"),
        ("Mr. Smith of Missouri", "S001195"),
        ("Ms. Smith of Washington", "S000510"),
    }


def test_collect_emits_unified_events():
    from congress_committees.collector import collect_committee_change_events
    events = collect_committee_change_events(
        119, client=FakeClient(), gpo_fetch=fake_gpo_fetch,
        legislators=LegislatorIndex.from_yaml_files([FIXTURES / "legislators-sample.yaml"]),
    )
    assert all(e.source == "resolution" for e in events)
    assert {e.change_type for e in events} == {"addition"}
    assert any(e.gpo_code for e in events)
