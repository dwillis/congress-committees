"""Tests for the GovInfo CREC client (discovery + granule fetch) via MockTransport."""

import httpx

from congress_committees.congressional_record import CRECClient

COLLECTIONS = {"packages": [{"packageId": "CREC-2001-02-08", "dateIssued": "2001-02-08"}],
               "nextPage": None}
GRANULES = {"granules": [
    {"granuleId": "CREC-2001-02-08-pt1-PgH228",
     "title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE",
     "granuleClass": "HOUSE"},
    {"granuleId": "CREC-2001-02-08-pt1-PgH200",
     "title": "PROVIDING FOR CONSIDERATION OF H.R. 9", "granuleClass": "HOUSE"},
], "nextPage": None}
SUMMARY = {"title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE",
           "granuleId": "CREC-2001-02-08-pt1-PgH228",
           "download": {"txtLink": "https://api.govinfo.gov/packages/CREC-2001-02-08/granules/CREC-2001-02-08-pt1-PgH228/htm"},
           "detailsLink": "https://www.govinfo.gov/app/details/CREC-2001-02-08"}
GRANULE_TEXT = "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE ..."


def _handler(request):
    url = str(request.url)
    if "/collections/CREC/" in url:
        return httpx.Response(200, json=COLLECTIONS)
    if "/summary" in url:
        return httpx.Response(200, json=SUMMARY)
    if url.endswith("/granules") or "/granules?" in url:
        return httpx.Response(200, json=GRANULES)
    if "htm" in url or url.endswith(".txt"):
        return httpx.Response(200, text=GRANULE_TEXT)
    return httpx.Response(404)


def _client():
    return CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(_handler)))


def test_discovery_keeps_only_resignation_granules():
    granules = _client().discover_resignations("2001-02-08", "2001-02-09")
    assert [g["granuleId"] for g in granules] == ["CREC-2001-02-08-pt1-PgH228"]
    assert granules[0]["packageId"] == "CREC-2001-02-08"


def test_fetch_granule_text_and_meta():
    text, meta = _client().fetch_granule("CREC-2001-02-08", "CREC-2001-02-08-pt1-PgH228")
    assert "RESIGNATION" in text
    assert meta["page"] == "H228"
    assert meta["url"].endswith("CREC-2001-02-08")
    assert meta["granule_id"] == "CREC-2001-02-08-pt1-PgH228"


def test_paged_follows_next_page():
    page1 = {"packages": [{"packageId": "CREC-2001-02-08"}],
             "nextPage": "https://api.govinfo.gov/collections/CREC/next?offsetMark=ABC"}
    page2 = {"packages": [{"packageId": "CREC-2001-02-09"}], "nextPage": None}

    calls = {"n": 0}

    def handler(request):
        if "/collections/CREC/" in str(request.url):
            calls["n"] += 1
            return httpx.Response(200, json=page1 if calls["n"] == 1 else page2)
        return httpx.Response(404)

    client = CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    pkgs = client.list_packages("2001-02-08", "2001-02-10")
    assert [p["packageId"] for p in pkgs] == ["CREC-2001-02-08", "CREC-2001-02-09"]
    assert calls["n"] == 2


def test_fetch_granule_empty_text_when_no_txt_link():
    summary = {"title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE",
               "granuleId": "CREC-2001-02-08-pt1-PgH228",
               "detailsLink": "https://www.govinfo.gov/app/details/CREC-2001-02-08"}

    def handler(request):
        if "/summary" in str(request.url):
            return httpx.Response(200, json=summary)
        return httpx.Response(404)

    client = CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    text, meta = client.fetch_granule("CREC-2001-02-08", "CREC-2001-02-08-pt1-PgH228")
    assert text == ""
    assert meta["page"] == "H228"
