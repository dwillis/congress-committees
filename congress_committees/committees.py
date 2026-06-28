"""Map committee names (current and historical) to congress.gov system codes."""

import re
from typing import Dict, List, Optional


def _normalize(name: str) -> str:
    """Normalize a committee name for matching: drop boilerplate words, lowercase."""
    n = name.lower()
    n = re.sub(r"\bcommittee\b|\bhouse\b|\bpermanent\b|\bselect\b|\bon\b|\bthe\b|\bof\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


class CommitteeIndex:
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
                    by_norm.setdefault(key, code)
        return cls(by_norm)

    def code_for(self, name: str) -> Optional[str]:
        return self._by_norm.get(_normalize(name))
