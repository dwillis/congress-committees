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
GRANULE_TEXT = ("<html><head><title>CR</title></head><body><pre>\n"
                "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE\n"
                "Dear Speaker: ...\n</pre></body></html>")


def _handler(request):
    url = str(request.url)
    if "/published/" in url:
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


def test_discovery_finds_plural_temporary_resignations_title():
    # CREC-1994-05-19-pt1-PgH44 (103rd Congress): "TEMPORARY RESIGNATIONS AS
    # MEMBERS OF COMMITTEE ON SCIENCE, SPACE, AND TECHNOLOGY" -- plural
    # "RESIGNATIONS"/"MEMBERS" plus a "TEMPORARY" prefix, a real committee
    # resignation notice (two members, in this case) that the singular-only
    # regex didn't recognize at all, so it was never even discovered.
    granules = {"granules": [
        {"granuleId": "CREC-1994-05-19-pt1-PgH44",
         "title": "TEMPORARY RESIGNATIONS AS MEMBERS OF COMMITTEE ON SCIENCE, "
                  "SPACE, AND TECHNOLOGY"},
        {"granuleId": "CREC-1994-05-19-pt1-PgH50", "title": "THE JOURNAL"},
    ], "nextPage": None}

    def handler(request):
        url = str(request.url)
        if "/published/" in url:
            return httpx.Response(200, json=COLLECTIONS)
        if url.endswith("/granules") or "/granules?" in url:
            return httpx.Response(200, json=granules)
        return httpx.Response(404)

    client = CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    found = client.discover_resignations("1994-05-19", "1994-05-20")
    assert [g["granuleId"] for g in found] == ["CREC-1994-05-19-pt1-PgH44"]


def test_fetch_granule_text_and_meta():
    text, meta = _client().fetch_granule("CREC-2001-02-08", "CREC-2001-02-08-pt1-PgH228")
    assert "RESIGNATION" in text
    assert "<pre>" not in text and "<html>" not in text
    assert meta["page"] == "H228"
    assert meta["url"].endswith("CREC-2001-02-08")
    assert meta["granule_id"] == "CREC-2001-02-08-pt1-PgH228"


def test_paged_follows_next_page():
    page1 = {"packages": [{"packageId": "CREC-2001-02-08"}],
             "nextPage": "https://api.govinfo.gov/published/2001-02-05/2001-02-09?offsetMark=CURSOR&pageSize=2&collection=CREC"}
    page2 = {"packages": [{"packageId": "CREC-2001-02-09"}], "nextPage": None}

    def handler(request):
        url = str(request.url)
        if "offsetMark=CURSOR" in url:          # the follow MUST carry the cursor
            return httpx.Response(200, json=page2)
        if "/published/" in url:                # first page (offsetMark=* / %2A)
            return httpx.Response(200, json=page1)
        return httpx.Response(500, json={"message": "missing offsetMark cursor"})

    client = CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    pkgs = client.list_packages("2001-02-05", "2001-02-09")
    assert [p["packageId"] for p in pkgs] == ["CREC-2001-02-08", "CREC-2001-02-09"]


def test_discovery_skips_granule_with_null_title():
    # GovInfo sometimes returns a granule whose title is explicitly null; dict.get
    # with a default doesn't help (the key is present), so discovery must not crash.
    granules = {"granules": [
        {"granuleId": "CREC-2001-02-08-pt1-PgH228",
         "title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE"},
        {"granuleId": "CREC-2001-02-08-pt1-PgH999", "title": None},
    ], "nextPage": None}

    def handler(request):
        url = str(request.url)
        if "/published/" in url:
            return httpx.Response(200, json=COLLECTIONS)
        if url.endswith("/granules") or "/granules?" in url:
            return httpx.Response(200, json=granules)
        return httpx.Response(404)

    client = CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    found = client.discover_resignations("2001-02-08", "2001-02-09")
    assert [g["granuleId"] for g in found] == ["CREC-2001-02-08-pt1-PgH228"]


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
