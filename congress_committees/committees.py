"""Map committee names (current and historical) to congress.gov system codes."""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .atomic_io import atomic_write_text

logger = logging.getLogger(__name__)


def _fetch_committee_records(client, chamber: str = "house") -> List[dict]:
    """Fetch top-level committee records (systemCode, name, previous_names) from the API.

    Only top-level committees (no `parent`) are returned -- resignations name full
    committees, not subcommittees. Each committee's `history` officialNames and
    libraryOfCongressNames are collected into `previous_names` (best-effort: a
    committee whose detail fetch fails is kept with no history and a warning).
    """
    records = []
    for com in client.list_committees(chamber):
        if com.get("parent"):
            continue
        code = com.get("systemCode")
        if not code:
            continue
        names = [com.get("name", "")]
        try:
            history = client.get_committee(code, chamber).get("history", [])
        except Exception as exc:  # pragma: no cover - network degradation
            logger.warning("committee history fetch failed for %s: %s", code, exc)
            history = []
        for h in history:
            if h.get("officialName"):
                names.append(h["officialName"])
            if h.get("libraryOfCongressName"):
                names.append(h["libraryOfCongressName"])
        records.append({"systemCode": code, "name": com.get("name", ""),
                        "previous_names": names})
    return records


def _normalize(name: str) -> str:
    """Normalize a committee name for matching: drop boilerplate words, lowercase.

    Keeps "select"/"permanent" so select committees stay distinct from standing
    committees on the same topic; still strips the "house" chamber prefix.
    """
    n = name.lower()
    n = re.sub(r"\bcommittee\b|\bhouse\b|\bon\b|\bthe\b|\bof\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


class CommitteeIndex:
    """Map committee names to system codes by normalizing away boilerplate words
    and the chamber prefix; first-wins on any residual collision (logged)."""

    def __init__(self, by_norm: Dict[str, str]):
        self._by_norm = by_norm

    @classmethod
    def from_records(cls, records: List[dict]) -> "CommitteeIndex":
        by_norm: Dict[str, str] = {}
        for rec in records:
            code = rec.get("systemCode")
            if not code:
                continue
            names = [rec.get("name", "")] + list(rec.get("previous_names", []))
            for name in names:
                key = _normalize(name)
                if key:
                    if key in by_norm and by_norm[key] != code:
                        logger.warning(
                            "committee normalization collision: %r -> %s vs %s",
                            key, by_norm[key], code,
                        )
                    by_norm.setdefault(key, code)
        return cls(by_norm)

    @classmethod
    def from_client(cls, client, chamber: str = "house") -> "CommitteeIndex":
        """Build the index from a congress.gov client, including historical names.

        Always hits the API (no cache). Use ``load`` for the cached path.
        """
        return cls.from_records(_fetch_committee_records(client, chamber))

    @classmethod
    def load(cls, client, chamber: str = "house", cache_dir: str = ".cache") -> "CommitteeIndex":
        """Build the index, caching fetched committee records to disk.

        On first run the records (including historical names) are fetched from the API
        and written to <cache_dir>/committees-<chamber>.json; later runs reuse the cache.
        Delete that file to refresh after a Congress's committee renames.
        """
        cache_path = Path(cache_dir) / f"committees-{chamber}.json"
        if cache_path.exists():
            try:
                return cls.from_records(json.loads(cache_path.read_text()))
            except (json.JSONDecodeError, ValueError) as exc:
                # A truncated/partial cache (interrupted or concurrent earlier
                # run) must not break every subsequent run -- re-fetch instead.
                logger.warning("corrupt committee cache %s; re-fetching: %s", cache_path, exc)
        records = _fetch_committee_records(client, chamber)
        atomic_write_text(cache_path, json.dumps(records, indent=2))
        return cls.from_records(records)

    def code_for(self, name: str) -> Optional[str]:
        return self._by_norm.get(_normalize(name))
