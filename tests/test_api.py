"""Tests for the congress.gov client: discovery filtering, actions parsing, wiring."""

import json

import httpx
import pytest

from congress_committees.api import (
    CongressGovClient,
    extract_agreed_to_date,
    filter_committee_change_bills,
    parse_actions,
)

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


def test_get_actions_parses(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ACTIONS)

    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    actions = client.get_actions(119, "1381")
    assert extract_agreed_to_date(actions) == "2026-06-24"
