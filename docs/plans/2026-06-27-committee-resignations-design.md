# Committee Resignation Ingestion — Design

**Date:** 2026-06-27
**Status:** Approved (pending implementation plan)

## Problem

The project currently extracts committee membership **additions** from House
resolutions (e.g. "Electing a Member to certain standing committees…") via the
congress.gov `/bill/hres` API + GPO bill XML. It does **not** capture committee
**resignations**, because resignations are not resolutions: a member's
resignation is submitted as a **letter laid before the House and printed in the
Congressional Record**, not as a bill.

Example — Congressional Record Vol. 147, No. 18 (Feb 8, 2001), page H228:

```
     RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON
                              INTELLIGENCE
  The SPEAKER pro tempore (Mr. Ryan of Wisconsin) laid before the House
the following resignation as a member of the House Permanent Select
Committee on Intelligence:
                                 Washington, DC, February 7, 2001.
     Hon. Dennis Hastert,
     Speaker, House of Representatives,
       Dear Speaker Hastert: Please accept my resignation from the
     House Permanent Select Committee on Intelligence. ...
           Sincerely,
                                                  Charles F. Bass,
                                               Member of Congress.
```

The existing `resign…`/`discharg…`/`remov…` patterns in `classify_title` only
fire on *resolution titles*, so this document type never enters the pipeline.

## Goals & scope

- Add a **second ingestion path** for committee resignations sourced from the
  Congressional Record.
- Support **both** historical backfill (date or Congress range) and **ongoing
  monitoring** (incremental `--since` polling), sharing one parser.
- Emit into a **unified change stream** alongside resolution-based additions.
- Resolve committee codes and member bioguide IDs **best-effort**.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Scope | Both backfill and ongoing monitoring, shared parser |
| Output shape | Unified flat change-event stream with a `source` field |
| Committee codes | Carry **both** `system_code` (congress.gov) and `gpo_code` (GPO XML), best-effort |
| Bioguide match | Full-name + date-of-issue match |
| Discovery source | GovInfo `CREC` granules (Approach A), bulk-data as no-key fallback |

## Architecture

New modules mirror the existing resolution path:

| Existing (resolutions) | New (resignations) | Role |
|---|---|---|
| `api.py` (congress.gov client) | `congressional_record.py` (`CRECClient`) | HTTP: discover CREC granules in a date range, fetch granule TXT |
| `gpo.py` (bill XML fetch) | *(folded into `congressional_record.py`)* | — |
| `parser.py: parse_resolution_xml` | `parser.py: parse_resignation_granule(title, text)` | Pure, offline-testable parsing |

Network access lives in `congressional_record.py`; letter parsing is a pure
function in `parser.py` so it is unit-testable against the fixture with no mocks.

Two supporting indexes (both cached like the existing legislators data):

- **`CommitteeIndex`** — built from the **congress.gov committees API**
  (`list_committees()`, new method on `CongressGovClient`). Maps normalized
  committee name **and historical previous names** → `system_code` (`hsfa00`).
  The API's name `history`/`previousNames` handles renames (e.g. "Committee on
  Resources" → "Committee on Natural Resources", "Committee on International
  Relations" → "Foreign Affairs", "Committee on Government Reform" →
  "Oversight").
- **`LegislatorIndex`** (extended) — add first-name indexing and term date
  ranges; new `lookup_full_name(first, last, on_date)`.

## Data flow (resignation path)

1. **Discover** — `CRECClient` queries the GovInfo *collections* endpoint for
   `CREC` packages over a date range (`--since`→today, or a Congress's date
   span for backfill), lists each package's granules, and keeps those whose
   **title** matches `RESIGNATION AS MEMBER OF … COMMITTEE`. Title-only — no body
   fetch for discovery.
2. **Parse** — fetch TXT for matched granules; `parse_resignation_granule`
   extracts committee name(s), signer full name, and dates.
3. **Enrich** — `CommitteeIndex` → `system_code` (best-effort);
   `LegislatorIndex.lookup_full_name` → `bioguide_id` (best-effort).
4. **Flatten** — build `CommitteeChangeEvent`s.

Both pipelines converge on `List[CommitteeChangeEvent]`, which the CLI
serializes.

### Congress ↔ date mapping (backfill by Congress)

`start_year = 1789 + (congress - 1) * 2`; span = Jan 3 of that year to Jan 3 two
years later. (107th → 2001–2003; 119th → 2025–2027.)

### GovInfo key reuse

`CRECClient.from_env()` tries `CONGRESS_GOV_API_KEY` against `api.govinfo.gov`
(same api.data.gov key family). If GovInfo rejects it, fall back to optional
`GOVINFO_API_KEY`; last resort is the no-key bulk-data route
(`govinfo.gov/bulkdata/CREC/`).

## Output model (`models.py`)

Existing `CommitteeChange`, `BillAction`, `ResolutionRecord` are retained as the
resolution path's **internal parse products** (existing parser/tests untouched).
The **output** type becomes a flat list of change events:

```jsonc
{
  "congress": "107",
  "change_type": "removal",                 // addition | removal
  "committee": "House Permanent Select Committee on Intelligence",
  "system_code": null,                       // hsfa00-style, congress.gov; best-effort
  "gpo_code": null,                          // HFA00-style, GPO XML; resolution path only
  "member_name": "Charles F. Bass",
  "bioguide_id": "B000220",
  "date": "2001-02-08",                      // laid before / agreed to
  "source": "congressional_record",          // resolution | congressional_record
  "source_ref": {                            // typed union, discriminated on `type`
    "type": "congressional_record",
    "volume": "147", "issue": "18", "page": "H228",
    "granule_id": "CREC-2001-02-08-pt1-PgH228",
    "signed_date": "2001-02-07",
    "url": "https://www.govinfo.gov/app/details/CREC-2001-02-08/..."
  }
}
```

For a resolution-sourced event: `source: "resolution"`, and `source_ref` is a
`ResolutionRef` carrying `{type: "resolution", number, stage, agreed_to_date,
congress_gov_url, govinfo_xml_url}`.

- `gpo_code` populated natively from GPO bill XML (resolution path); null for
  resignations.
- `system_code` populated best-effort via `CommitteeIndex` name lookup on **both**
  paths (a lookup, not a lossy code transform).
- `to_events(record)` flattens a `ResolutionRecord`'s nested changes into events;
  the resignation path builds events directly.
- `source_ref` is a typed pydantic union (`ResolutionRef | RecordRef`)
  discriminated on `type`.

## CLI (`cli.py`)

- Default run emits the unified event stream from **both** sources.
- `--source {resolution,record,all}` (default `all`).
- Record discovery range: `--since`→today, or the Congress's full span when no
  `--since`.
- Retain `--congress`, `--out`, `--legislators-path`, `--no-bioguide`, `-v`; add
  `--no-committee-codes` to skip the committees-API fetch.
- Default out: `output/committee_changes_<congress>.json` (now unified events).

## Error handling

Best-effort throughout — nothing silently dropped:

- GovInfo auth: try `CONGRESS_GOV_API_KEY` → `GOVINFO_API_KEY` → bulk-data
  fallback, clear message if all fail.
- Granule fetch failure → log + skip that granule.
- Letter body unparseable (no signature block) → still emit committee + date
  from the title/issue with `member_name=null` + warning.
- Committee name not resolvable → `system_code=null` + warning.
- Bioguide ambiguous/none → `bioguide_id=null` + warning.

## Testing

**Offline units**
- `parse_resignation_granule` vs. saved fixture
  (`tests/fixtures/CREC-2001-02-08-pt1-PgH228-resignation.txt`) → Intelligence,
  "Charles F. Bass", signed 2001-02-07.
- Synthetic multi-committee fixture (Agriculture AND Resources) → 2 events.
- `CommitteeIndex` name + previous-name → code, including a rename case
  ("Committee on Resources").
- `LegislatorIndex.lookup_full_name` (Bass, 107th → bioguide).
- `to_events` flattening of a `ResolutionRecord`.

**Offline integration**
- `CRECClient` discovery + granule fetch via `httpx.MockTransport`
  (collections JSON + granules JSON + granule text).
- Record-path collector end-to-end with injected fakes → unified events.

**Live (marked `live`, skipped without key)**
- GovInfo discovery + parse for stable historical issue `CREC-2001-02-08`,
  asserting the Bass/Intelligence resignation is found and parsed.
- congress.gov committees-API `CommitteeIndex` smoke test.

## Out of scope / future

- GovInfo Search API as a discovery optimization (fewer calls than the
  collections+granules walk).
- Senate committee resignations.
- Discharge/removal *resolutions* (a separate, rarer document type).
