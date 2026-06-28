"""Tests for GPO govinfo bill-XML URL building and stage probing."""

import httpx

from congress_committees.gpo import build_package_id, fetch_resolution_xml, xml_url


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


def test_fetch_returns_none_when_no_stage_available():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_resolution_xml(119, "1381", client=client) is None
