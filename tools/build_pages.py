#!/usr/bin/env python3
"""Generate docs/index.html: a static GitHub Pages listing of the
committee_changes_<congress>.json files in output/, in the style of
https://thescoop.org/congress-press/ (same author, same visual language).

Run after regenerating any output/*.json file:

    uv run python tools/build_pages.py

Reads real data every time -- there are no hardcoded stats or Congress
numbers to go stale.
"""

import json
import sys
from pathlib import Path

REPO = "dwillis/congress-committees"
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"

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
    rows = []
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
    return sorted(rows, key=lambda r: -r["congress"])


def _ordinal(n):
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _details_html(row, open_attr):
    congress = row["congress"]
    start, end = _year_span(congress)
    raw_url = f"https://raw.githubusercontent.com/{REPO}/main/output/{row['path'].name}"
    blob_url = f"https://github.com/{REPO}/blob/main/output/{row['path'].name}"
    missing_note = (
        f" &middot; {row['missing']} missing bioguide_id" if row["missing"] else ""
    )
    return f"""
      <details{open_attr}>
        <summary>
          <span class="year">{_ordinal(congress)} Congress</span>
          <span class="year-meta">{row['total']:,} events &middot; {start}&ndash;{end}</span>
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
          <a href="{blob_url}">View committee_changes_{congress}.json on GitHub</a>{missing_note}
        </p>
      </details>"""


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Congress Committees - House Committee Membership Change Archive</title>
  <style>
    :root {{
      --navy: #1a2744;
      --navy-light: #2a3d5e;
      --gold: #c5a44e;
      --gold-light: #d4ba73;
      --bg: #fafafa;
      --text: #2c2c2c;
      --border: #ddd;
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
      line-height: 1.6;
    }}

    header {{
      background: var(--navy);
      color: white;
      padding: 2.5rem 1rem 2rem;
      text-align: center;
    }}

    header h1 {{
      font-family: "Libre Baskerville", "Georgia", serif;
      font-size: 2.4rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      margin-bottom: 0.5rem;
    }}

    header h1 span {{
      color: var(--gold);
    }}

    header p {{
      font-size: 1.05rem;
      opacity: 0.85;
      max-width: 600px;
      margin: 0 auto 1rem;
    }}

    .header-links {{
      display: flex;
      gap: 1.5rem;
      justify-content: center;
      flex-wrap: wrap;
    }}

    .header-links a {{
      color: var(--gold-light);
      text-decoration: none;
      font-size: 0.9rem;
      border-bottom: 1px solid transparent;
    }}

    .header-links a:hover {{
      border-bottom-color: var(--gold-light);
    }}

    .stats {{
      display: flex;
      justify-content: center;
      gap: 2.5rem;
      padding: 1.2rem 1rem;
      background: white;
      border-bottom: 2px solid var(--gold);
      flex-wrap: wrap;
    }}

    .stat {{
      text-align: center;
    }}

    .stat-value {{
      font-family: "Libre Baskerville", "Georgia", serif;
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--navy);
    }}

    .stat-label {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #777;
    }}

    main {{
      max-width: 760px;
      margin: 2rem auto;
      padding: 0 1rem;
    }}

    h2 {{
      font-family: "Libre Baskerville", "Georgia", serif;
      font-size: 1.4rem;
      color: var(--navy);
      margin-bottom: 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 2px solid var(--gold);
    }}

    p.intro {{
      margin-bottom: 1.5rem;
      color: #555;
    }}

    details {{
      border: 1px solid var(--border);
      border-radius: 4px;
      margin-bottom: 0.5rem;
      background: white;
    }}

    summary {{
      padding: 0.8rem 1rem;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
    }}

    summary:hover {{
      background: #f5f5f5;
    }}

    summary::-webkit-details-marker {{
      display: none;
    }}

    summary::before {{
      content: "\\25B6";
      font-size: 0.7rem;
      margin-right: 0.7rem;
      color: var(--gold);
      transition: transform 0.2s;
    }}

    details[open] > summary::before {{
      transform: rotate(90deg);
    }}

    .year {{
      font-family: "Libre Baskerville", "Georgia", serif;
      font-size: 1.15rem;
      font-weight: 700;
      color: var(--navy);
    }}

    .year-meta {{
      font-size: 0.85rem;
      color: #888;
    }}

    details > :not(summary) {{
      padding: 0 1rem 1rem;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}

    thead th {{
      text-align: left;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #888;
      padding: 0.5rem 0.5rem;
      border-bottom: 1px solid var(--border);
    }}

    td {{
      padding: 0.45rem 0.5rem;
      border-bottom: 1px solid #eee;
    }}

    .num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}

    .dl-link {{
      color: var(--navy);
      text-decoration: none;
      font-weight: 500;
      font-size: 0.85rem;
      padding: 0.25rem 0.6rem;
      border: 1px solid var(--navy);
      border-radius: 3px;
      transition: all 0.15s;
    }}

    .dl-link:hover {{
      background: var(--navy);
      color: white;
    }}

    .months-covered {{
      font-size: 0.8rem;
      color: #aaa;
    }}

    footer {{
      text-align: center;
      padding: 2rem 1rem;
      font-size: 0.8rem;
      color: #999;
      border-top: 1px solid var(--border);
      margin-top: 2rem;
    }}

    footer a {{
      color: var(--navy-light);
    }}

    @media (max-width: 600px) {{
      header h1 {{ font-size: 1.8rem; }}
      .stats {{ gap: 1.5rem; }}
      .stat-value {{ font-size: 1.2rem; }}
    }}
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&display=swap" rel="stylesheet">
</head>
<body>
  <header>
    <h1>Congress <span>Committees</span></h1>
    <p>An archive of House committee membership changes -- additions and resignations --
       for the {oldest_ordinal} through {newest_ordinal} Congresses ({oldest_year}&ndash;present).</p>
    <div class="header-links">
      <a href="https://github.com/{repo}">GitHub Repository</a>
      <a href="https://github.com/{repo}#readme">Documentation</a>
      <a href="https://github.com/{repo}/blob/main/HISTORY.md">Project History</a>
    </div>
  </header>

  <div class="stats">
    <div class="stat">
      <div class="stat-value">{total_events:,}</div>
      <div class="stat-label">Committee Changes</div>
    </div>
    <div class="stat">
      <div class="stat-value">{num_congresses}</div>
      <div class="stat-label">Congresses</div>
    </div>
    <div class="stat">
      <div class="stat-value">{oldest_year}&ndash;present</div>
      <div class="stat-label">Years Covered</div>
    </div>
  </div>

  <main>
    <h2>Downloads</h2>
    <p class="intro">Each file is a flat JSON list of committee-change events (additions from
      House resolutions, removals from Congressional Record resignation letters), one per
      Congress. See the <a href="https://github.com/{repo}#output">README</a> for the event
      schema.</p>
{details}
  </main>

  <footer>
    Created by <a href="mailto:dpwillis@umd.edu">Derek Willis</a>.
    <a href="https://github.com/{repo}">View the source on GitHub</a>.
  </footer>
</body>
</html>
"""


def main():
    rows = _load_congress_files()
    if not rows:
        print("No output/committee_changes_*.json files found -- nothing to build.", file=sys.stderr)
        return 1

    total_events = sum(r["total"] for r in rows)
    newest, oldest = rows[0]["congress"], rows[-1]["congress"]
    oldest_year, _ = _year_span(oldest)

    details = "".join(
        _details_html(row, " open" if row["congress"] == newest else "")
        for row in rows
    )

    html = TEMPLATE.format(
        repo=REPO,
        total_events=total_events,
        num_congresses=len(rows),
        oldest_year=oldest_year,
        oldest_ordinal=_ordinal(oldest),
        newest_ordinal=_ordinal(newest),
        details=details,
    )

    DOCS_DIR.mkdir(exist_ok=True)
    out_path = DOCS_DIR / "index.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} ({len(rows)} Congresses, {total_events:,} total events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
