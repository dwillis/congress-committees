from congress_committees.cli import _merge_bioguide_ids, build_parser
from congress_committees.models import CommitteeChangeEvent, RecordRef, ResolutionRef


def test_source_flag_defaults_to_all():
    args = build_parser().parse_args(["--congress", "119"])
    assert args.source == "all"


def test_source_flag_accepts_record():
    args = build_parser().parse_args(["--congress", "119", "--source", "record"])
    assert args.source == "record"


def test_no_committee_codes_flag():
    args = build_parser().parse_args(["--congress", "119", "--no-committee-codes"])
    assert args.no_committee_codes is True


# --- carrying a manually-set bioguide_id forward across a re-run -----------


def _resolution_event(member_name, bioguide_id=None, number="25"):
    return CommitteeChangeEvent(
        congress="107",
        change_type="addition",
        committee="Committee on Financial Services",
        member_name=member_name,
        bioguide_id=bioguide_id,
        date="2001-01-31",
        source="resolution",
        source_ref=ResolutionRef(number=number, agreed_to_date="2001-01-31"),
    )


def test_merge_fills_in_a_hand_corrected_bioguide_id():
    # tools/review_server.py is how a source-document typo like "Guiterrez"
    # (which the automated lookup deliberately won't guess at) gets a
    # bioguide_id by hand. Re-running the CLI recomputes everything from
    # scratch and would otherwise silently wipe that correction out.
    old_raw = [_resolution_event("Mr. Guiterrez of Illinois", "G000535").model_dump()]
    new_events = [_resolution_event("Mr. Guiterrez of Illinois", None)]

    filled = _merge_bioguide_ids(old_raw, new_events)

    assert filled == 1
    assert new_events[0].bioguide_id == "G000535"


def test_merge_does_not_overwrite_a_freshly_resolved_bioguide_id():
    # If the automated lookup itself now resolves the member (e.g. a real
    # code fix), that fresh result must win, not a stale old one.
    old_raw = [_resolution_event("Mr. Gallagher", "OLDVALUE").model_dump()]
    new_events = [_resolution_event("Mr. Gallagher", "G000587")]

    filled = _merge_bioguide_ids(old_raw, new_events)

    assert filled == 0
    assert new_events[0].bioguide_id == "G000587"


def test_merge_requires_the_same_source_document_and_member():
    # A same-named member in a DIFFERENT resolution is a different event --
    # an old bioguide_id must not leak across unrelated entries.
    old_raw = [_resolution_event("Mr. Guiterrez of Illinois", "G000535", number="25").model_dump()]
    new_events = [_resolution_event("Mr. Guiterrez of Illinois", None, number="99")]

    filled = _merge_bioguide_ids(old_raw, new_events)

    assert filled == 0
    assert new_events[0].bioguide_id is None


def test_merge_handles_congressional_record_events_by_granule_id():
    old_raw = [
        CommitteeChangeEvent(
            congress="107",
            change_type="removal",
            committee="Committee on International Relations",
            member_name="Chris Bell",
            bioguide_id="B001243",
            date="2004-03-25",
            source="congressional_record",
            source_ref=RecordRef(granule_id="CREC-2004-03-25-pt1-PgH1566-3"),
        ).model_dump()
    ]
    new_events = [
        CommitteeChangeEvent(
            congress="107",
            change_type="removal",
            committee="Committee on International Relations",
            member_name="Chris Bell",
            bioguide_id=None,
            date="2004-03-25",
            source="congressional_record",
            source_ref=RecordRef(granule_id="CREC-2004-03-25-pt1-PgH1566-3"),
        )
    ]

    filled = _merge_bioguide_ids(old_raw, new_events)

    assert filled == 1
    assert new_events[0].bioguide_id == "B001243"
