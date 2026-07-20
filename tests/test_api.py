"""Tests for the congress.gov client: discovery filtering, actions parsing, wiring."""

import json

import httpx
import pytest

from congress_committees.api import (
    CongressGovClient,
    extract_agreed_to_date,
    filter_committee_change_bills,
    filter_senate_committee_change_bills,
    parse_actions,
)

SENATE_BILL_LIST = {
    "bills": [
        {
            "congress": 119,
            "type": "SRES",
            "number": "16",
            "title": "To constitute the majority party's membership on certain "
            "committees for the One Hundred Nineteenth Congress, or until "
            "their successors are chosen.",
        },
        {
            "congress": 119,
            "type": "SRES",
            "number": "9",
            "title": "A resolution to authorize expenditures by committees of "
            "the Senate for the One Hundred Nineteenth Congress.",
        },
    ]
}

BILL_LIST = {
    "bills": [
        {
            "congress": 119,
            "type": "HRES",
            "number": "1381",
            "title": "Electing a Member to certain standing committees of the House of Representatives.",
            "latestAction": {"actionDate": "2026-06-24", "text": "Agreed to."},
        },
        {
            "congress": 119,
            "type": "HRES",
            "number": "1300",
            "title": "Providing for consideration of the bill (H.R. 9) ...",
            "latestAction": {"actionDate": "2026-06-20", "text": "Agreed to."},
        },
    ]
}

ACTIONS = {
    "actions": [
        {
            "actionDate": "2026-06-24",
            "text": "On agreeing to the resolution Agreed to without objection.",
            "type": "Floor",
        },
        {"actionDate": "2026-06-24", "text": "Considered by unanimous consent.", "type": "Floor"},
    ]
}

COMMITTEES = {
    "committees": [
        {"systemCode": "hsfa00", "name": "Foreign Affairs Committee", "chamber": "House"},
        {"systemCode": "hsii00", "name": "Natural Resources Committee", "chamber": "House"},
    ]
}


def test_filter_keeps_only_committee_change_resolutions():
    kept = filter_committee_change_bills(BILL_LIST)
    assert [b["number"] for b in kept] == ["1381"]


def test_parse_actions_maps_fields():
    actions = parse_actions(ACTIONS)
    assert len(actions) == 2
    assert actions[0].date == "2026-06-24"
    assert actions[0].type == "Floor"


def test_extract_agreed_to_date_finds_agreement():
    assert extract_agreed_to_date(parse_actions(ACTIONS)) == "2026-06-24"


def test_extract_agreed_to_date_none_when_no_agreement():
    actions = parse_actions({"actions": [{"actionDate": "2026-06-24", "text": "Referred."}]})
    assert extract_agreed_to_date(actions) is None


def test_from_env_requires_api_key(monkeypatch):
    monkeypatch.delenv("CONGRESS_GOV_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        CongressGovClient.from_env()


def test_list_hres_sends_key_and_parses(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=BILL_LIST)

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    bills = client.list_committee_change_resolutions(119)

    assert "api_key=SECRET" in captured["url"]
    assert "/bill/119/hres" in captured["url"]
    assert [b["number"] for b in bills] == ["1381"]


def test_list_committee_change_resolutions_follows_pagination():
    # A committee-change resolution that hasn't had a recent action (e.g. it was
    # agreed to months ago and never touched again) can sit past the first page
    # when a Congress has more HRES bills than the page size. Without pagination
    # it's silently dropped even though it matches the title filter.
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json={
                "bills": [
                    {
                        "number": "1400",
                        "title": "Providing for consideration of the bill (H.R. 9) ...",
                    },
                ],
                "pagination": {"count": 2, "next": "https://api.congress.gov/v3/bill/119/hres?offset=250"},
            })
        return httpx.Response(200, json={
            "bills": [
                {
                    "number": "979",
                    "title": "Electing a Member to a certain standing committee of the House of Representatives.",
                },
            ],
            "pagination": {"count": 2},
        })

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    bills = client.list_committee_change_resolutions(119)

    assert len(calls) == 2  # a second page request fired
    assert [b["number"] for b in bills] == ["979"]


def test_filter_senate_keeps_only_committee_change_resolutions():
    kept = filter_senate_committee_change_bills(SENATE_BILL_LIST)
    assert [b["number"] for b in kept] == ["16"]


def test_list_sres_sends_key_and_parses(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=SENATE_BILL_LIST)

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    bills = client.list_committee_change_resolutions(119, bill_type="sres")

    assert "api_key=SECRET" in captured["url"]
    assert "/bill/119/sres" in captured["url"]
    assert [b["number"] for b in bills] == ["16"]


def test_get_actions_senate_uses_sres_path(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=ACTIONS)

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    actions = client.get_actions(119, "16", bill_type="sres")

    assert "/bill/119/sres/16/actions" in captured["url"]
    assert extract_agreed_to_date(actions) == "2026-06-24"


def test_get_actions_parses(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ACTIONS)

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    actions = client.get_actions(119, "1381")
    assert extract_agreed_to_date(actions) == "2026-06-24"


def test_list_committees_parses():
    def handler(request):
        assert "/committee/house" in str(request.url)
        return httpx.Response(200, json=COMMITTEES)
    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    recs = client.list_committees("house")
    assert {r["systemCode"] for r in recs} == {"hsfa00", "hsii00"}


def test_list_committees_follows_pagination():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json={
                "committees": [
                    {"systemCode": "hsfa00", "name": "Foreign Affairs Committee"},
                    {"systemCode": "hsii00", "name": "Natural Resources Committee"},
                ],
                "pagination": {"count": 4, "next": "https://api.congress.gov/v3/committee/house?offset=2"},
            })
        return httpx.Response(200, json={
            "committees": [
                {"systemCode": "hsju00", "name": "Judiciary Committee"},
                {"systemCode": "hsgo00", "name": "Oversight Committee"},
            ],
            "pagination": {"count": 4},
        })

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    recs = client.list_committees("house")
    assert len(calls) == 2  # a second page request fired
    assert {r["systemCode"] for r in recs} == {"hsfa00", "hsii00", "hsju00", "hsgo00"}


def test_get_committee_returns_committee_dict():
    detail = {"committee": {"systemCode": "hsii00", "isCurrent": True,
                            "history": [{"officialName": "Committee on Resources"}]}}

    def handler(request):
        assert "/committee/house/hsii00" in str(request.url)
        return httpx.Response(200, json=detail)

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    com = client.get_committee("hsii00", "house")
    assert com["systemCode"] == "hsii00"
    assert com["history"][0]["officialName"] == "Committee on Resources"
