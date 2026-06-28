"""Tests for the unified committee-change-event output model."""

from congress_committees.models import (
    CommitteeChange,
    CommitteeChangeEvent,
    RecordRef,
    ResolutionRecord,
    ResolutionRef,
    to_events,
)


def test_committee_change_event_round_trips():
    event = CommitteeChangeEvent(
        congress="107",
        change_type="removal",
        committee="House Permanent Select Committee on Intelligence",
        member_name="Charles F. Bass",
        source="congressional_record",
        date="2001-02-08",
        source_ref=RecordRef(
            volume="147", issue="18", page="H228",
            granule_id="CREC-2001-02-08-pt1-PgH228", signed_date="2001-02-07",
            url="https://www.govinfo.gov/app/details/CREC-2001-02-08",
        ),
    )
    dumped = event.model_dump()
    assert dumped["source_ref"]["type"] == "congressional_record"
    assert dumped["system_code"] is None and dumped["gpo_code"] is None


def test_to_events_flattens_resolution_record():
    record = ResolutionRecord(
        congress="119", type="HRES", number="1381",
        title="Electing a Member...", stage="Engrossed-in-House",
        date="2026-06-24", govinfo_xml_url="http://x/BILLS.xml",
        congress_gov_url="http://c/1381", agreed_to_date="2026-06-24",
        committee_changes=[
            CommitteeChange(change_type="addition", committee="Committee on Foreign Affairs",
                            committee_code="HFA00", member_name="Mr. Gallagher",
                            bioguide_id="G000587"),
        ],
    )
    events = to_events(record)
    assert len(events) == 1
    ev = events[0]
    assert ev.change_type == "addition"
    assert ev.source == "resolution"
    assert ev.gpo_code == "HFA00"          # native from XML
    assert ev.system_code is None           # filled later, best-effort
    assert ev.member_name == "Mr. Gallagher"
    assert ev.bioguide_id == "G000587"
    assert ev.source_ref.type == "resolution"
    assert ev.source_ref.number == "1381"
    assert ev.source_ref.agreed_to_date == "2026-06-24"
