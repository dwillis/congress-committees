# Committee Resignation Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a second ingestion path that extracts House committee *resignations* from Congressional Record letters (GovInfo CREC granules) into the same unified committee-change-event output as the existing resolution-based additions.

**Architecture:** A new `congressional_record.py` (`CRECClient`) discovers CREC granules by title over a date range and fetches their TXT; a pure `parse_resignation_granule` in `parser.py` extracts committee(s)/member/dates; a `CommitteeIndex` (congress.gov committees API) maps names→`system_code` with rename history; `LegislatorIndex` gains full-name+date bioguide matching. Both the resolution and resignation paths flatten into a unified `List[CommitteeChangeEvent]` that the CLI serializes.

**Tech Stack:** Python 3.10+, httpx (+ `httpx.MockTransport` for offline tests), pydantic v2, BeautifulSoup/lxml, pyyaml, pytest.

**Design doc:** `docs/plans/2026-06-27-committee-resignations-design.md`

**Conventions for every task:** follow TDD (@superpowers:test-driven-development) — write the failing test, watch it fail, implement minimally, watch it pass, commit. Offline tests only (network via `httpx.MockTransport`; parsing via fixtures). Run `pytest -q` (excludes `live` by default). Use the existing `.venv` (`source .venv/bin/activate`).

---

## Task 1: Unified output models

**Files:**
- Modify: `congress_committees/models.py`
- Test: `tests/test_models.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_models.py
"""Tests for the unified committee-change-event output model."""

from congress_committees.models import (
    CommitteeChange,
    CommitteeChangeEvent,
    RecordRef,
    ResolutionRecord,
    ResolutionRef,
    to_events,
)


def test_committee_change_event_round_trips():
    event = CommitteeChangeEvent(
        congress="107",
        change_type="removal",
        committee="House Permanent Select Committee on Intelligence",
        member_name="Charles F. Bass",
        source="congressional_record",
        date="2001-02-08",
        source_ref=RecordRef(
            volume="147", issue="18", page="H228",
            granule_id="CREC-2001-02-08-pt1-PgH228", signed_date="2001-02-07",
            url="https://www.govinfo.gov/app/details/CREC-2001-02-08",
        ),
    )
    dumped = event.model_dump()
    assert dumped["source_ref"]["type"] == "congressional_record"
    assert dumped["system_code"] is None and dumped["gpo_code"] is None


def test_to_events_flattens_resolution_record():
    record = ResolutionRecord(
        congress="119", type="HRES", number="1381",
        title="Electing a Member...", stage="Engrossed-in-House",
        date="2026-06-24", govinfo_xml_url="http://x/BILLS.xml",
        congress_gov_url="http://c/1381", agreed_to_date="2026-06-24",
        committee_changes=[
            CommitteeChange(change_type="addition", committee="Committee on Foreign Affairs",
                            committee_code="HFA00", member_name="Mr. Gallagher",
                            bioguide_id="G000587"),
        ],
    )
    events = to_events(record)
    assert len(events) == 1
    ev = events[0]
    assert ev.change_type == "addition"
    assert ev.source == "resolution"
    assert ev.gpo_code == "HFA00"          # native from XML
    assert ev.system_code is None           # filled later, best-effort
    assert ev.member_name == "Mr. Gallagher"
    assert ev.bioguide_id == "G000587"
    assert ev.source_ref.type == "resolution"
    assert ev.source_ref.number == "1381"
    assert ev.source_ref.agreed_to_date == "2026-06-24"
```

**Step 2: Run to verify it fails**

Run: `pytest tests/test_models.py -q`
Expected: FAIL (ImportError: cannot import name `CommitteeChangeEvent`).

**Step 3: Implement minimally** — append to `congress_committees/models.py`:

```python
from typing import Annotated, Literal, Union
from pydantic import Field

Source = Literal["resolution", "congressional_record"]


class ResolutionRef(BaseModel):
    type: Literal["resolution"] = "resolution"
    number: str
    stage: Optional[str] = None
    agreed_to_date: Optional[str] = None
    congress_gov_url: Optional[str] = None
    govinfo_xml_url: Optional[str] = None


class RecordRef(BaseModel):
    type: Literal["congressional_record"] = "congressional_record"
    volume: Optional[str] = None
    issue: Optional[str] = None
    page: Optional[str] = None
    granule_id: Optional[str] = None
    signed_date: Optional[str] = None
    url: Optional[str] = None


SourceRef = Annotated[Union[ResolutionRef, RecordRef], Field(discriminator="type")]


class CommitteeChangeEvent(BaseModel):
    """A single committee membership change, from either source."""

    congress: str
    change_type: ChangeType
    committee: str
    system_code: Optional[str] = Field(None, description="congress.gov system code, e.g. hsfa00")
    gpo_code: Optional[str] = Field(None, description="GPO bill-XML code, e.g. HFA00")
    member_name: Optional[str] = None
    bioguide_id: Optional[str] = None
    date: Optional[str] = None
    source: Source
    source_ref: SourceRef


def to_events(record: "ResolutionRecord") -> List["CommitteeChangeEvent"]:
    """Flatten a resolution record's nested changes into unified events."""
    ref = ResolutionRef(
        number=record.number, stage=record.stage,
        agreed_to_date=record.agreed_to_date,
        congress_gov_url=record.congress_gov_url,
        govinfo_xml_url=record.govinfo_xml_url,
    )
    return [
        CommitteeChangeEvent(
            congress=record.congress, change_type=c.change_type, committee=c.committee,
            gpo_code=c.committee_code, member_name=c.member_name,
            bioguide_id=c.bioguide_id,
            date=record.agreed_to_date or record.date,
            source="resolution", source_ref=ref,
        )
        for c in record.committee_changes
    ]
```

**Step 4: Run to verify it passes**

Run: `pytest tests/test_models.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/models.py tests/test_models.py
git commit -m "feat: add unified CommitteeChangeEvent model and to_events flattening"
```

---

## Task 2: Parse a single-committee resignation granule

**Files:**
- Modify: `congress_committees/parser.py`
- Test: `tests/test_resignation_parser.py` (create)
- Fixture (exists): `tests/fixtures/CREC-2001-02-08-pt1-PgH228-resignation.txt`

**Step 1: Write the failing test**

```python
# tests/test_resignation_parser.py
"""Tests for parsing Congressional Record committee-resignation letters."""

from pathlib import Path

from congress_committees.parser import parse_resignation_granule

FIX = Path(__file__).parent / "fixtures"
INTEL = (FIX / "CREC-2001-02-08-pt1-PgH228-resignation.txt").read_text()
INTEL_TITLE = "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE"


def test_parses_single_committee_resignation():
    result = parse_resignation_granule(INTEL_TITLE, INTEL)
    assert result.committees == ["House Permanent Select Committee on Intelligence"]
    assert result.member_name == "Charles F. Bass"
    assert result.signed_date == "2001-02-07"
```

**Step 2: Run to verify it fails**

Run: `pytest tests/test_resignation_parser.py -q`
Expected: FAIL (cannot import `parse_resignation_granule`).

**Step 3: Implement minimally** — add to `congress_committees/parser.py`:

```python
from dataclasses import dataclass, field

_MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], start=1)}


@dataclass
class ResignationParse:
    committees: list = field(default_factory=list)
    member_name: Optional[str] = None
    signed_date: Optional[str] = None


def _titlecase_committee(raw: str) -> str:
    """Normalize a TITLE-cased committee phrase to canonical title case."""
    text = _clean(raw).title()
    # Fix small words that .title() over-capitalizes.
    for small in ("On", "Of", "And", "The"):
        text = re.sub(rf"\b{small}\b", small.lower(), text)
    text = text[0].upper() + text[1:]
    return text


def _split_committees(title_tail: str) -> list:
    """Split 'COMMITTEE ON A AND COMMITTEE ON B' into individual committee names."""
    parts = re.split(r"\s+AND\s+(?=COMMITTEE\b|HOUSE\b|HOUSE PERMANENT\b)", title_tail.strip())
    return [_titlecase_committee(p) for p in parts if p.strip()]


def parse_resignation_granule(title: str, text: str) -> ResignationParse:
    """Parse a CREC resignation granule (title + TXT) into structured fields."""
    result = ResignationParse()

    m = re.search(r"RESIGNATION AS MEMBER OF\s+(.*)", _clean(title), re.IGNORECASE)
    if m:
        result.committees = _split_committees(m.group(1))

    flat = _clean(text)

    # Signed date from the dateline: "Washington, DC, February 7, 2001."
    d = re.search(r"Washington, DC,\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", flat)
    if d:
        month = _MONTHS.get(d.group(1))
        if month:
            result.signed_date = f"{d.group(3)}-{month:02d}-{int(d.group(2)):02d}"

    # Signature: the name line between 'Sincerely,' and 'Member of Congress.'
    s = re.search(r"Sincerely,\s+(.+?),\s+Member of Congress", flat)
    if s:
        result.member_name = _clean(s.group(1))

    return result
```

**Step 4: Run to verify it passes**

Run: `pytest tests/test_resignation_parser.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/parser.py tests/test_resignation_parser.py
git commit -m "feat: parse single-committee Congressional Record resignation letters"
```

---

## Task 3: Multi-committee granule splitting

**Files:**
- Create: `tests/fixtures/CREC-2001-02-08-multi-resignation.txt`
- Modify: `tests/test_resignation_parser.py`

**Step 1: Create the synthetic fixture** `tests/fixtures/CREC-2001-02-08-multi-resignation.txt`:

```
[Page H228]
     RESIGNATION AS MEMBER OF COMMITTEE ON AGRICULTURE AND COMMITTEE
                            ON RESOURCES
  The SPEAKER pro tempore laid before the House the following
resignation as a member of the Committee on Agriculture and the
Committee on Resources:
                                 Washington, DC, February 7, 2001.
     Hon. Dennis Hastert,
     Speaker, House of Representatives,
       Dear Speaker Hastert: I hereby resign from the Committee on
     Agriculture and the Committee on Resources.
           Sincerely,
                                                  Jane Q. Member,
                                               Member of Congress.
```

**Step 2: Write the failing test** — add to `tests/test_resignation_parser.py`:

```python
MULTI = (FIX / "CREC-2001-02-08-multi-resignation.txt").read_text()
MULTI_TITLE = "RESIGNATION AS MEMBER OF COMMITTEE ON AGRICULTURE AND COMMITTEE ON RESOURCES"


def test_parses_multi_committee_resignation():
    result = parse_resignation_granule(MULTI_TITLE, MULTI)
    assert result.committees == ["Committee on Agriculture", "Committee on Resources"]
    assert result.member_name == "Jane Q. Member"
```

**Step 3: Run to verify it fails**

Run: `pytest tests/test_resignation_parser.py::test_parses_multi_committee_resignation -q`
Expected: FAIL (committees not split, or title-case off). Adjust `_split_committees`/`_titlecase_committee` regex until it passes (the split anchor already handles `AND COMMITTEE`; verify "Committee on Resources" casing).

**Step 4: Run to verify it passes**

Run: `pytest tests/test_resignation_parser.py -q` → PASS (both tests).

**Step 5: Commit**

```bash
git add tests/fixtures/CREC-2001-02-08-multi-resignation.txt tests/test_resignation_parser.py
git commit -m "feat: split multi-committee resignation granules into separate committees"
```

---

## Task 4: Congress↔date mapping helper

**Files:**
- Create: `congress_committees/dates.py`
- Test: `tests/test_dates.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_dates.py
from congress_committees.dates import congress_date_span


def test_congress_date_span():
    assert congress_date_span(107) == ("2001-01-03", "2003-01-03")
    assert congress_date_span(119) == ("2025-01-03", "2027-01-03")
```

**Step 2: Run to verify it fails** — `pytest tests/test_dates.py -q` → FAIL.

**Step 3: Implement** `congress_committees/dates.py`:

```python
"""Congress-number ↔ calendar-date helpers."""

from typing import Tuple


def congress_date_span(congress: int) -> Tuple[str, str]:
    """Return (start, end) ISO dates for a Congress. Congress 1 began 1789-01-03."""
    start_year = 1789 + (congress - 1) * 2
    return f"{start_year}-01-03", f"{start_year + 2}-01-03"
```

**Step 4: Run to verify it passes** — `pytest tests/test_dates.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/dates.py tests/test_dates.py
git commit -m "feat: add congress-number to date-span mapping"
```

---

## Task 5: Full-name + date bioguide lookup

**Files:**
- Modify: `congress_committees/legislators.py`
- Test: `tests/test_legislators.py` (extend)
- Fixture: extend `tests/fixtures/legislators-sample.yaml`

**Step 1: Inspect** `congress_committees/legislators.py` (`_Candidate`, `from_records`, `lookup`) and `tests/fixtures/legislators-sample.yaml` to learn the current shape before changing it.

**Step 2: Extend the fixture** — ensure `legislators-sample.yaml` includes a record usable for full-name+date matching, e.g. Charles Bass with a term spanning 2001:

```yaml
- id:
    bioguide: B000220
  name:
    first: Charles
    last: Bass
  terms:
    - type: rep
      start: "1995-01-04"
      end: "2007-01-03"
      state: NH
```

(Keep the existing Gallagher record used by other tests.)

**Step 3: Write the failing test** — add to `tests/test_legislators.py`:

```python
def test_lookup_full_name_with_date(tmp_path):
    from pathlib import Path
    from congress_committees.legislators import LegislatorIndex
    idx = LegislatorIndex.from_yaml_files([Path(__file__).parent / "fixtures" / "legislators-sample.yaml"])
    assert idx.lookup_full_name("Charles", "Bass", "2001-02-08") == "B000220"
    # No one named that serving in 1990 -> None
    assert idx.lookup_full_name("Charles", "Bass", "1990-01-01") is None
```

**Step 4: Run to verify it fails** — `pytest tests/test_legislators.py::test_lookup_full_name_with_date -q` → FAIL.

**Step 5: Implement** — extend `_Candidate` to carry `first` name and a list of `(start, end)` term ranges, populate them in `from_records`, and add:

```python
def lookup_full_name(self, first: str, last: str, on_date: Optional[str] = None) -> Optional[str]:
    """Resolve a signer to a bioguide by surname, active-on-date, then first name.

    Returns the bioguide only when exactly one candidate matches confidently.
    """
    candidates = self._by_surname.get(_norm_surname(last), [])
    if on_date:
        candidates = [c for c in candidates if c.served_on(on_date)]
    if first:
        fl = first.strip().lower()
        narrowed = [c for c in candidates if c.first and c.first.lower().startswith(fl[:1])
                    and (c.first.lower() == fl or fl.startswith(c.first.lower()) or c.first.lower().startswith(fl))]
        if narrowed:
            candidates = narrowed
    return candidates[0].bioguide if len(candidates) == 1 else None
```

Add a `served_on(date)` method to `_Candidate` (true if any term range contains `date`). Reuse the existing surname-normalization helper (match whatever `lookup` already uses; create `_norm_surname` only if one doesn't already exist).

**Step 6: Run to verify it passes** — `pytest tests/test_legislators.py -q` → PASS (all, including pre-existing tests).

**Step 7: Commit**

```bash
git add congress_committees/legislators.py tests/test_legislators.py tests/fixtures/legislators-sample.yaml
git commit -m "feat: add full-name + date bioguide lookup to LegislatorIndex"
```

---

## Task 6: CommitteeIndex (name + history → system_code)

**Files:**
- Create: `congress_committees/committees.py`
- Test: `tests/test_committees.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_committees.py
from congress_committees.committees import CommitteeIndex

RECORDS = [
    {"systemCode": "hsfa00", "name": "Foreign Affairs Committee",
     "previous_names": ["Committee on International Relations"]},
    {"systemCode": "hsii00", "name": "Natural Resources Committee",
     "previous_names": ["Committee on Resources"]},
    {"systemCode": "hlig00", "name": "Permanent Select Committee on Intelligence",
     "previous_names": []},
]


def test_resolves_current_name():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("Committee on Foreign Affairs") == "hsfa00"


def test_resolves_previous_name():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("Committee on Resources") == "hsii00"
    assert idx.code_for("Committee on International Relations") == "hsfa00"


def test_resolves_intelligence_variant():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("House Permanent Select Committee on Intelligence") == "hlig00"


def test_unknown_returns_none():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("Committee on Nonexistent Things") is None
```

**Step 2: Run to verify it fails** — `pytest tests/test_committees.py -q` → FAIL.

**Step 3: Implement** `congress_committees/committees.py`:

```python
"""Map committee names (current and historical) to congress.gov system codes."""

import re
from typing import Dict, List, Optional


def _normalize(name: str) -> str:
    """Normalize a committee name for matching: lowercase core words only."""
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
```

Note: `_normalize("Foreign Affairs Committee")` and `_normalize("Committee on Foreign Affairs")` both reduce to `"foreign affairs"`, so the current-name entry matches the printed form. Verify in tests; tune `_normalize` if a case fails.

**Step 4: Run to verify it passes** — `pytest tests/test_committees.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/committees.py tests/test_committees.py
git commit -m "feat: add CommitteeIndex mapping names+history to system codes"
```

---

## Task 7: CongressGovClient.list_committees()

**Files:**
- Modify: `congress_committees/api.py`
- Test: `tests/test_api.py` (extend)

**Step 1: Write the failing test** — add to `tests/test_api.py`:

```python
COMMITTEES = {
    "committees": [
        {"systemCode": "hsfa00", "name": "Foreign Affairs Committee", "chamber": "House"},
        {"systemCode": "hsii00", "name": "Natural Resources Committee", "chamber": "House"},
    ]
}


def test_list_committees_parses():
    def handler(request):
        assert "/committee/house" in str(request.url)
        return httpx.Response(200, json=COMMITTEES)
    client = CongressGovClient("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    recs = client.list_committees("house")
    assert {r["systemCode"] for r in recs} == {"hsfa00", "hsii00"}
```

**Step 2: Run to verify it fails** — `pytest tests/test_api.py::test_list_committees_parses -q` → FAIL.

**Step 3: Implement** — add to `CongressGovClient`:

```python
def list_committees(self, chamber: str = "house") -> List[dict]:
    """Return committee records (systemCode + name) for a chamber."""
    payload = self._get(f"/committee/{chamber}", limit=self.page_size)
    return payload.get("committees", [])
```

(Pagination beyond `page_size` and per-committee name-history enrichment are a follow-up; the current chamber list is well under one page. If name history is needed live, enrich via `/committee/{chamber}/{systemCode}` `history` — covered by the live test in Task 11.)

**Step 4: Run to verify it passes** — `pytest tests/test_api.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/api.py tests/test_api.py
git commit -m "feat: add list_committees to congress.gov client"
```

---

## Task 8: CRECClient — discovery + granule fetch

**Files:**
- Create: `congress_committees/congressional_record.py`
- Test: `tests/test_congressional_record.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_congressional_record.py
"""Tests for the GovInfo CREC client (discovery + granule fetch) via MockTransport."""

import httpx

from congress_committees.congressional_record import CRECClient

COLLECTIONS = {"packages": [{"packageId": "CREC-2001-02-08", "dateIssued": "2001-02-08"}],
               "nextPage": None}
GRANULES = {"granules": [
    {"granuleId": "CREC-2001-02-08-pt1-PgH228",
     "title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE",
     "granuleClass": "HOUSE"},
    {"granuleId": "CREC-2001-02-08-pt1-PgH200",
     "title": "PROVIDING FOR CONSIDERATION OF H.R. 9", "granuleClass": "HOUSE"},
], "nextPage": None}
SUMMARY = {"title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE",
           "granuleId": "CREC-2001-02-08-pt1-PgH228",
           "download": {"txtLink": "https://api.govinfo.gov/.../granule.txt"},
           "detailsLink": "https://www.govinfo.gov/app/details/CREC-2001-02-08"}
GRANULE_TEXT = "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE ..."


def _handler(request):
    url = str(request.url)
    if "/collections/CREC/" in url:
        return httpx.Response(200, json=COLLECTIONS)
    if url.endswith("/granules") or "/granules?" in url:
        return httpx.Response(200, json=GRANULES)
    if "/summary" in url:
        return httpx.Response(200, json=SUMMARY)
    if url.endswith(".txt"):
        return httpx.Response(200, text=GRANULE_TEXT)
    return httpx.Response(404)


def _client():
    return CRECClient("KEY", client=httpx.Client(transport=httpx.MockTransport(_handler)))


def test_discovery_keeps_only_resignation_granules():
    granules = _client().discover_resignations("2001-02-08", "2001-02-09")
    assert [g["granuleId"] for g in granules] == ["CREC-2001-02-08-pt1-PgH228"]


def test_fetch_granule_text_and_meta():
    text, meta = _client().fetch_granule("CREC-2001-02-08", "CREC-2001-02-08-pt1-PgH228")
    assert "RESIGNATION" in text
    assert meta["url"].endswith("CREC-2001-02-08")
```

**Step 2: Run to verify it fails** — `pytest tests/test_congressional_record.py -q` → FAIL.

**Step 3: Implement** `congress_committees/congressional_record.py`:

```python
"""GovInfo CREC (Congressional Record) client: discover committee-resignation
granules over a date range and fetch their text.

GovInfo is fronted by api.data.gov; the congress.gov API key usually works.
Falls back to GOVINFO_API_KEY if set.
"""

import os
import re
from typing import List, Optional, Tuple

import httpx

GOVINFO_API = "https://api.govinfo.gov"
_RESIGNATION_TITLE = re.compile(r"RESIGNATION AS MEMBER OF .*COMMITTEE", re.IGNORECASE)


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
        params["api_key"] = self.api_key
        resp = self._client.get(url, params=params)
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
            params = {}  # nextPage is fully-qualified

    def list_packages(self, start: str, end: str) -> List[dict]:
        url = f"{self.base_url}/collections/CREC/{start}T00:00:00Z/{end}T00:00:00Z"
        return list(self._paged(url, "packages"))

    def discover_resignations(self, start: str, end: str) -> List[dict]:
        """Return resignation granules across CREC packages in [start, end)."""
        found = []
        for pkg in self.list_packages(start, end):
            pid = pkg["packageId"]
            url = f"{self.base_url}/packages/{pid}/granules"
            for g in self._paged(url, "granules"):
                if _RESIGNATION_TITLE.search(g.get("title", "")):
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
        if txt_link:
            resp = self._client.get(txt_link, params={"api_key": self.api_key})
            if resp.status_code == 200:
                text = resp.text
        page = None
        m = re.search(r"Pg([A-Z]\d+)", granule_id)
        if m:
            page = m.group(1)
        meta = {"granule_id": granule_id, "page": page,
                "url": summary.get("detailsLink") or f"https://www.govinfo.gov/app/details/{package_id}"}
        return text, meta
```

**Step 4: Run to verify it passes** — `pytest tests/test_congressional_record.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/congressional_record.py tests/test_congressional_record.py
git commit -m "feat: add GovInfo CREC client for resignation discovery and fetch"
```

---

## Task 9: Resignation collector → unified events

**Files:**
- Create: `congress_committees/resignations.py`
- Test: `tests/test_resignations.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_resignations.py
"""End-to-end resignation collection with injected fakes (no network)."""

from pathlib import Path

from congress_committees.committees import CommitteeIndex
from congress_committees.legislators import LegislatorIndex
from congress_committees.resignations import collect_resignations

FIX = Path(__file__).parent / "fixtures"
INTEL_TEXT = (FIX / "CREC-2001-02-08-pt1-PgH228-resignation.txt").read_text()

COMMITTEE_RECORDS = [
    {"systemCode": "hlig00", "name": "Permanent Select Committee on Intelligence",
     "previous_names": []},
]


class FakeCREC:
    def discover_resignations(self, start, end):
        return [{"granuleId": "CREC-2001-02-08-pt1-PgH228", "packageId": "CREC-2001-02-08",
                 "title": "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE"}]

    def fetch_granule(self, package_id, granule_id):
        return INTEL_TEXT, {"granule_id": granule_id, "page": "H228",
                            "url": "https://www.govinfo.gov/app/details/CREC-2001-02-08"}


def _collect():
    committees = CommitteeIndex.from_records(COMMITTEE_RECORDS)
    legislators = LegislatorIndex.from_yaml_files([FIX / "legislators-sample.yaml"])
    return collect_resignations(
        congress=107, client=FakeCREC(), start="2001-02-08", end="2001-02-09",
        committees=committees, legislators=legislators,
    )


def test_collect_resignations_emits_removal_event():
    events = _collect()
    assert len(events) == 1
    ev = events[0]
    assert ev.change_type == "removal"
    assert ev.committee == "House Permanent Select Committee on Intelligence"
    assert ev.system_code == "hlig00"
    assert ev.gpo_code is None
    assert ev.member_name == "Charles F. Bass"
    assert ev.bioguide_id == "B000220"
    assert ev.source == "congressional_record"
    assert ev.source_ref.type == "congressional_record"
    assert ev.source_ref.page == "H228"
    assert ev.date == "2001-02-08"
```

**Step 2: Run to verify it fails** — `pytest tests/test_resignations.py -q` → FAIL.

**Step 3: Implement** `congress_committees/resignations.py`:

```python
"""Collect committee resignations from Congressional Record granules into events."""

import logging
import re
from typing import List, Optional

from .committees import CommitteeIndex
from .legislators import LegislatorIndex
from .models import CommitteeChangeEvent, RecordRef
from .parser import parse_resignation_granule

logger = logging.getLogger(__name__)


def _split_name(full: Optional[str]):
    if not full:
        return "", ""
    parts = _strip = re.sub(r"\s+", " ", full).strip().split(" ")
    return parts[0], parts[-1]


def _issue_date_from_package(package_id: str) -> Optional[str]:
    m = re.search(r"CREC-(\d{4})-(\d{2})-(\d{2})", package_id or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def collect_resignations(
    *, congress: int, client, start: str, end: str,
    committees: Optional[CommitteeIndex] = None,
    legislators: Optional[LegislatorIndex] = None,
) -> List[CommitteeChangeEvent]:
    events: List[CommitteeChangeEvent] = []
    for granule in client.discover_resignations(start, end):
        gid = granule["granuleId"]
        pid = granule.get("packageId", "")
        text, meta = client.fetch_granule(pid, gid)
        parsed = parse_resignation_granule(granule.get("title", ""), text)
        if not parsed.member_name:
            logger.warning("No signer parsed for granule %s", gid)
        issue_date = _issue_date_from_package(pid)
        first, last = _split_name(parsed.member_name)
        bioguide = (legislators.lookup_full_name(first, last, issue_date)
                    if legislators and parsed.member_name else None)
        ref = RecordRef(granule_id=gid, page=meta.get("page"),
                        signed_date=parsed.signed_date, url=meta.get("url"))
        for committee in parsed.committees or [None]:
            system_code = committees.code_for(committee) if (committees and committee) else None
            events.append(CommitteeChangeEvent(
                congress=str(congress), change_type="removal",
                committee=committee or "", system_code=system_code,
                member_name=parsed.member_name, bioguide_id=bioguide,
                date=issue_date, source="congressional_record", source_ref=ref,
            ))
    return events
```

**Step 4: Run to verify it passes** — `pytest tests/test_resignations.py -q` → PASS.

**Step 5: Commit**

```bash
git add congress_committees/resignations.py tests/test_resignations.py
git commit -m "feat: collect Congressional Record resignations into unified events"
```

---

## Task 10: Unify the resolution collector output

**Files:**
- Modify: `congress_committees/collector.py`
- Test: `tests/test_collector.py` (extend)

**Step 1: Write the failing test** — add to `tests/test_collector.py`:

```python
def test_collect_emits_unified_events():
    from congress_committees.collector import collect_committee_change_events
    events = collect_committee_change_events(
        119, client=FakeClient(), gpo_fetch=fake_gpo_fetch,
        legislators=LegislatorIndex.from_yaml_files([FIXTURES / "legislators-sample.yaml"]),
    )
    assert all(e.source == "resolution" for e in events)
    assert {e.change_type for e in events} == {"addition"}
    assert any(e.gpo_code for e in events)
```

**Step 2: Run to verify it fails** — `pytest tests/test_collector.py::test_collect_emits_unified_events -q` → FAIL.

**Step 3: Implement** — add a thin wrapper to `collector.py` (keep `collect_committee_changes` returning records for the existing tests):

```python
from .models import CommitteeChangeEvent, to_events


def collect_committee_change_events(congress: int, **kwargs) -> List[CommitteeChangeEvent]:
    """Resolution path, flattened to unified events."""
    records = collect_committee_changes(congress, **kwargs)
    events: List[CommitteeChangeEvent] = []
    for record in records:
        events.extend(to_events(record))
    return events
```

**Step 4: Run to verify it passes** — `pytest tests/test_collector.py -q` → PASS (all).

**Step 5: Commit**

```bash
git add congress_committees/collector.py tests/test_collector.py
git commit -m "feat: flatten resolution collector output to unified events"
```

---

## Task 11: CLI — unified output across both sources

**Files:**
- Modify: `congress_committees/cli.py`
- Test: `tests/test_cli.py` (create or extend)

**Step 1: Inspect** `congress_committees/cli.py` for the current argument parsing, client/legislators construction, and JSON writing, so the new flags slot into the existing structure.

**Step 2: Write the failing test** — assert argument parsing and source selection without network. Build a `parse_args`-style test:

```python
# tests/test_cli.py
from congress_committees.cli import build_arg_parser


def test_source_flag_defaults_to_all():
    args = build_arg_parser().parse_args(["--congress", "119"])
    assert args.source == "all"


def test_source_flag_accepts_record():
    args = build_arg_parser().parse_args(["--congress", "119", "--source", "record"])
    assert args.source == "record"
```

(If `cli.py` builds its parser inline in `main()`, refactor it into a `build_arg_parser()` function first — that is the minimal change this test drives.)

**Step 3: Run to verify it fails** — `pytest tests/test_cli.py -q` → FAIL.

**Step 4: Implement** — in `cli.py`:
- Extract `build_arg_parser()`; add `--source {resolution,record,all}` (default `all`), `--no-committee-codes`.
- In `main()`:
  - Build `events: List[CommitteeChangeEvent] = []`.
  - If source in (`resolution`, `all`): `events += collect_committee_change_events(...)`.
  - If source in (`record`, `all`):
    - Resolve date range: `start = args.since or congress_date_span(args.congress)[0]`; `end = congress_date_span(args.congress)[1]` (or today for ongoing — acceptable to use the span end).
    - Build `CommitteeIndex` from `CongressGovClient.list_committees("house")` unless `--no-committee-codes`.
    - `events += collect_resignations(congress=..., client=CRECClient.from_env(), start=start, end=end, committees=..., legislators=...)`.
  - Serialize `[e.model_dump() for e in events]` to the out path (unchanged writing logic).

**Step 5: Run to verify it passes** — `pytest tests/test_cli.py -q` → PASS. Then full suite: `pytest -q` → all PASS.

**Step 6: Commit**

```bash
git add congress_committees/cli.py tests/test_cli.py
git commit -m "feat: unify CLI output across resolution and resignation sources"
```

---

## Task 12: Live integration tests

**Files:**
- Modify: `tests/test_live.py`

**Step 1: Add live tests** (marked via existing `pytestmark = pytest.mark.live` + `requires_key`):

```python
def test_live_committees_index_resolves_foreign_affairs(client):
    from congress_committees.committees import CommitteeIndex
    idx = CommitteeIndex.from_records(client.list_committees("house"))
    assert idx.code_for("Committee on Foreign Affairs") == "hsfa00"


def test_live_crec_finds_bass_intelligence_resignation():
    from congress_committees.congressional_record import CRECClient
    from congress_committees.parser import parse_resignation_granule
    crec = CRECClient.from_env()
    granules = crec.discover_resignations("2001-02-08", "2001-02-09")
    intel = [g for g in granules if "INTELLIGENCE" in g["title"].upper()]
    assert intel, "expected the Feb 8 2001 Intelligence resignation"
    text, meta = crec.fetch_granule(intel[0]["packageId"], intel[0]["granuleId"])
    parsed = parse_resignation_granule(intel[0]["title"], text)
    assert parsed.member_name == "Charles F. Bass"
    assert meta["page"] == "H228"
```

**Step 2: Verify offline suite still excludes them** — `pytest -q` → live deselected, all PASS. Then (where the key is set) `pytest -m live` → all PASS. If `CONGRESS_GOV_API_KEY` is rejected by `api.govinfo.gov`, note it and set `GOVINFO_API_KEY`; if the committees code differs from `hsfa00`, correct the assertion to the live value.

**Step 3: Commit**

```bash
git add tests/test_live.py
git commit -m "test: add live CREC resignation and committees-API integration tests"
```

---

## Task 13: Update README

**Files:**
- Modify: `README.md`

**Step 1:** Document the resignation path: the unified `CommitteeChangeEvent` output shape (with `source`, `system_code`/`gpo_code`, `source_ref`), the `--source` flag, the GovInfo CREC source, and the `GOVINFO_API_KEY` fallback. Update the "How it works" and "Output" sections to reflect the unified event stream. Note resignations come from Congressional Record letters, not resolutions.

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document committee resignation ingestion and unified output"
```

---

## Verification checklist (after all tasks)

- `pytest -q` → all offline tests pass; `live` deselected.
- `pytest -m live` (with key set) → live tests pass.
- Manual smoke: `congress-committees --congress 107 --source record --since 2001-02-08` produces resignation events (subject to the span end; use a narrow range for a quick check).
- @superpowers:verification-before-completion before claiming done.
