"""GovInfo CREC (Congressional Record) client: discover committee-resignation
granules over a date range and fetch their text.

GovInfo is fronted by api.data.gov; the congress.gov API key usually works.
Falls back to GOVINFO_API_KEY if set.
"""

import os
import re
from typing import List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

GOVINFO_API = "https://api.govinfo.gov"
# Most titles read "RESIGNATION AS MEMBER OF ...COMMITTEE" (singular), but a
# granule can hold more than one signer's letter at once, printed as
# "(TEMPORARY )RESIGNATIONS AS MEMBERS OF ...COMMITTEE" (CREC-1994-05-19,
# 103rd Congress: two members temporarily giving up a committee seat to
# serve on another, with seniority protected).
_RESIGNATION_TITLE = re.compile(
    r"(?:TEMPORARY\s+)?RESIGNATIONS?\s+AS\s+MEMBERS?\s+OF\s+.*COMMITTEE", re.IGNORECASE
)


def _extract_text(body: str) -> str:
    """GovInfo's CREC txtLink serves an HTML page with the record text in <pre>."""
    soup = BeautifulSoup(body, "lxml")
    pre = soup.find("pre")
    return pre.get_text() if pre else soup.get_text()


class CRECClient:
    def __init__(self, api_key: str, client: Optional[httpx.Client] = None,
                 base_url: str = GOVINFO_API, page_size: int = 100):
        if not api_key:
            raise RuntimeError("A GovInfo/congress.gov API key is required.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self._client = client or httpx.Client(timeout=30.0)

    @classmethod
    def from_env(cls, **kwargs) -> "CRECClient":
        key = os.environ.get("CONGRESS_GOV_API_KEY") or os.environ.get("GOVINFO_API_KEY")
        if not key:
            raise RuntimeError(
                "Set CONGRESS_GOV_API_KEY (or GOVINFO_API_KEY) for GovInfo CREC access."
            )
        return cls(key, **kwargs)

    def _get(self, url: str, **params) -> dict:
        # Merge params (incl. api_key) INTO the URL's existing query rather than
        # passing params= to client.get, which would replace a fully-qualified
        # nextPage URL's embedded cursor (offsetMark/pageSize) and 500 on GovInfo.
        merged = {**params, "api_key": self.api_key}
        resp = self._client.get(httpx.URL(url).copy_merge_params(merged))
        resp.raise_for_status()
        return resp.json()

    def _paged(self, url: str, key: str, **params):
        params.setdefault("offsetMark", "*")
        params.setdefault("pageSize", self.page_size)
        while url:
            payload = self._get(url, **params)
            for item in payload.get(key, []):
                yield item
            url = payload.get("nextPage")
            params = {}  # nextPage is a fully-qualified URL with its own query

    def list_packages(self, start: str, end: str) -> List[dict]:
        # /published filters by dateIssued (what we want); /collections filters by
        # lastModified, which misses historical issues. Dates must be plain YYYY-MM-DD.
        url = f"{self.base_url}/published/{start}/{end}"
        return list(self._paged(url, "packages", collection="CREC"))

    def discover_resignations(self, start: str, end: str) -> List[dict]:
        """Return resignation granules across CREC packages in [start, end)."""
        found = []
        for pkg in self.list_packages(start, end):
            pid = pkg["packageId"]
            url = f"{self.base_url}/packages/{pid}/granules"
            for g in self._paged(url, "granules"):
                if _RESIGNATION_TITLE.search(g.get("title") or ""):
                    g["packageId"] = pid
                    found.append(g)
        return found

    def fetch_granule(self, package_id: str, granule_id: str) -> Tuple[str, dict]:
        """Return (text, meta) for a granule. meta carries page + details URL."""
        summary = self._get(
            f"{self.base_url}/packages/{package_id}/granules/{granule_id}/summary"
        )
        txt_link = summary.get("download", {}).get("txtLink")
        text = ""
        # Text is best-effort: a missing link or non-200 yields empty text (summary above is required and raises).
        if txt_link:
            resp = self._client.get(txt_link, params={"api_key": self.api_key})
            if resp.status_code == 200:
                text = _extract_text(resp.text)
        page = None
        m = re.search(r"Pg([A-Z]\d+)", granule_id)
        if m:
            page = m.group(1)
        meta = {"granule_id": granule_id, "page": page,
                "url": summary.get("detailsLink") or f"https://www.govinfo.gov/app/details/{package_id}"}
        return text, meta
