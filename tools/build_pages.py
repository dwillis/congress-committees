#!/usr/bin/env python3
"""Generate the GitHub Pages site from output/*.json: docs/index.html (a
listing of downloads), docs/site.css (shared styles), and
docs/data/site_data.json (the precomputed data behind the interactive pages
docs/committees.html, docs/members.html, docs/dashboard.html), in the style
of https://thescoop.org/congress-press/ (same author, same visual language).

Run after regenerating any output/*.json file:

    uv run python tools/build_pages.py

Reads real data every time -- there are no hardcoded stats or Congress
numbers to go stale.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from congress_committees.committees import _normalize  # noqa: E402
from congress_committees.legislators import resolve_legislator_files  # noqa: E402

import yaml  # noqa: E402

REPO = "dwillis/congress-committees"
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"
DATA_DIR = DOCS_DIR / "data"


# Congress 1 began 1789-01-03; each Congress spans two years.
def _year_span(congress):
    start = 1789 + (congress - 1) * 2
    return start, start + 2


def _human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024


def _load_congress_files():
    """Return (rows, all_events) -- summary rows for the downloads page, and
    the full flat event list (each tagged with its source path) for the
    site-data build."""
    rows = []
    all_events = []
    for path in sorted(OUTPUT_DIR.glob("committee_changes_*.json")):
        congress = int(path.stem.rsplit("_", 1)[-1])
        events = json.loads(path.read_text())
        additions = sum(1 for e in events if e.get("change_type") == "addition")
        removals = sum(1 for e in events if e.get("change_type") == "removal")
        missing = sum(1 for e in events if e.get("bioguide_id") is None and e.get("member_name"))
        rows.append({
            "congress": congress,
            "path": path,
            "total": len(events),
            "additions": additions,
            "removals": removals,
            "missing": missing,
            "size": path.stat().st_size,
        })
        for e in events:
            e["congress"] = congress
        all_events.extend(events)
    return sorted(rows, key=lambda r: -r["congress"]), all_events


def _ordinal(n):
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# --------------------------------------------------------------------------
# docs/data/site_data.json -- the precomputed data behind the interactive
# pages. Everything here is derived straight from output/*.json plus the
# congress-legislators dataset; nothing is hand-maintained.
# --------------------------------------------------------------------------

def _committee_key(event):
    code = event.get("system_code")
    if code:
        return code
    # A committee with no resolved system_code (a joint committee, a messy
    # multi-committee resignation-letter title, a typo in the source
    # document) still needs a stable, de-duplicated key -- normalize the
    # printed name the same way CommitteeIndex does so near-identical
    # variants ("Committee on Ways and Means" / "committee on ways and
    # means") collapse together.
    return f"name:{_normalize(event.get('committee') or '')}"


def _build_committees(events):
    by_key = {}
    for e in events:
        key = _committee_key(e)
        entry = by_key.setdefault(key, {"names": {}, "latest_congress": -1})
        name = e.get("committee") or ""
        entry["names"][name] = entry["names"].get(name, 0) + 1
        if e["congress"] >= entry["latest_congress"]:
            entry["latest_congress"] = e["congress"]
            entry["latest_name"] = name

    committees = {}
    for key, entry in by_key.items():
        # The most-recently-printed name is the display name; every other
        # distinct printed name (renames, casing variants) is kept as
        # "formerly" context on the committee page.
        others = sorted(n for n in entry["names"] if n != entry["latest_name"])
        committees[key] = {"name": entry["latest_name"], "formerly": others}
    return committees


def _build_members(events):
    """bioguide -> {name, state, party}, loaded from the congress-legislators
    dataset (already cached in .cache/ or downloaded once, same as the CLI)
    for just the bioguides that actually appear in the data."""
    needed = {e["bioguide_id"] for e in events if e.get("bioguide_id")}
    members = {}
    if not needed:
        return members

    try:
        files = resolve_legislator_files(None, str(ROOT / ".cache"))
        records = []
        for path in files:
            if path.exists():
                data = yaml.safe_load(path.read_text())
                if data:
                    records.extend(data)
    except Exception as exc:  # pragma: no cover - defensive; site still builds
        print(f"warning: could not load legislator data for member info ({exc})", file=sys.stderr)
        records = []

    for rec in records:
        bioguide = (rec.get("id") or {}).get("bioguide")
        if bioguide not in needed or bioguide in members:
            continue
        name = rec.get("name") or {}
        terms = [t for t in (rec.get("terms") or []) if t.get("type") == "rep"]
        last_term = terms[-1] if terms else None
        members[bioguide] = {
            "name": name.get("official_full") or f"{name.get('first', '')} {name.get('last', '')}".strip(),
            "state": (last_term or {}).get("state"),
            "party": (last_term or {}).get("party"),
        }
    return members


def _build_site_data(events):
    committees = _build_committees(events)
    members = _build_members(events)
    trimmed = [
        {
            "c": e["congress"],
            "t": "a" if e.get("change_type") == "addition" else "r",
            "k": _committee_key(e),
            "n": e.get("member_name"),
            "b": e.get("bioguide_id"),
            "d": e.get("date"),
            "r": e.get("party_rank"),
            "u": (e.get("source_ref") or {}).get("congress_gov_url")
                 or (e.get("source_ref") or {}).get("url"),
        }
        for e in events
    ]
    return {
        "committees": committees,
        "members": members,
        "events": trimmed,
    }


# --------------------------------------------------------------------------
# Shared styling -- one stylesheet linked by every page.
# --------------------------------------------------------------------------

SITE_CSS = """
:root {
  --navy: #1a2744;
  --navy-light: #2a3d5e;
  --gold: #c5a44e;
  --gold-light: #d4ba73;
  --bg: #fafafa;
  --text: #2c2c2c;
  --border: #ddd;
  --green: #2f7a3d;
  --red: #a33a3a;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
  line-height: 1.6;
}

header {
  background: var(--navy);
  color: white;
  padding: 2.5rem 1rem 1.2rem;
  text-align: center;
}

header h1 {
  font-family: "Libre Baskerville", "Georgia", serif;
  font-size: 2.4rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  margin-bottom: 0.5rem;
}

header h1 span { color: var(--gold); }
header h1 a { color: inherit; text-decoration: none; }

header p {
  font-size: 1.05rem;
  opacity: 0.85;
  max-width: 600px;
  margin: 0 auto 1rem;
}

.header-links {
  display: flex;
  gap: 1.5rem;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.header-links a {
  color: var(--gold-light);
  text-decoration: none;
  font-size: 0.9rem;
  border-bottom: 1px solid transparent;
}

.header-links a:hover { border-bottom-color: var(--gold-light); }

nav.sitenav {
  background: var(--navy-light);
  display: flex;
  justify-content: center;
  gap: 2rem;
  padding: 0.6rem 1rem;
  flex-wrap: wrap;
}

nav.sitenav a {
  color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding-bottom: 2px;
  border-bottom: 2px solid transparent;
}

nav.sitenav a:hover, nav.sitenav a.active {
  color: white;
  border-bottom-color: var(--gold);
}

.stats {
  display: flex;
  justify-content: center;
  gap: 2.5rem;
  padding: 1.2rem 1rem;
  background: white;
  border-bottom: 2px solid var(--gold);
  flex-wrap: wrap;
}

.stat { text-align: center; }

.stat-value {
  font-family: "Libre Baskerville", "Georgia", serif;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--navy);
}

.stat-label {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #777;
}

main {
  max-width: 760px;
  margin: 2rem auto;
  padding: 0 1rem;
}

main.wide { max-width: 1000px; }

h2 {
  font-family: "Libre Baskerville", "Georgia", serif;
  font-size: 1.4rem;
  color: var(--navy);
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid var(--gold);
}

p.intro { margin-bottom: 1.5rem; color: #555; }

details {
  border: 1px solid var(--border);
  border-radius: 4px;
  margin-bottom: 0.5rem;
  background: white;
}

summary {
  padding: 0.8rem 1rem;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  user-select: none;
}

summary:hover { background: #f5f5f5; }
summary::-webkit-details-marker { display: none; }

summary::before {
  content: "\\25B6";
  font-size: 0.7rem;
  margin-right: 0.7rem;
  color: var(--gold);
  transition: transform 0.2s;
}

details[open] > summary::before { transform: rotate(90deg); }

.year {
  font-family: "Libre Baskerville", "Georgia", serif;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--navy);
}

.year-meta { font-size: 0.85rem; color: #888; }

details > :not(summary) { padding: 0 1rem 1rem; }

table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }

thead th {
  text-align: left;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #888;
  padding: 0.5rem 0.5rem;
  border-bottom: 1px solid var(--border);
}

td { padding: 0.45rem 0.5rem; border-bottom: 1px solid #eee; }

.num { text-align: right; font-variant-numeric: tabular-nums; }

.dl-link {
  color: var(--navy);
  text-decoration: none;
  font-weight: 500;
  font-size: 0.85rem;
  padding: 0.25rem 0.6rem;
  border: 1px solid var(--navy);
  border-radius: 3px;
  transition: all 0.15s;
}

.dl-link:hover { background: var(--navy); color: white; }

.months-covered { font-size: 0.8rem; color: #aaa; }

footer {
  text-align: center;
  padding: 2rem 1rem;
  font-size: 0.8rem;
  color: #999;
  border-top: 1px solid var(--border);
  margin-top: 2rem;
}

footer a { color: var(--navy-light); }

.card {
  background: white;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1rem;
  margin-bottom: 1rem;
}

.badge {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.badge.addition { background: #e3f2e3; color: var(--green); }
.badge.removal { background: #fbe6e6; color: var(--red); }

.warn-badge {
  display: inline-block;
  margin-left: 0.6rem;
  padding: 0.1rem 0.5rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
  background: #fbeee0;
  color: #a45c1a;
}

.alert-banner {
  background: #fff6e5;
  border: 1px solid #e8c98a;
  border-left: 4px solid #c5893a;
  border-radius: 4px;
  padding: 0.8rem 1rem;
  margin-bottom: 1.5rem;
  font-size: 0.92rem;
  color: #6b4a1a;
}

.alert-banner code {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
  font-size: 0.85em;
}

input[type=text], input[type=search], select {
  font: inherit;
  padding: 0.5rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  width: 100%;
}

.loading { color: #999; font-style: italic; padding: 1rem 0; }

@media (max-width: 600px) {
  header h1 { font-size: 1.8rem; }
  .stats { gap: 1.5rem; }
  .stat-value { font-size: 1.2rem; }
  nav.sitenav { gap: 1rem; }
}
"""


def _page_shell(title, nav_active, body, extra_head="", wide=False):
    def nav_link(href, label, key):
        active = " active" if key == nav_active else ""
        return f'<a href="{href}" class="{active.strip()}">{label}</a>'

    nav = f"""
    <nav class="sitenav">
      {nav_link('index.html', 'Downloads', 'downloads')}
      {nav_link('committees.html', 'Committees', 'committees')}
      {nav_link('members.html', 'Members', 'members')}
      {nav_link('dashboard.html', 'Dashboard', 'dashboard')}
    </nav>"""

    main_class = ' class="wide"' if wide else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="site.css">
  <link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&display=swap" rel="stylesheet">
  {extra_head}
</head>
<body>
  <header>
    <h1><a href="index.html">Congress <span>Committees</span></a></h1>
    <p>An archive of House committee membership changes -- additions and resignations.</p>
  </header>
{nav}
  <main{main_class}>
{body}
  </main>
  <footer>
    Created by <a href="mailto:dpwillis@umd.edu">Derek Willis</a>.
    <a href="https://github.com/{REPO}">View the source on GitHub</a>.
  </footer>
</body>
</html>
"""


# --------------------------------------------------------------------------
# docs/index.html -- the downloads listing (unchanged in substance, now
# sharing site.css and the nav bar).
# --------------------------------------------------------------------------

def _details_html(row, open_attr):
    congress = row["congress"]
    start, end = _year_span(congress)
    raw_url = f"https://raw.githubusercontent.com/{REPO}/main/output/{row['path'].name}"
    blob_url = f"https://github.com/{REPO}/blob/main/output/{row['path'].name}"
    # Shown right in the (possibly collapsed) summary line, not just buried in
    # the expanded body, so a missing bioguide_id is visible at a glance
    # across every Congress, not only the one that happens to be open.
    missing_badge = (
        f'<span class="warn-badge">&#9888; {row["missing"]} missing bioguide_id</span>'
        if row["missing"] else ""
    )
    return f"""
      <details{open_attr}>
        <summary>
          <span class="year">{_ordinal(congress)} Congress</span>
          <span class="year-meta">{row['total']:,} events &middot; {start}&ndash;{end}{missing_badge}</span>
        </summary>
        <table>
          <thead><tr><th>Additions</th><th>Removals</th><th>Size</th><th></th></tr></thead>
          <tbody>
          <tr>
            <td class="num">{row['additions']:,}</td>
            <td class="num">{row['removals']:,}</td>
            <td class="num">{_human_size(row['size'])}</td>
            <td><a href="{raw_url}" class="dl-link">Download JSON</a></td>
          </tr>
          </tbody>
        </table>
        <p class="months-covered">
          <a href="{blob_url}">View committee_changes_{congress}.json on GitHub</a>
        </p>
      </details>"""


def _build_index_html(rows):
    total_events = sum(r["total"] for r in rows)
    newest, oldest = rows[0]["congress"], rows[-1]["congress"]
    oldest_year, _ = _year_span(oldest)
    newest_row = rows[0]

    details = "".join(
        _details_html(row, " open" if row["congress"] == newest else "")
        for row in rows
    )

    # The most prominent thing on the page after the stats: if the *current*
    # Congress (the one the daily workflow keeps refreshing) came out of that
    # refresh with an unresolved bioguide_id, that's worth surfacing here
    # immediately, not just as a small badge several rows down.
    current_congress_alert = (
        f"""
    <div class="alert-banner">
      &#9888; The {_ordinal(newest)} Congress has <strong>{newest_row['missing']}</strong>
      event(s) with no <code>bioguide_id</code> after the latest update. See the
      {_ordinal(newest)} Congress row below, or run
      <code>uv run python tools/review_server.py</code> to check and fix them.
    </div>"""
        if newest_row["missing"] else ""
    )

    body = f"""
    <h2>Downloads</h2>
    <p class="intro">Each file is a flat JSON list of committee-change events (additions from
      House resolutions, removals from Congressional Record resignation letters), one per
      Congress, spanning the {_ordinal(oldest)} through {_ordinal(newest)} Congresses
      ({oldest_year}&ndash;present). See the <a href="https://github.com/{REPO}#output">README</a>
      for the event schema, or explore the data interactively via Committees, Members, and
      Dashboard above.</p>
{current_congress_alert}
    <div class="stats" style="margin-bottom: 1.5rem;">
      <div class="stat">
        <div class="stat-value">{total_events:,}</div>
        <div class="stat-label">Committee Changes</div>
      </div>
      <div class="stat">
        <div class="stat-value">{len(rows)}</div>
        <div class="stat-label">Congresses</div>
      </div>
      <div class="stat">
        <div class="stat-value">{oldest_year}&ndash;present</div>
        <div class="stat-label">Years Covered</div>
      </div>
    </div>
{details}
"""
    return _page_shell(
        "Congress Committees - House Committee Membership Change Archive",
        "downloads",
        body,
    )


def main():
    rows, events = _load_congress_files()
    if not rows:
        print("No output/committee_changes_*.json files found -- nothing to build.", file=sys.stderr)
        return 1

    DOCS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

    (DOCS_DIR / "site.css").write_text(SITE_CSS)
    (DOCS_DIR / "index.html").write_text(_build_index_html(rows))

    site_data = _build_site_data(events)
    data_path = DATA_DIR / "site_data.json"
    data_path.write_text(json.dumps(site_data, separators=(",", ":")))

    total_events = sum(r["total"] for r in rows)
    print(
        f"Wrote docs/index.html, docs/site.css, {data_path.relative_to(ROOT)} "
        f"({len(rows)} Congresses, {total_events:,} events, "
        f"{len(site_data['committees'])} committees, {len(site_data['members'])} members, "
        f"{data_path.stat().st_size // 1024} KB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
