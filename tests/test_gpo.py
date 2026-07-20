"""Tests for GPO govinfo bill-XML URL building and stage probing."""

import httpx

from congress_committees.gpo import (
    build_package_id,
    congress_gov_text_url,
    fetch_resolution_text,
    fetch_resolution_xml,
    html_url,
    xml_url,
)


def test_build_package_id():
    assert build_package_id(119, "1381", "eh") == "BILLS-119hres1381eh"


def test_xml_url():
    assert xml_url("BILLS-119hres1381eh") == (
        "https://www.govinfo.gov/content/pkg/BILLS-119hres1381eh/"
        "xml/BILLS-119hres1381eh.xml"
    )


def test_fetch_returns_first_available_stage():
    def handler(request: httpx.Request) -> httpx.Response:
        if "119hres1381eh" in str(request.url):
            return httpx.Response(200, content=b"<resolution/>")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    xml, package_id, stage = fetch_resolution_xml(119, "1381", client=client)

    assert xml == b"<resolution/>"
    assert package_id == "BILLS-119hres1381eh"
    assert stage == "eh"


def test_fetch_falls_through_to_later_stage():
    def handler(request: httpx.Request) -> httpx.Response:
        if "119hres1381enr" in str(request.url):
            return httpx.Response(200, content=b"<resolution/>")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    xml, package_id, stage = fetch_resolution_xml(119, "1381", client=client)

    assert package_id == "BILLS-119hres1381enr"
    assert stage == "enr"


def test_fetch_falls_through_to_agreed_to_house_stage():
    # BILLS-108hres79ath (108th Congress): some pre-XML-era House resolutions
    # that never leave the House are published only under "ath" (Agreed to
    # House) -- not "eh" (Engrossed), "enr", "rh", or "ih".
    def handler(request: httpx.Request) -> httpx.Response:
        if "108hres79ath" in str(request.url):
            return httpx.Response(200, content=b"resolution text")
        return httpx.Response(302)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    xml, package_id, stage = fetch_resolution_xml(108, "79", client=client)

    assert package_id == "BILLS-108hres79ath"
    assert stage == "ath"


def test_fetch_returns_none_when_no_stage_available():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_resolution_xml(119, "1381", client=client) is None


def test_html_url():
    assert html_url("BILLS-109hres6eh") == (
        "https://www.govinfo.gov/content/pkg/BILLS-109hres6eh/"
        "html/BILLS-109hres6eh.htm"
    )


def test_fetch_resolution_text_returns_first_available_stage():
    def handler(request: httpx.Request) -> httpx.Response:
        if "109hres6eh" in str(request.url):
            return httpx.Response(200, text="<pre>Committee text</pre>")
        return httpx.Response(302)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    text, package_id, stage = fetch_resolution_text(109, "6", client=client)

    assert text == "<pre>Committee text</pre>"
    assert package_id == "BILLS-109hres6eh"
    assert stage == "eh"


def test_fetch_resolution_text_returns_none_when_no_stage_available():
    # A missing rendition redirects to GovInfo's error page (302) rather than
    # 404ing -- must not be mistaken for success.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://www.govinfo.gov/error"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_resolution_text(109, "6", client=client) is None


# --- congress.gov fallback (GovInfo has nothing before the 103rd Congress) --

def test_html_url_passes_through_a_full_url_unchanged():
    # The congress.gov fallback below returns a full URL (not a GovInfo
    # package id) as the "package_id" slot, so collector.py's existing
    # `html_url(package_id)` call still produces the right link either way.
    url = "https://www.congress.gov/102/bills/HRES84/BILLS-hres84eh.htm"
    assert html_url(url) == url


def test_fetch_resolution_text_falls_back_to_congress_gov():
    # GovInfo's BILLS collection has nothing at all for the 102nd Congress
    # (confirmed live: every stage 404s) -- congress.gov hosts its own older
    # bill text directly, at a different URL shape entirely, but the same
    # stage abbreviations ("eh", "ath", ...).
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "govinfo.gov" in url:
            return httpx.Response(404)
        if "congress.gov/102/bills/HRES84/BILLS-hres84eh.htm" in url:
            return httpx.Response(200, text="<pre>Joint committee text</pre>")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    text, url, stage = fetch_resolution_text(102, "84", client=client)

    assert text == "<pre>Joint committee text</pre>"
    assert url == "https://www.congress.gov/102/bills/HRES84/BILLS-hres84eh.htm"
    assert stage == "eh"


def test_fetch_resolution_text_returns_none_when_neither_source_has_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_resolution_text(97, "59", client=client) is None


# --- Senate resolutions (bill_type="sres") ----------------------------------


def test_build_package_id_defaults_to_house():
    assert build_package_id(119, "1381", "eh") == "BILLS-119hres1381eh"


def test_build_package_id_senate():
    assert build_package_id(119, "16", "ats", bill_type="sres") == "BILLS-119sres16ats"


def test_congress_gov_text_url_senate_uses_uppercase_sres_directory():
    # Mirrors the House "HRES84" (uppercase dir) vs "hres84" (lowercase file)
    # split -- confirmed live for Senate resolutions too ("SRES46" works,
    # "sres46" 404s).
    assert congress_gov_text_url(102, "46", "ats", bill_type="sres") == (
        "https://www.congress.gov/102/bills/SRES46/BILLS-sres46ats.htm"
    )


def test_fetch_resolution_xml_senate_uses_sres_package_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if "119sres16ats" in str(request.url):
            return httpx.Response(200, content=b"<resolution/>")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    from congress_committees.gpo import SENATE_STAGES

    xml, package_id, stage = fetch_resolution_xml(
        119, "16", client=client, stages=SENATE_STAGES, bill_type="sres"
    )

    assert xml == b"<resolution/>"
    assert package_id == "BILLS-119sres16ats"
    assert stage == "ats"


def test_fetch_resolution_text_senate_falls_back_to_congress_gov():
    # GovInfo has nothing for the 101st Congress (confirmed live) -- same
    # congress.gov direct-hosting fallback as the House, "SRES"/"sres".
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "govinfo.gov" in url:
            return httpx.Response(404)
        if "congress.gov/101/bills/SRES99/BILLS-sres99ats.htm" in url:
            return httpx.Response(200, text="<pre>Committee text</pre>")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    from congress_committees.gpo import SENATE_STAGES

    text, url, stage = fetch_resolution_text(
        101, "99", client=client, stages=SENATE_STAGES, bill_type="sres"
    )

    assert text == "<pre>Committee text</pre>"
    assert url == "https://www.congress.gov/101/bills/SRES99/BILLS-sres99ats.htm"
    assert stage == "ats"
