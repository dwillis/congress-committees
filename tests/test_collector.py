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


def test_agreed_to_date_disambiguates_member():
    # "Mr. Foster" is an ambiguous surname; the resolution's agreed-to date
    # (2025) picks the Foster who was actually serving then.
    xml = (
        '<?xml version="1.0"?>'
        '<resolution resolution-stage="Engrossed-in-House">'
        "<title>119 HRES 99 EH: Electing a Member</title>"
        "<official-title>Electing a Member to a committee.</official-title>"
        "<resolution-body><committee-appointment-paragraph><header>"
        '<committee-name committee-id="HSY00">Committee on Science</committee-name>:'
        "</header><text> Mr. Foster. </text>"
        "</committee-appointment-paragraph></resolution-body></resolution>"
    )
    dated_actions = parse_actions(
        {"actions": [{"actionDate": "2025-01-09",
                      "text": "On agreeing to the resolution Agreed to without objection.",
                      "type": "Floor"}]}
    )

    class FosterClient(FakeClient):
        def list_committee_change_resolutions(self, congress, since=None):
            return [{"congress": 119, "type": "HRES", "number": "99", "title": "Electing..."}]

        def get_actions(self, congress, number):
            return dated_actions

    legislators = LegislatorIndex.from_records([
        {"id": {"bioguide": "F000001"}, "name": {"first": "Bill", "last": "Foster"},
         "terms": [{"type": "rep", "state": "IL", "start": "2008-03-08"}]},
        {"id": {"bioguide": "F000002"}, "name": {"first": "Ezra", "last": "Foster"},
         "terms": [{"type": "rep", "state": "NY", "start": "1899-01-01", "end": "1905-01-01"}]},
    ])
    records = collect_committee_changes(
        119,
        client=FosterClient(),
        gpo_fetch=lambda c, n, **k: (xml.encode(), "BILLS-119hres99eh", "eh"),
        legislators=legislators,
    )
    assert [c.bioguide_id for c in records[0].committee_changes] == ["F000001"]


def test_falls_back_to_text_when_no_xml_available():
    # Congresses before the 110th have no XML rendition on GovInfo at all --
    # gpo_fetch (XML) correctly returns None, and collection should fall back
    # to the plain-text rendition instead of just warning and skipping.
    text = (
        "In the House of Representatives, U.S., January 4, 2005.\n"
        "Resolved, That the following Members be, and are hereby, elected to "
        "the following standing committee of the House of Representatives:\n"
        "Committee on Rules: Mr. Dreier, Chairman; Mr. Hastings of "
        "Washington.\n"
        "Attest:\n"
        "Clerk.\n"
    )

    class OldCongressClient(FakeClient):
        def list_committee_change_resolutions(self, congress, since=None):
            return [{
                "congress": 109, "type": "HRES", "number": "6",
                "title": "Electing Members to certain standing committees of the House.",
            }]

    legislators = LegislatorIndex.from_records([
        {"id": {"bioguide": "D000355"}, "name": {"first": "David", "last": "Dreier"},
         "terms": [{"type": "rep", "state": "CA", "start": "1981-01-05"}]},
    ])
    records = collect_committee_changes(
        109,
        client=OldCongressClient(),
        gpo_fetch=lambda c, n, **k: None,
        gpo_fetch_text=lambda c, n, **k: (text, "BILLS-109hres6eh", "eh"),
        legislators=legislators,
    )
    assert len(records) == 1
    record = records[0]
    assert record.number == "6"
    assert [c.member_name for c in record.committee_changes] == [
        "Mr. Dreier", "Mr. Hastings of Washington",
    ]
    assert record.committee_changes[0].bioguide_id == "D000355"
    assert all(c.change_type == "addition" for c in record.committee_changes)


def test_warns_and_skips_when_neither_xml_nor_text_available():
    class NoRenditionClient(FakeClient):
        def list_committee_change_resolutions(self, congress, since=None):
            return [{"congress": 109, "type": "HRES", "number": "999", "title": "Electing..."}]

    records = collect_committee_changes(
        109,
        client=NoRenditionClient(),
        gpo_fetch=lambda c, n, **k: None,
        gpo_fetch_text=lambda c, n, **k: None,
    )
    assert records == []


def test_skips_resolution_never_agreed_to():
    # H.Res.1113 (119th Congress), "Censuring Representative Andrew Ogles and
    # Removing Him from the House Committee on Homeland Security" -- merely
    # referred to the Ethics Committee, never brought to a vote, but its
    # title alone matches the removal pattern and GovInfo has an "ih"
    # (introduced) rendition, which was enough to fabricate a real removal
    # event. Nothing has actually happened to Ogles's committee membership
    # unless/until the House agrees to it.
    xml = (
        '<?xml version="1.0"?>'
        '<resolution resolution-stage="Introduced-in-House">'
        "<title>119 HRES 1113 IH: Censuring Representative Andrew Ogles and "
        "Removing Him from the House Committee on Homeland Security.</title>"
        "<official-title>Censuring Representative Andrew Ogles and Removing "
        "Him from the House Committee on Homeland Security.</official-title>"
        "<resolution-body><committee-appointment-paragraph><header>"
        '<committee-name committee-id="HSHM00">Committee on Homeland Security</committee-name>:'
        "</header><text> Mr. Ogles. </text>"
        "</committee-appointment-paragraph></resolution-body></resolution>"
    )
    not_agreed_actions = parse_actions(
        {"actions": [{"actionDate": "2026-03-12", "text": "Referred to the House Committee on Ethics.",
                      "type": "IntroReferral"}]}
    )

    class NotAgreedClient(FakeClient):
        def list_committee_change_resolutions(self, congress, since=None):
            return [{
                "congress": 119, "type": "HRES", "number": "1113",
                "title": "Censuring Representative Andrew Ogles and Removing "
                "Him from the House Committee on Homeland Security.",
            }]

        def get_actions(self, congress, number):
            return not_agreed_actions

    records = collect_committee_changes(
        119,
        client=NotAgreedClient(),
        gpo_fetch=lambda c, n, **k: (xml.encode(), "BILLS-119hres1113ih", "ih"),
        legislators=LegislatorIndex.from_yaml_files([FIXTURES / "legislators-sample.yaml"]),
    )
    assert records == []


def test_collect_emits_unified_events():
    from congress_committees.collector import collect_committee_change_events
    events = collect_committee_change_events(
        119, client=FakeClient(), gpo_fetch=fake_gpo_fetch,
        legislators=LegislatorIndex.from_yaml_files([FIXTURES / "legislators-sample.yaml"]),
    )
    assert all(e.source == "resolution" for e in events)
    assert {e.change_type for e in events} == {"addition"}
    assert any(e.gpo_code for e in events)
