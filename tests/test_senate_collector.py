"""End-to-end orchestration test for the Senate roster-diffing pipeline
(injected fakes, no network)."""

from congress_committees.api import parse_actions
from congress_committees.legislators import LegislatorIndex
from congress_committees.senate_collector import (
    collect_senate_committee_change_events,
    collect_senate_committee_changes,
)

MAJORITY_TITLE = (
    "To constitute the majority party's membership on certain committees for "
    "the One Hundred Nineteenth Congress, or until their successors are chosen."
)

XML_TEMPLATE = (
    '<?xml version="1.0"?>'
    '<resolution resolution-type="senate-resolution" resolution-stage="Agreed-to-Senate">'
    "<form><official-title>{title}</official-title></form>"
    "<resolution-body><section><text>That the following shall constitute the "
    "majority party's membership...:</text>{paragraphs}</section></resolution-body>"
    "</resolution>"
)


def _para(committee, members, code=None):
    name_tag = f'<committee-name committee-id="{code}">{committee}:</committee-name>' if code else f"{committee}:"
    return (
        "<committee-appointment-paragraph><header>"
        f"{name_tag}"
        f"</header><text>{members}</text></committee-appointment-paragraph>"
    )


def _actions(date):
    return parse_actions(
        {
            "actions": [
                {
                    "actionDate": date,
                    "text": "Submitted in the Senate, considered, and agreed to.",
                    "type": "Floor",
                }
            ]
        }
    )


LEGISLATORS = LegislatorIndex.from_records(
    [
        {
            "id": {"bioguide": "M000934"},
            "name": {"first": "Jerry", "last": "Moran"},
            "terms": [{"type": "sen", "state": "KS", "start": "2011-01-05"}],
        },
        {
            "id": {"bioguide": "H001304"},
            "name": {"first": "Jon", "last": "Husted"},
            "terms": [{"type": "sen", "state": "OH", "start": "2025-01-21"}],
        },
        {
            "id": {"bioguide": "B001236"},
            "name": {"first": "Roger", "last": "Boozman"},
            "terms": [{"type": "sen", "state": "AR", "start": "2011-01-05"}],
        },
    ],
    chamber="senate",
)


class FakeClient:
    def __init__(self, bills, actions_by_number):
        self._bills = bills
        self._actions = actions_by_number

    def list_committee_change_resolutions(self, congress, since=None, bill_type="sres"):
        return self._bills

    def get_actions(self, congress, number, bill_type="sres"):
        return self._actions[number]


def test_first_resolution_yields_only_additions():
    xml = XML_TEMPLATE.format(
        title=MAJORITY_TITLE,
        paragraphs=_para(
            "Committee on Agriculture, Nutrition, and Forestry",
            "Mr. Boozman (Chair), Mr. Moran.",
            code="SSAF00",
        ),
    )
    client = FakeClient(
        bills=[{"number": "16", "title": MAJORITY_TITLE}],
        actions_by_number={"16": _actions("2025-01-07")},
    )
    records = collect_senate_committee_changes(
        119,
        client=client,
        gpo_fetch=lambda c, n, **k: (xml.encode(), "BILLS-119sres16ats", "ats"),
        legislators=LEGISLATORS,
    )
    assert len(records) == 1
    record = records[0]
    assert record.chamber == "senate"
    assert record.type == "SRES"
    assert record.congress_gov_url == "https://www.congress.gov/bill/119th-congress/senate-resolution/16"
    assert {(c.member_name, c.change_type, c.bioguide_id) for c in record.committee_changes} == {
        ("Mr. Boozman", "addition", "B001236"),
        ("Mr. Moran", "addition", "M000934"),
    }


def test_second_resolution_diffs_against_first_to_find_swap():
    # Mirrors the real 119th Congress S.Res.16 -> S.Res.38 finding: Moran
    # disappears from a committee's roster as Husted's name takes his slot.
    xml16 = XML_TEMPLATE.format(
        title=MAJORITY_TITLE,
        paragraphs=_para(
            "Committee on Agriculture, Nutrition, and Forestry",
            "Mr. Boozman (Chair), Mr. Moran.",
            code="SSAF00",
        ),
    )
    xml38 = XML_TEMPLATE.format(
        title=MAJORITY_TITLE,
        paragraphs=_para(
            "Committee on Agriculture, Nutrition, and Forestry",
            "Mr. Boozman (Chair), Mr. Husted.",
            code="SSAF00",
        ),
    )
    xml_by_number = {"16": xml16, "38": xml38}

    client = FakeClient(
        bills=[
            {"number": "16", "title": MAJORITY_TITLE},
            {"number": "38", "title": MAJORITY_TITLE},
        ],
        actions_by_number={"16": _actions("2025-01-07"), "38": _actions("2025-01-24")},
    )
    records = collect_senate_committee_changes(
        119,
        client=client,
        gpo_fetch=lambda c, n, **k: (xml_by_number[n].encode(), f"BILLS-119sres{n}ats", "ats"),
        legislators=LEGISLATORS,
    )
    assert [r.number for r in records] == ["16", "38"]

    second = records[1].committee_changes
    assert {(c.member_name, c.change_type) for c in second} == {
        ("Mr. Moran", "removal"),
        ("Mr. Husted", "addition"),
    }
    # Boozman appears in both rosters unchanged -- must NOT show up as churn.
    assert not any(c.member_name == "Mr. Boozman" for c in second)


def test_resolutions_are_diffed_in_chronological_order_not_api_order():
    # The API lists bills newest-activity-first; feed them in THAT (reversed)
    # order and confirm the collector still diffs oldest-to-newest.
    xml16 = XML_TEMPLATE.format(
        title=MAJORITY_TITLE,
        paragraphs=_para("Committee on Agriculture, Nutrition, and Forestry", "Mr. Moran."),
    )
    xml38 = XML_TEMPLATE.format(
        title=MAJORITY_TITLE,
        paragraphs=_para("Committee on Agriculture, Nutrition, and Forestry", "Mr. Husted."),
    )
    xml_by_number = {"16": xml16, "38": xml38}

    client = FakeClient(
        bills=[
            {"number": "38", "title": MAJORITY_TITLE},  # newest first, as the API returns
            {"number": "16", "title": MAJORITY_TITLE},
        ],
        actions_by_number={"16": _actions("2025-01-07"), "38": _actions("2025-01-24")},
    )
    records = collect_senate_committee_changes(
        119,
        client=client,
        gpo_fetch=lambda c, n, **k: (xml_by_number[n].encode(), f"BILLS-119sres{n}ats", "ats"),
        legislators=LEGISLATORS,
    )
    assert [r.number for r in records] == ["16", "38"]
    assert [c.change_type for c in records[0].committee_changes] == ["addition"]
    assert {(c.member_name, c.change_type) for c in records[1].committee_changes} == {
        ("Mr. Moran", "removal"),
        ("Mr. Husted", "addition"),
    }


def test_party_agnostic_title_is_skipped():
    client = FakeClient(
        bills=[
            {
                "number": "136",
                "title": "To make appointments to the Committee on Environment and Public Works.",
            }
        ],
        actions_by_number={"136": _actions("1991-06-04")},
    )
    records = collect_senate_committee_changes(
        119, client=client, gpo_fetch=lambda c, n, **k: None, gpo_fetch_text=lambda c, n, **k: None,
    )
    assert records == []


def test_single_add_schema_emits_direct_addition():
    text = (
        "<pre>S. RES. 137\nResolved, That the following Senator shall be "
        "added to the minority party's membership on the Senate Committee on "
        "Banking, Housing, and Urban Affairs for the One Hundred Second "
        "Congress until November 6, 1991: Mr. Moran.</pre>"
    )
    client = FakeClient(
        bills=[
            {
                "number": "137",
                "title": "A resolution to make a minority party appointment to the "
                "Committee on Banking, Housing, and Urban Affairs.",
            }
        ],
        actions_by_number={"137": _actions("1991-06-04")},
    )
    records = collect_senate_committee_changes(
        102,
        client=client,
        gpo_fetch=lambda c, n, **k: None,
        gpo_fetch_text=lambda c, n, **k: (text, "BILLS-102sres137ats", "ats"),
        legislators=LEGISLATORS,
    )
    assert len(records) == 1
    changes = records[0].committee_changes
    assert len(changes) == 1
    assert changes[0].change_type == "addition"
    assert changes[0].member_name == "Mr. Moran"
    assert changes[0].bioguide_id == "M000934"
    assert changes[0].committee == "Committee on Banking, Housing, and Urban Affairs"


def test_collect_senate_committee_change_events_flattens_and_tags_chamber():
    xml = XML_TEMPLATE.format(
        title=MAJORITY_TITLE,
        paragraphs=_para("Committee on Agriculture, Nutrition, and Forestry", "Mr. Moran."),
    )
    client = FakeClient(
        bills=[{"number": "16", "title": MAJORITY_TITLE}],
        actions_by_number={"16": _actions("2025-01-07")},
    )
    events = collect_senate_committee_change_events(
        119,
        client=client,
        gpo_fetch=lambda c, n, **k: (xml.encode(), "BILLS-119sres16ats", "ats"),
        legislators=LEGISLATORS,
    )
    assert len(events) == 1
    assert events[0].chamber == "senate"
    assert events[0].source == "resolution"
    assert events[0].date == "2025-01-07"
