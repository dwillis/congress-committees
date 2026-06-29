"""Map committee names (current and historical) to congress.gov system codes."""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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

        Only top-level committees (no `parent`) are indexed -- resignations name full
        committees, not subcommittees. Each committee's `history` officialNames and
        libraryOfCongressNames are indexed to its current systemCode (best-effort:
        a committee whose detail fetch fails is skipped with a warning).
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
        return cls.from_records(records)

    def code_for(self, name: str) -> Optional[str]:
        return self._by_norm.get(_normalize(name))
