# congress-committees

Extract House committee membership changes from House resolutions (e.g.
[H. Res. 1381](https://www.congress.gov/bill/119th-congress/house-resolution/1381),
"Electing a Member to certain standing committees…") into structured JSON.

It discovers committee-change resolutions through the **congress.gov API**, parses
the committee names, House committee codes, and members from the **GPO govinfo bill
XML**, enriches each with the resolution's action history (when it was agreed to),
and resolves member names to **bioguide IDs** using the
[unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators)
datasets.

## How it works

1. **Discover** — list House resolutions for a Congress via the congress.gov API and
   keep those whose title marks a committee change (`Electing… committees`,
   `discharged from… committee`, etc.).
2. **Parse** — fetch each resolution's GPO bill XML
   (`BILLS-<congress>hres<number><stage>`) and read every
   `<committee-appointment-paragraph>`: committee name, `committee-id` code, and
   member. The title classifies each change as an `addition` or `removal`.
   (The congress.gov API can't supply appointment committee codes — privileged
   resolutions have no referral committees — so codes come from the XML.)
3. **Enrich** — pull the resolution's actions from the congress.gov API and derive
   the `agreed_to_date`; resolve each member name to a bioguide ID.
4. **Write** — emit a JSON list of resolution objects.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

| Variable | Required | Purpose |
|----------|----------|---------|
| `CONGRESS_GOV_API_KEY` | yes | congress.gov API key ([free signup](https://api.congress.gov)). Needed for discovery + actions. |
| `CONGRESS_LEGISLATORS_PATH` | no | Path to a congress-legislators YAML file or directory. If unset, the datasets are downloaded once to `.cache/`. |

## Usage

```bash
export CONGRESS_GOV_API_KEY=...
congress-committees --congress 119 --since 2026-06-20
# -> output/committee_changes_119.json
```

Options: `--out PATH`, `--since YYYY-MM-DD` (incremental polling),
`--legislators-path PATH`, `--no-bioguide`, `-v`.

Run it on a schedule (cron, etc.) with a moving `--since` watermark to capture new
committee-change resolutions as they are agreed to.

## Output

```json
[
  {
    "congress": "119",
    "type": "HRES",
    "number": "1381",
    "title": "Electing a Member to certain standing committees of the House of Representatives.",
    "stage": "Engrossed-in-House",
    "date": "2026-06-24",
    "govinfo_xml_url": "https://www.govinfo.gov/content/pkg/BILLS-119hres1381eh/xml/BILLS-119hres1381eh.xml",
    "congress_gov_url": "https://www.congress.gov/bill/119th-congress/house-resolution/1381",
    "actions": [{"date": "2026-06-24", "text": "...Agreed to...", "type": "Floor"}],
    "agreed_to_date": "2026-06-24",
    "committee_changes": [
      {"change_type": "addition", "committee": "Committee on Foreign Affairs",
       "committee_code": "HFA00", "member_name": "Mr. Gallagher", "bioguide_id": "G000587"}
    ]
  }
]
```

## Tests

```bash
pytest
```

Tests are offline: GPO/congress.gov calls are exercised via `httpx.MockTransport`,
and parsing/bioguide logic runs against fixtures under `tests/fixtures/`.

### Live integration test

There is also a live test (`tests/test_live.py`) that runs the full pipeline for a
real committee assignment resolution (H. Res. 1381) against the **actual
congress.gov API and GPO govinfo**. It is excluded from the default run and only
runs when explicitly selected and a key is present:

```bash
export CONGRESS_GOV_API_KEY=...
pytest -m live
```

Without the key it skips; without `-m live` it is deselected — so `pytest` stays
offline.
