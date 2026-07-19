"""Resolve printed member names (e.g. "Mr. Smith of Texas") to bioguide IDs.

Backed by the unitedstates/congress-legislators YAML datasets. Matching is
best-effort: surname plus state when the resolution prints one. Ambiguous
matches (multiple House members with the same surname and no disambiguating
state) resolve to None rather than guessing.
"""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .atomic_io import atomic_write_bytes

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
    "american samoa": "AS", "district of columbia": "DC",
    "d.c.": "DC", "d.c": "DC", "guam": "GU",
    "northern mariana islands": "MP", "puerto rico": "PR", "virgin islands": "VI",
}

# The space after the honorific's period is optional -- GPO's pre-XML-era
# plain-text rendition sometimes drops it as a typo ("Mr.McKeon").
_HONORIFIC = re.compile(r"^\s*(?:Mr|Ms|Mrs|Miss)\.\s*", re.IGNORECASE)
# The honorific also carries a gender signal ("Mr." vs "Ms./Mrs./Miss") that
# can break a tie when a same-surname, same-state candidate pool can't be
# narrowed by service date alone (e.g. "Mr. Johnson of Texas" -- Sam Johnson
# and Eddie Bernice Johnson both represented Texas concurrently).
_HONORIFIC_MATCH = re.compile(r"^\s*(?P<hon>Mr|Ms|Mrs|Miss)\.\s*", re.IGNORECASE)
_HONORIFIC_GENDER = {"mr": "M", "ms": "F", "mrs": "F", "miss": "F"}

# A generational suffix (e.g. "George Brown, Jr., California", the full-name
# text-mode schema's own comma-separated form -- reconstructed by the caller
# as "George Brown Jr. of California") is never part of `last` in the
# congress-legislators YAML -- strip it before the surname lookup, same as
# the honorific and the "of <State>" suffix.
_GENERATIONAL_SUFFIX_RE = re.compile(r",?\s+(?:Jr|Sr|II|III|IV)\.?\s*$", re.IGNORECASE)
# "or" tolerates a genuine source typo ("Ms. Hooley or Oregon" for "of
# Oregon") -- a small, bounded substitution in a fixed grammatical position
# (the state connector), unlike an unbounded surname typo.
_OF_STATE = re.compile(r"\s+(?:of|or)\s+(?P<state>[A-Za-z .]+?)\s*$", re.IGNORECASE)


# Apostrophe-like characters that appear interchangeably in printed names
# ("D'Esposito" vs "D’Esposito") and in the congress-legislators YAML --
# NFKD doesn't touch these (they aren't a base+combining-mark decomposition),
# so they need their own normalization to a plain "'".
_APOSTROPHES = "’‘ʼ`´"
_APOSTROPHE_RE = re.compile(f"[{_APOSTROPHES}]")


def _fold(text: str) -> str:
    """Lowercase, strip accents, normalize apostrophe variants, and treat a
    hyphen as a space, so "Velazquez" matches "Velázquez", "D'Esposito"
    matches "D’Esposito", and "Jackson-Lee" matches "Jackson Lee" -- whichever
    side (CREC/resolution text vs the congress-legislators YAML) carries the
    accent/apostrophe/hyphen style."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    folded = _APOSTROPHE_RE.sub("'", folded)
    return folded.replace("-", " ")


# Common English nickname <-> formal-name pairs that AREN'T a simple prefix of
# each other (a prefix match, e.g. "Chris"/"Christopher", is already handled
# below without this table) -- not exhaustive, just the most common ones
# likely to appear as a member's preferred first name in a printed
# resolution or letter ("Mr. Tom Davis of Virginia" for Thomas Davis).
_NICKNAMES = {
    "tom": "thomas", "bob": "robert", "bill": "william", "dick": "richard",
    "jack": "john", "jim": "james", "ted": "edward", "ned": "edward",
    "chuck": "charles", "hank": "henry", "mike": "michael",
    "larry": "lawrence", "andy": "andrew", "jerry": "gerald", "gerry": "gerald",
    "peggy": "margaret", "sally": "sarah", "polly": "mary",
    "kathy": "katherine", "cathy": "catherine", "debbie": "deborah",
    "patty": "patricia", "patsy": "patricia", "sandy": "sandra",
    "cindy": "cynthia", "beth": "elizabeth", "betty": "elizabeth",
    "liz": "elizabeth", "ginny": "virginia", "nate": "nathaniel",
}


def _first_names_match(candidate_first: str, printed_first: str) -> bool:
    """True if a candidate's registered first name plausibly matches the
    printed one -- exact, a prefix in either direction (handles
    "Chris"/"Christopher"), or a known irregular nickname (handles
    "Tom"/"Thomas", which isn't a prefix relationship)."""
    a, b = _fold(candidate_first), _fold(printed_first)
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    return _NICKNAMES.get(a) == b or _NICKNAMES.get(b) == a


def _levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings (insert/delete/substitute, cost 1)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


# State/territory names are a small, fixed vocabulary, so a minor misprint
# (an official bill's "Tennnesse" for "Tennessee") can be corrected safely --
# unlike surnames, where the space is unbounded and a fuzzy match risks
# resolving to the wrong person entirely.
_STATE_TYPO_MAX_DISTANCE = 2


def _fuzzy_state_lookup(value_lower: str) -> Optional[str]:
    best_dist, best_abbrev, tied = None, None, False
    for name, abbrev in _STATES.items():
        dist = _levenshtein(value_lower, name)
        if best_dist is None or dist < best_dist:
            best_dist, best_abbrev, tied = dist, abbrev, False
        elif dist == best_dist:
            tied = True
    if best_dist is not None and best_dist <= _STATE_TYPO_MAX_DISTANCE and not tied:
        return best_abbrev
    return None


def _normalize_state(value: Optional[str]) -> Optional[str]:
    """Normalize a state name or abbreviation to a USPS abbreviation.

    Falls back to a small edit-distance match against the full name when the
    exact spelling doesn't hit, tolerating minor misprints in the source text.
    """
    if not value:
        return None
    value = value.strip()
    if len(value) == 2 and value.upper() in _STATES.values():
        return value.upper()
    exact = _STATES.get(value.lower())
    if exact:
        return exact
    # "the Virgin Islands"/"the District of Columbia" -- a common phrasing
    # variant for territories/D.C., not a typo, and not in the dict's key.
    if value.lower().startswith("the "):
        exact = _STATES.get(value[4:].lower())
        if exact:
            return exact
    return _fuzzy_state_lookup(value.lower())


def _honorific_gender(printed: str) -> Optional[str]:
    """Return 'M'/'F' for a leading "Mr."/"Ms."/"Mrs."/"Miss" honorific, or None."""
    m = _HONORIFIC_MATCH.match(printed or "")
    return _HONORIFIC_GENDER.get(m.group("hon").lower()) if m else None


def _strip_honorific_and_state(printed: str) -> tuple[str, Optional[str]]:
    """Strip a leading honorific and trailing "of <State>" from a printed name.

    Returns (remaining_name, state_abbrev_or_None). The remaining name may hold
    a multi-word surname ("Wasserman Schultz") and/or a leading given name
    ("David Scott") -- callers decide how to tokenize it.
    """
    name = _HONORIFIC.sub("", printed or "").strip()
    state = None
    m = _OF_STATE.search(name)
    if m:
        state = _normalize_state(m.group("state"))
        name = name[: m.start()].strip()
    return name, state


def parse_member_name(printed: str) -> tuple[str, Optional[str]]:
    """Split a printed member name into (surname, state_abbrev_or_None).

    e.g. "Mr. Smith of Texas" -> ("smith", "TX"); "Mr. Gallagher" -> ("gallagher", None).
    Returns only the last token as the surname; ``LegislatorIndex.lookup``
    handles multi-word surnames.
    """
    name, state = _strip_honorific_and_state(printed)
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
            atomic_write_bytes(Path(cache_dir) / name, resp.content)
    finally:
        if owns:
            client.close()


class _Candidate:
    __slots__ = ("bioguide", "states", "first", "terms", "gender")

    def __init__(
        self,
        bioguide: str,
        states: set,
        first: Optional[str] = None,
        terms: Optional[List[tuple]] = None,
        gender: Optional[str] = None,
    ):
        self.bioguide = bioguide
        self.states = states
        self.first = first
        # List of (start, end) ISO date strings; either may be None.
        self.terms = terms or []
        self.gender = gender

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
            gender = (rec.get("bio") or {}).get("gender")
            by_surname.setdefault(_fold(last), []).append(
                _Candidate(bioguide, house_states, name.get("first"), term_ranges, gender)
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

    def _resolve(
        self,
        candidates: List["_Candidate"],
        state: Optional[str],
        first: Optional[str],
        on_date: Optional[str] = None,
        gender: Optional[str] = None,
        strict_state: bool = False,
    ) -> Optional[str]:
        """Pick a single bioguide from a surname group using state, service date,
        first name, then the honorific's gender. Each filter is skipped if it
        would empty the pool, so a wrong state/date never discards an
        otherwise-unique candidate -- UNLESS ``strict_state``, which requires an
        actual state match instead (see the hyphen-fallback surname guess in
        ``lookup()``, where the surname itself is already a guess and a
        same-surname-wrong-state coincidence must not resolve confidently)."""
        pool = candidates
        if state:
            by_state = [c for c in pool if state in c.states]
            if by_state:  # keep the full pool if the state matches nobody
                pool = by_state
            elif strict_state:
                return None
        if on_date:
            by_date = [c for c in pool if c.served_on(on_date)]
            if by_date:
                pool = by_date
        if len(pool) == 1:
            return pool[0].bioguide
        if first:
            by_first = [c for c in pool if c.first and _first_names_match(c.first, first)]
            if len(by_first) == 1:
                return by_first[0].bioguide
        if gender:
            by_gender = [c for c in pool if c.gender == gender]
            if len(by_gender) == 1:
                return by_gender[0].bioguide
        return None  # ambiguous

    def lookup(
        self,
        printed_name: str,
        state: Optional[str] = None,
        on_date: Optional[str] = None,
    ) -> Optional[str]:
        """Return a bioguide ID for the printed member name, or None if unresolved.

        When ``on_date`` (YYYY-MM-DD) is given, same-surname namesakes are
        disambiguated by who was serving in the House on that date.
        """
        name, parsed_state = _strip_honorific_and_state(printed_name)
        name = _GENERATIONAL_SUFFIX_RE.sub("", name)
        state = _normalize_state(state) or parsed_state
        gender = _honorific_gender(printed_name)
        tokens = name.split()
        if not tokens:
            return None
        # The remaining name may be "Surname", "First Surname", or a multi-word
        # surname ("Wasserman Schultz"). Try the longest surname first so a real
        # two-word surname wins over treating its first token as a given name.
        for k in range(len(tokens), 0, -1):
            surname = _fold(" ".join(tokens[-k:])).rstrip(".,")
            candidates = self._by_surname.get(surname)
            first = " ".join(tokens[:-k]).strip() or None
            if candidates:
                resolved = self._resolve(candidates, state, first, on_date, gender)
                if resolved:
                    return resolved
            if k == 1 and "-" in tokens[-1]:
                # A hyphen sometimes joins a MIDDLE name to the surname by
                # mistake ("Eddie Bernice-Johnson" for "Eddie Bernice
                # Johnson", "Eleanor Holmes-Norton" for "Eleanor Holmes
                # Norton") rather than being part of a genuine two-word
                # hyphenated surname (which already matches above via
                # _fold's hyphen-to-space folding). Try just the piece after
                # the LAST hyphen as a bare single-word surname too -- but
                # this surname is itself a GUESS, so require an actual state
                # match (strict_state) rather than the usual leniency, or a
                # same-surname-wrong-person coincidence (e.g. "Green" from
                # "Christian-Green" matching an unrelated Rep. Gene Green)
                # resolves confidently to the wrong bioguide instead of
                # correctly staying unresolved.
                after_hyphen = tokens[-1].rsplit("-", 1)[-1]
                hyphen_candidates = self._by_surname.get(_fold(after_hyphen).rstrip(".,"))
                if hyphen_candidates:
                    resolved = self._resolve(
                        hyphen_candidates, state, first, on_date, gender, strict_state=True
                    )
                    if resolved:
                        return resolved
        return None

    def lookup_full_name(
        self, first: str, last: str, on_date: Optional[str] = None
    ) -> Optional[str]:
        """Resolve a signer to a bioguide by surname, active-on-date, then first name.

        Returns the bioguide only when exactly one candidate matches confidently.
        """
        candidates = self._by_surname.get(_fold(last).rstrip(".,"), [])
        if on_date:
            candidates = [c for c in candidates if c.served_on(on_date)]
        if first:
            # When no candidate's first name matches, fall back to the
            # surname+date set rather than emptying it: we deliberately trust
            # surname+date over a non-matching first name. The single-match
            # gate below still prevents a wrong-but-confident return.
            candidates = [
                c for c in candidates if c.first and _first_names_match(c.first, first)
            ] or candidates
        return candidates[0].bioguide if len(candidates) == 1 else None
