"""Fetch House resolution bill XML from GPO govinfo.

govinfo publishes bill text as packages named BILLS-<congress><type><number><stage>,
e.g. BILLS-119hres1381eh. For committee-appointment resolutions the operative
agreed-to text is the engrossed ("eh") version; we probe stages in likelihood order.
"""

from typing import Optional, Tuple

import httpx

GOVINFO_BASE = "https://www.govinfo.gov/content/pkg"

# Probe order: engrossed (agreed-to text), enrolled, reported, introduced.
DEFAULT_STAGES = ("eh", "enr", "rh", "ih")

USER_AGENT = "congress-committees (https://github.com/dwillis/congress-committees)"


def build_package_id(congress: int, number: str, stage: str) -> str:
    return f"BILLS-{congress}hres{number}{stage}"


def xml_url(package_id: str) -> str:
    return f"{GOVINFO_BASE}/{package_id}/xml/{package_id}.xml"


def fetch_resolution_xml(
    congress: int,
    number: str,
    client: Optional[httpx.Client] = None,
    stages: Tuple[str, ...] = DEFAULT_STAGES,
) -> Optional[Tuple[bytes, str, str]]:
    """Return (xml_bytes, package_id, stage) for the first available stage, or None."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, headers={"user-agent": USER_AGENT})
    try:
        for stage in stages:
            package_id = build_package_id(congress, number, stage)
            resp = client.get(xml_url(package_id))
            if resp.status_code == 200:
                return resp.content, package_id, stage
        return None
    finally:
        if owns_client:
            client.close()
