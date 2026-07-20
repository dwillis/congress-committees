"""Fetch House/Senate resolution bill XML from GPO govinfo.

govinfo publishes bill text as packages named BILLS-<congress><type><number><stage>,
e.g. BILLS-119hres1381eh (House) or BILLS-119sres16ats (Senate). For committee-
appointment resolutions the operative agreed-to text is the engrossed ("eh")
version for the House or the agreed-to-Senate ("ats") version for the Senate;
we probe stages in likelihood order.
"""

from typing import Optional, Tuple

import httpx

GOVINFO_BASE = "https://www.govinfo.gov/content/pkg"

# GovInfo's BILLS collection has nothing at all before the 103rd Congress
# (confirmed live: every stage 404s for 102nd-Congress resolutions, House or
# Senate). congress.gov hosts its own older bill text directly, at a
# different URL shape entirely, but the same stage abbreviations -- a
# fallback source for Congresses GovInfo never digitized.
CONGRESS_GOV_BASE = "https://www.congress.gov"

# Probe order: engrossed (agreed-to text), agreed-to-House (some pre-XML-era
# House resolutions that never leave the House are published only under this
# stage, e.g. BILLS-108hres79ath), enrolled, reported, introduced.
DEFAULT_STAGES = ("eh", "ath", "enr", "rh", "ih")

# Senate committee-assignment resolutions are almost always agreed to the
# same day by unanimous consent, so "ats" (Agreed to Senate) is far and away
# the most common stage -- probed first, with earlier legislative stages as
# a fallback for the rare resolution that never got a floor vote recorded
# under "ats".
SENATE_STAGES = ("ats", "es", "rs", "is")

USER_AGENT = "congress-committees (https://github.com/dwillis/congress-committees)"


def build_package_id(congress: int, number: str, stage: str, bill_type: str = "hres") -> str:
    return f"BILLS-{congress}{bill_type}{number}{stage}"


def xml_url(package_id: str) -> str:
    return f"{GOVINFO_BASE}/{package_id}/xml/{package_id}.xml"


def html_url(package_id: str) -> str:
    # The congress.gov fallback in fetch_resolution_text returns a full URL
    # (not a GovInfo package id) in this slot -- pass it through unchanged so
    # callers (collector.py) don't need to know which source a document came
    # from to build the right link.
    if package_id.startswith("http://") or package_id.startswith("https://"):
        return package_id
    return f"{GOVINFO_BASE}/{package_id}/html/{package_id}.htm"


def congress_gov_text_url(congress: int, number: str, stage: str, bill_type: str = "hres") -> str:
    # The directory segment is case-sensitive on congress.gov's server --
    # "HRES84"/"SRES46" (uppercase) works, "hres84"/"sres46" 404s -- unlike
    # the lowercase filename right after it.
    return (
        f"{CONGRESS_GOV_BASE}/{congress}/bills/{bill_type.upper()}{number}/"
        f"BILLS-{bill_type}{number}{stage}.htm"
    )


def fetch_resolution_xml(
    congress: int,
    number: str,
    client: Optional[httpx.Client] = None,
    stages: Tuple[str, ...] = DEFAULT_STAGES,
    bill_type: str = "hres",
) -> Optional[Tuple[bytes, str, str]]:
    """Return (xml_bytes, package_id, stage) for the first available stage, or None."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, headers={"user-agent": USER_AGENT})
    try:
        for stage in stages:
            package_id = build_package_id(congress, number, stage, bill_type=bill_type)
            resp = client.get(xml_url(package_id))
            if resp.status_code == 200:
                return resp.content, package_id, stage
        return None
    finally:
        if owns_client:
            client.close()


def fetch_resolution_text(
    congress: int,
    number: str,
    client: Optional[httpx.Client] = None,
    stages: Tuple[str, ...] = DEFAULT_STAGES,
    bill_type: str = "hres",
) -> Optional[Tuple[str, str, str]]:
    """Return (text, package_id_or_url, stage) for the first available stage's
    plain-text rendition, or None.

    Fallback for Congresses with no XML rendition on GovInfo at all (109th and
    earlier) -- fetch_resolution_xml correctly returns None for these (a
    missing rendition 302-redirects to an error page rather than 404ing), but
    the plain text still exists and is structurally parseable
    (see parser.parse_resolution_text). For Congresses GovInfo never
    digitized at all (102nd and earlier for House, 101st and earlier for
    Senate), falls back further to congress.gov's own bill-text hosting --
    same stage abbreviations, different host and URL shape entirely, so the
    second slot holds a full URL instead of a GovInfo package id in that case
    (html_url() handles either transparently).
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, headers={"user-agent": USER_AGENT})
    try:
        for stage in stages:
            package_id = build_package_id(congress, number, stage, bill_type=bill_type)
            resp = client.get(html_url(package_id))
            if resp.status_code == 200:
                return resp.text, package_id, stage
        for stage in stages:
            url = congress_gov_text_url(congress, number, stage, bill_type=bill_type)
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text, url, stage
        return None
    finally:
        if owns_client:
            client.close()
