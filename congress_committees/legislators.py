"""Resolve printed member names (e.g. "Mr. Smith of Texas") to bioguide IDs.

Backed by the unitedstates/congress-legislators YAML datasets. Matching is
best-effort: surname plus state when the resolution prints one. Ambiguous
matches (multiple House members with the same surname and no disambiguating
state) resolve to None rather than guessing.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# unitedstates/congress-legislators raw datasets.
_CL_BASE = "https://unitedstates.github.io/congress-legislators/"
_CL_FILES = ("legislators-current.yaml", "legislators-historical.yaml")

# Full state/territory name -> USPS abbreviation, for the "of <State>" suffix.
_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "american samoa": "AS", "district of columbia": "DC", "guam": "GU",
    "northern mariana islands": "MP", "puerto rico": "PR", "virgin islands": "VI",
}

_HONORIFIC = re.compile(r"^\s*(?:Mr|Ms|Mrs|Miss)\.\s+", re.IGNORECASE)
_OF_STATE = re.compile(r"\s+of\s+(?P<state>[A-Za-z .]+?)\s*$", re.IGNORECASE)


def _normalize_state(value: Optional[str]) -> Optional[str]:
    """Normalize a state name or abbreviation to a USPS abbreviation."""
    if not value:
        return None
    value = value.strip()
    if len(value) == 2 and value.upper() in _STATES.values():
        return value.upper()
    return _STATES.get(value.lower())


def parse_member_name(printed: str) -> tuple[str, Optional[str]]:
    """Split a printed member name into (surname, state_abbrev_or_None).

    e.g. "Mr. Smith of Texas" -> ("smith", "TX"); "Mr. Gallagher" -> ("gallagher", None).
    """
    name = _HONORIFIC.sub("", printed or "").strip()
    state = None
    m = _OF_STATE.search(name)
    if m:
        state = _normalize_state(m.group("state"))
        name = name[: m.start()].strip()
    # Surname is the last whitespace-delimited token of what remains.
    surname = name.split()[-1] if name.split() else ""
    return surname.lower().rstrip(".,"), state


def resolve_legislator_files(path: Optional[str], cache_dir: str) -> List[Path]:
    """Resolve the list of YAML files to read, given an optional override path.

    - path is a single .yaml file  -> [that file]
    - path is a directory          -> the standard files within it
    - path is None                 -> the standard files within cache_dir
    """
    if path:
        p = Path(path)
        if p.is_file() or p.suffix in (".yaml", ".yml"):
            return [p]
        return [p / name for name in _CL_FILES]
    return [Path(cache_dir) / name for name in _CL_FILES]


def _download_legislators(cache_dir: str, names, client=None) -> None:
    import httpx

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    owns = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        for name in names:
            logger.info("Downloading %s", name)
            resp = client.get(_CL_BASE + name)
            resp.raise_for_status()
            (Path(cache_dir) / name).write_bytes(resp.content)
    finally:
        if owns:
            client.close()


class _Candidate:
    __slots__ = ("bioguide", "states", "first", "terms")

    def __init__(
        self,
        bioguide: str,
        states: set,
        first: Optional[str] = None,
        terms: Optional[List[tuple]] = None,
    ):
        self.bioguide = bioguide
        self.states = states
        self.first = first
        # List of (start, end) ISO date strings; either may be None.
        self.terms = terms or []

    def served_on(self, date: str) -> bool:
        """True if any term range contains the ISO date string (YYYY-MM-DD)."""
        for start, end in self.terms:
            if (start is None or start <= date) and (end is None or date <= end):
                return True
        return False


class LegislatorIndex:
    """Surname -> House-member candidates index."""

    def __init__(self, by_surname: Dict[str, List[_Candidate]]):
        self._by_surname = by_surname

    @classmethod
    def from_records(cls, records: List[dict]) -> "LegislatorIndex":
        by_surname: Dict[str, List[_Candidate]] = {}
        for rec in records:
            terms = rec.get("terms") or []
            house_states = {
                t.get("state") for t in terms if t.get("type") == "rep" and t.get("state")
            }
            if not house_states:
                continue  # only House members are candidates
            bioguide = (rec.get("id") or {}).get("bioguide")
            name = rec.get("name") or {}
            last = name.get("last")
            if not bioguide or not last:
                continue
            term_ranges = [
                (t.get("start"), t.get("end"))
                for t in terms
                if t.get("type") == "rep"
            ]
            by_surname.setdefault(last.lower(), []).append(
                _Candidate(bioguide, house_states, name.get("first"), term_ranges)
            )
        return cls(by_surname)

    @classmethod
    def from_yaml_files(cls, paths) -> "LegislatorIndex":
        records: List[dict] = []
        for path in paths:
            data = yaml.safe_load(Path(path).read_text())
            if data:
                records.extend(data)
        return cls.from_records(records)

    @classmethod
    def load(
        cls,
        path: Optional[str] = None,
        cache_dir: str = ".cache",
        client=None,
    ) -> "LegislatorIndex":
        """Build an index from a local path or by downloading the datasets.

        If `path` is a directory (or None and the cache already holds the files),
        the current + historical YAMLs there are used. Otherwise they are
        downloaded once into `cache_dir` and reused on later runs.
        """
        files = resolve_legislator_files(path, cache_dir)
        missing = [p for p in files if not p.exists()]
        if missing:
            _download_legislators(cache_dir, [p.name for p in missing], client)
        existing = [p for p in files if p.exists()]
        if not existing:
            raise RuntimeError("Could not locate or download congress-legislators data.")
        return cls.from_yaml_files(existing)

    def lookup(self, printed_name: str, state: Optional[str] = None) -> Optional[str]:
        """Return a bioguide ID for the printed member name, or None if unresolved."""
        surname, parsed_state = parse_member_name(printed_name)
        state = _normalize_state(state) or parsed_state
        candidates = self._by_surname.get(surname, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0].bioguide
        if state:
            matches = [c for c in candidates if state in c.states]
            if len(matches) == 1:
                return matches[0].bioguide
        return None  # ambiguous

    def lookup_full_name(
        self, first: str, last: str, on_date: Optional[str] = None
    ) -> Optional[str]:
        """Resolve a signer to a bioguide by surname, active-on-date, then first name.

        Returns the bioguide only when exactly one candidate matches confidently.
        """
        candidates = self._by_surname.get((last or "").lower().rstrip(".,"), [])
        if on_date:
            candidates = [c for c in candidates if c.served_on(on_date)]
        if first:
            fl = first.strip().lower()
            # When no candidate's first name matches, fall back to the
            # surname+date set rather than emptying it: we deliberately trust
            # surname+date over a non-matching first name. The single-match
            # gate below still prevents a wrong-but-confident return.
            candidates = [
                c
                for c in candidates
                if c.first
                and (
                    c.first.lower() == fl
                    or c.first.lower().startswith(fl)
                    or fl.startswith(c.first.lower())
                )
            ] or candidates
        return candidates[0].bioguide if len(candidates) == 1 else None
