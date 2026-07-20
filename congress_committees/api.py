"""Client for the congress.gov API: discovery of committee-change resolutions
and retrieval of their action history.

Requires a (free) API key from https://api.congress.gov, read from the
CONGRESS_GOV_API_KEY environment variable.
"""

import os
from typing import List, Optional

import httpx

from .models import BillAction
from .parser import classify_title
from .senate_parser import classify_senate_title

API_BASE = "https://api.congress.gov/v3"
_AGREED = "agreed to"


def filter_committee_change_bills(bill_list: dict) -> List[dict]:
    """Keep only bills whose title marks them as committee membership changes."""
    kept = []
    for bill in bill_list.get("bills", []):
        is_change, _ = classify_title(bill.get("title", ""))
        if is_change:
            kept.append(bill)
    return kept


def filter_senate_committee_change_bills(bill_list: dict) -> List[dict]:
    """Keep only S.Res. bills whose title marks them as committee-assignment
    resolutions (see senate_parser.classify_senate_title)."""
    kept = []
    for bill in bill_list.get("bills", []):
        if classify_senate_title(bill.get("title", "")):
            kept.append(bill)
    return kept


def parse_actions(actions_payload: dict) -> List[BillAction]:
    """Map a congress.gov actions response into BillAction models."""
    return [
        BillAction(
            date=a.get("actionDate"),
            text=a.get("text", ""),
            type=a.get("type"),
        )
        for a in actions_payload.get("actions", [])
    ]


def extract_agreed_to_date(actions: List[BillAction]) -> Optional[str]:
    """Return the date of the action signalling the resolution was agreed to."""
    for action in actions:
        if _AGREED in (action.text or "").lower():
            return action.date
    return None


class CongressGovClient:
    """Thin wrapper over the congress.gov v3 endpoints used here."""

    def __init__(
        self,
        api_key: str,
        client: Optional[httpx.Client] = None,
        base_url: str = API_BASE,
        page_size: int = 250,
    ):
        if not api_key:
            raise RuntimeError("A congress.gov API key is required.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self._client = client or httpx.Client(timeout=30.0)

    @classmethod
    def from_env(cls, **kwargs) -> "CongressGovClient":
        key = os.environ.get("CONGRESS_GOV_API_KEY")
        if not key:
            raise RuntimeError(
                "CONGRESS_GOV_API_KEY is not set. Get a free key at "
                "https://api.congress.gov and export it."
            )
        return cls(key, **kwargs)

    def _get(self, path: str, **params) -> dict:
        params.setdefault("format", "json")
        params["api_key"] = self.api_key
        resp = self._client.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def list_committee_change_resolutions(
        self, congress: int, since: Optional[str] = None, bill_type: str = "hres"
    ) -> List[dict]:
        """List House/Senate resolutions about committee changes, newest activity first.

        `since` is an ISO date (YYYY-MM-DD); when given, only bills updated on or
        after that date are returned. Follows pagination (ALL bills, not just the
        first page) -- a committee-election resolution typically gets one action
        and is never updated again, so with a Congress-wide `since` window it can
        sit well past the first `limit`-sized page sorted by updateDate and would
        otherwise be silently dropped.

        `bill_type="sres"` selects Senate resolutions, filtered by
        classify_senate_title instead of the House's classify_title -- the two
        chambers' committee-resolution titles use entirely different phrasing.
        """
        params = {"sort": "updateDate+desc", "limit": self.page_size}
        if since:
            params["fromDateTime"] = f"{since}T00:00:00Z"

        bills: List[dict] = []
        offset = 0
        while True:
            payload = self._get(f"/bill/{congress}/{bill_type}", offset=offset, **params)
            batch = payload.get("bills", [])
            bills.extend(batch)
            if not batch or not payload.get("pagination", {}).get("next"):
                break
            offset += self.page_size
        if bill_type == "sres":
            return filter_senate_committee_change_bills({"bills": bills})
        return filter_committee_change_bills({"bills": bills})

    def get_actions(self, congress: int, number: str, bill_type: str = "hres") -> List[BillAction]:
        payload = self._get(
            f"/bill/{congress}/{bill_type}/{number}/actions", limit=self.page_size
        )
        return parse_actions(payload)

    def list_committees(self, chamber: str = "house") -> List[dict]:
        """Return ALL committee records for a chamber (follows pagination)."""
        committees: List[dict] = []
        offset = 0
        while True:
            payload = self._get(f"/committee/{chamber}", limit=self.page_size, offset=offset)
            batch = payload.get("committees", [])
            committees.extend(batch)
            if not batch or not payload.get("pagination", {}).get("next"):
                break
            offset += self.page_size
        return committees

    def get_committee(self, system_code: str, chamber: str = "house") -> dict:
        """Return the committee detail record (includes `history`)."""
        payload = self._get(f"/committee/{chamber}/{system_code}")
        return payload.get("committee", {})
