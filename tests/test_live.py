"""Live integration tests against the real congress.gov API and GPO govinfo.

Unlike the rest of the suite (which is offline via httpx.MockTransport and
fixtures), these hit the network. They are gated two ways:

* marked ``live`` so the default ``pytest`` run skips them — run with
  ``pytest -m live``;
* skipped entirely when ``CONGRESS_GOV_API_KEY`` is not set, so they are a
  no-op in CI / offline environments.

The subject is H. Res. 1381 (119th Congress), "Electing a Member to certain
standing committees of the House of Representatives." — a real committee
assignment resolution whose engrossed text and actions are public.
"""

import os

import pytest

from congress_committees.api import CongressGovClient, extract_agreed_to_date
from congress_committees.collector import collect_committee_changes
from congress_committees.parser import classify_title

pytestmark = pytest.mark.live

CONGRESS = 119
HRES_NUMBER = "1381"
HRES_TITLE = (
    "Electing a Member to certain standing committees "
    "of the House of Representatives."
)
# Committee system codes published in BILLS-119hres1381eh.xml (see fixtures).
EXPECTED_COMMITTEE_CODES = {"HFA00", "HJU00", "HGO00"}

requires_key = pytest.mark.skipif(
    not os.environ.get("CONGRESS_GOV_API_KEY"),
    reason="CONGRESS_GOV_API_KEY not set; skipping live congress.gov tests",
)


@pytest.fixture
def client():
    return CongressGovClient.from_env()


class _SingleResolutionClient:
    """Restrict discovery to one known resolution, delegating actions to a real client.

    Lets us drive the full collector end-to-end against a single committee
    assignment resolution without depending on it appearing in the live,
    most-recently-updated discovery window.
    """

    def __init__(self, real, congress, number, title):
        self._real = real
        self._bill = {
            "congress": congress,
            "type": "HRES",
            "number": number,
            "title": title,
        }

    def list_committee_change_resolutions(self, congress, since=None):
        return [self._bill]

    def get_actions(self, congress, number):
        return self._real.get_actions(congress, number)


@requires_key
def test_live_discovery_returns_committee_change_resolutions(client):
    bills = client.list_committee_change_resolutions(CONGRESS)
    assert bills, "expected at least one committee-change HRES for the 119th Congress"
    # Every bill the client returns must classify as a committee change.
    assert all(classify_title(b.get("title", ""))[0] for b in bills)


@requires_key
def test_live_actions_yield_agreed_to_date(client):
    actions = client.get_actions(CONGRESS, HRES_NUMBER)
    assert actions, "expected actions for H. Res. 1381"
    assert extract_agreed_to_date(actions) is not None


@requires_key
def test_live_end_to_end_committee_assignment(client):
    """Full pipeline for one assignment resolution: live API actions + live GPO XML."""
    records = collect_committee_changes(
        CONGRESS,
        client=_SingleResolutionClient(client, CONGRESS, HRES_NUMBER, HRES_TITLE),
    )

    assert len(records) == 1
    record = records[0]
    assert record.number == HRES_NUMBER
    assert record.type == "HRES"

    # Source URLs wired up from the live fetch.
    assert record.govinfo_xml_url.endswith("BILLS-119hres1381eh.xml")
    assert record.congress_gov_url.endswith("/house-resolution/1381")

    # Actions came from the live congress.gov API.
    assert record.actions
    assert record.agreed_to_date is not None

    # Committee changes (and their codes) came from the live GPO bill XML.
    codes = {c.committee_code for c in record.committee_changes}
    assert codes == EXPECTED_COMMITTEE_CODES
    assert all(c.member_name for c in record.committee_changes)
    assert {c.change_type for c in record.committee_changes} == {"addition"}


@requires_key
def test_live_committees_index_resolves_foreign_affairs(client):
    from congress_committees.committees import CommitteeIndex
    idx = CommitteeIndex.from_records(client.list_committees("house"))
    assert idx.code_for("Committee on Foreign Affairs") == "hsfa00"


@requires_key
def test_live_crec_finds_bass_intelligence_resignation():
    from congress_committees.congressional_record import CRECClient
    from congress_committees.parser import parse_resignation_granule
    crec = CRECClient.from_env()
    granules = crec.discover_resignations("2001-02-08", "2001-02-09")
    intel = [g for g in granules if "INTELLIGENCE" in g["title"].upper()]
    assert intel, "expected the Feb 8 2001 Intelligence resignation"
    text, meta = crec.fetch_granule(intel[0]["packageId"], intel[0]["granuleId"])
    parsed = parse_resignation_granule(intel[0]["title"], text)
    assert parsed.member_name == "Charles F. Bass"
    assert meta["page"] == "H228"
