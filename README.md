# congress-committees

Extract House committee membership **changes** — both additions and resignations —
into a single structured JSON stream of change events.

Two kinds of change reach the House from two different documents, so there are two
ingestion paths feeding one unified output:

- **Additions** come from **House resolutions** (e.g.
  [H. Res. 1381](https://www.congress.gov/bill/119th-congress/house-resolution/1381),
  "Electing a Member to certain standing committees…"), discovered via the
  **congress.gov API** and parsed from the **GPO govinfo bill XML**.
- **Resignations** come from **letters printed in the Congressional Record** (the
  Speaker laying a member's resignation before the House), discovered and parsed
  from **GPO govinfo `CREC` granules**.

Both paths resolve members to **bioguide IDs** using the
[unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators)
datasets, and emit a flat list of `addition`/`removal` events tagged by `source`.
Tested against every Congress from the **103rd through the 119th** (1993–present).

## How it works

**Resolution path (additions):**

1. **Discover** — list House resolutions for a Congress via the congress.gov API and
   keep those whose title marks a committee change (`Electing… committees`, etc.).
2. **Parse** — fetch each resolution's GPO bill text and read every committee's
   member list. From the **110th Congress on**, GPO publishes real bill XML
   (`BILLS-<congress>hres<number><stage>`), so parsing reads each
   `<committee-appointment-paragraph>` directly: committee name, `committee-id`
   code (the GPO code, e.g. `HFA00`), and member. **Before the 110th**, GPO never
   digitized bill XML — only a plain-text rendition exists, so a separate
   text-mode parser reads the same information out of prose.
3. **Enrich** — pull the resolution's actions and derive the `agreed_to_date`;
   resolve each member to a bioguide ID.

**Congressional Record path (resignations):**

1. **Discover** — list `CREC` packages issued in a date range via the govinfo
   **`/published`** endpoint, then keep granules titled
   `RESIGNATION(S) AS MEMBER(S) OF … COMMITTEE`. GovInfo's Congressional Record
   digitization starts in **1994** — nothing before that date is available at
   all, regardless of what this tool does.
2. **Parse** — fetch each granule's text and read the committee name(s) (one
   granule can name several), the signer, and the letter's date.
3. **Enrich** — resolve the signer to a bioguide ID by full name + the issue date;
   look up the congress.gov committee **system code** (e.g. `hsfa00`) by name.

Both paths converge on a single list of **change events** (see [Output](#output)).

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras
```

## Configuration

| Variable | Required | Purpose |
|----------|----------|---------|
| `CONGRESS_GOV_API_KEY` | yes | api.data.gov key ([free signup](https://api.congress.gov)). Used for congress.gov **and** govinfo (`CREC`) — the same key works for both. |
| `GOVINFO_API_KEY` | no | Fallback key for govinfo if `CONGRESS_GOV_API_KEY` is unset. |
| `CONGRESS_LEGISLATORS_PATH` | no | Path to a congress-legislators YAML file or directory. If unset, the datasets are downloaded once to `.cache/`. |

## Usage

```bash
export CONGRESS_GOV_API_KEY=...
uv run congress-committees --congress 119 --since 2026-06-20
# -> output/committee_changes_119.json
```

Options:

| Option | Purpose |
|--------|---------|
| `--congress N` | Congress number, e.g. `119` (required). |
| `--source {resolution,record,all}` | Which path(s) to run. Default `all`. |
| `--since YYYY-MM-DD` | Lower time bound for **both** sources: an "updated on/after" filter for resolutions, and the start of the date-range walk for the Congressional Record. Omit to cover the Congress's full span. |
| `--out PATH` | Output JSON path (default `output/committee_changes_<congress>.json`). |
| `--legislators-path PATH` | congress-legislators YAML file/dir. |
| `--no-bioguide` | Skip bioguide resolution. |
| `--no-committee-codes` | Skip the congress.gov committees lookup (leaves `system_code` null). |
| `-v` | Verbose logging. |

Run it on a schedule (cron, etc.) with a moving `--since` watermark to capture new
committee changes as they appear. `.github/workflows/check-congressional-record.yml`
does exactly this: a daily GitHub Actions run that checks for new events since its
last watermark and opens an issue only when it finds any.

## Output

A flat JSON list of committee-change events. Each event is tagged with its
`source` and carries a typed `source_ref`. Committee codes are populated from
whichever source has them natively: `gpo_code` (`HFA00`-style) on resolution
events, `system_code` (`hsfa00`-style, best-effort) on resignation events.

```json
[
  {
    "congress": "119",
    "change_type": "addition",
    "committee": "Committee on Foreign Affairs",
    "system_code": null,
    "gpo_code": "HFA00",
    "member_name": "Mr. Gallagher",
    "bioguide_id": "G000587",
    "date": "2026-06-24",
    "source": "resolution",
    "source_ref": {
      "type": "resolution",
      "number": "1381",
      "stage": "Engrossed-in-House",
      "agreed_to_date": "2026-06-24",
      "congress_gov_url": "https://www.congress.gov/bill/119th-congress/house-resolution/1381",
      "govinfo_xml_url": "https://www.govinfo.gov/content/pkg/BILLS-119hres1381eh/xml/BILLS-119hres1381eh.xml"
    }
  },
  {
    "congress": "107",
    "change_type": "removal",
    "committee": "House Permanent Select Committee on Intelligence",
    "system_code": "hlig00",
    "gpo_code": null,
    "member_name": "Charles F. Bass",
    "bioguide_id": "B000220",
    "date": "2001-02-08",
    "source": "congressional_record",
    "source_ref": {
      "type": "congressional_record",
      "page": "H228",
      "granule_id": "CREC-2001-02-08-pt1-PgH228-3",
      "signed_date": "2001-02-07",
      "url": "https://www.govinfo.gov/app/details/CREC-2001-02-08/CREC-2001-02-08-pt1-PgH228-3"
    }
  }
]
```

## Limitations

- **Renamed committees** resolve to their *current* `system_code` via each
  committee's name history (e.g. a 2001 "Committee on Resources" resignation →
  `hsii00`, today's Natural Resources). The committee index is fetched once and
  cached to `.cache/committees-house.json`; after a new Congress reorganizes or
  renames committees, delete that file to refresh (same download-once model as the
  legislators data).
- Bioguide and committee-code resolution are best-effort: unresolved values are
  left `null` (and logged with `-v`) rather than guessed. A committee with no
  matching current/historical name simply yields a `null` `system_code`.
- A `null` `bioguide_id` on a resolution event usually means one of three things,
  in roughly this order of frequency:
  - **A typo in the original government document** (e.g. "Guiterrez" for
    Gutierrez, "Baldaccu" for Baldacci). These are real, verifiable misprints in
    the source text, not a parsing bug — surname matching deliberately doesn't
    "fix" them by guessing, since a wrong guess is worse than a `null`.
  - **A member's name changed** between when they served and today. The
    congress-legislators data stores each person's *current* name, not the one
    printed at the time (e.g. Donna Christian-Green, later Christian-Christensen;
    Jill Long, later Long Thompson) — left unresolved for the same reason as above.
  - **Genuine ambiguity**: the text names only a bare surname with no state, and
    more than one same-surname member was serving at the time.
- The Congressional Record path can't yet parse a resignation notice that names
  **more than one signer in a single entry** (rare — only one instance has turned
  up across the 103rd–119th Congresses so far). It's discovered but explicitly
  skipped with a logged warning rather than guessing at which text belongs to
  which name.

## Tests

```bash
uv run pytest
```

Tests are offline: GPO/congress.gov/govinfo calls are exercised via
`httpx.MockTransport`, and parsing/bioguide logic runs against fixtures under
`tests/fixtures/`.

### Live integration tests

`tests/test_live.py` runs the pipeline against the **real** congress.gov and
govinfo APIs — a committee assignment resolution (H. Res. 1381), the committees
system-code lookup, and a Congressional Record resignation (H. Permanent Select
Committee on Intelligence, Feb 8 2001). They are excluded from the default run and
only execute when explicitly selected and a key is present:

```bash
export CONGRESS_GOV_API_KEY=...
uv run pytest -m live
```

Without the key they skip; without `-m live` they are deselected — so
`uv run pytest` stays offline.
