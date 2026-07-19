#!/usr/bin/env python3
"""A tiny local web UI for checking and editing committee_changes_<congress>.json
files, especially events with no bioguide_id.

Stdlib only (http.server) -- no extra dependencies, nothing leaves your
machine. Run it from the repo root:

    uv run python tools/review_server.py
    uv run python tools/review_server.py --port 8080 --output-dir output

Then open http://localhost:8000/ in a browser.
"""

import argparse
import html
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from congress_committees.atomic_io import atomic_write_text  # noqa: E402

PAGE_SIZE = 50
FILENAME_RE = re.compile(r"committee_changes_(\d+)\.json$")

# Fields a reviewer can change from the browser. Everything else (congress,
# change_type, system_code, gpo_code, member_name_raw, source, source_ref) is
# shown for context but edited by hand in the JSON if it's ever wrong --
# these are the fields actually worth a quick web form.
EDITABLE_FIELDS = ("member_name", "committee", "bioguide_id", "party_rank", "date")


def _guess_surname(member_name):
    """Best-effort surname guess from a printed name, for pre-filling the
    legislator search link -- doesn't need to be perfect, just a head start."""
    name = re.sub(r"^(?:Mr|Ms|Mrs|Miss)\.\s*", "", member_name or "", flags=re.IGNORECASE)
    name = re.sub(r"\s*,?\s*(?:Jr|Sr|II|III|IV)\.?\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+(?:of|or)\s+.+$", "", name, flags=re.IGNORECASE)
    tokens = [t for t in name.replace(",", " ").split() if t]
    return tokens[-1] if tokens else ""


def _load_legislator_search_index(legislators_path):
    """Best-effort: build a flat, searchable list of House-member candidates.
    Returns [] (feature quietly disabled) if the datasets aren't available --
    this tool should still work for browsing/editing even offline."""
    try:
        from congress_committees.legislators import LegislatorIndex, _fold
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"warning: legislator search disabled ({exc})", file=sys.stderr)
        return []
    try:
        index = LegislatorIndex.load(path=legislators_path)
    except Exception as exc:
        print(f"warning: legislator search disabled ({exc})", file=sys.stderr)
        return []
    rows = []
    for surname_key, candidates in index._by_surname.items():
        for c in candidates:
            rows.append({
                "bioguide": c.bioguide,
                "first": c.first or "",
                "surname_key": surname_key,
                "states": sorted(c.states),
                "terms": c.terms,
            })
    return rows


class Store:
    """Loads/saves committee_changes_<congress>.json files on demand -- no
    in-memory caching, so an edit is visible to the next request immediately
    and an external re-run of the CLI is picked up without restarting."""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)

    def path_for(self, congress):
        return self.output_dir / f"committee_changes_{congress}.json"

    def available_congresses(self):
        found = []
        if self.output_dir.is_dir():
            for p in sorted(self.output_dir.glob("committee_changes_*.json")):
                m = FILENAME_RE.search(p.name)
                if m:
                    found.append(m.group(1))
        return sorted(found, key=int, reverse=True)

    def load(self, congress):
        path = self.path_for(congress)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save(self, congress, events):
        atomic_write_text(self.path_for(congress), json.dumps(events, indent=2) + "\n")


def _missing(event):
    return event.get("bioguide_id") is None and bool(event.get("member_name"))


def _page(title, body):
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 1.5rem;
         color: #1a1a1a; background: #fff; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: 4px 6px; text-align: left;
            vertical-align: top; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; }}
  input[type=text] {{ width: 100%; box-sizing: border-box; font-size: 0.85rem;
                       padding: 2px 4px; }}
  input[type=text].narrow {{ width: 5em; }}
  .committee-col {{ min-width: 12em; }}
  .name-col {{ min-width: 12em; }}
  .muted {{ color: #777; font-size: 0.8em; }}
  .flash {{ background: #eaffea; border: 1px solid #9c9; padding: 0.5em 1em;
            margin-bottom: 1em; border-radius: 4px; }}
  .error {{ background: #ffecec; border: 1px solid #c99; padding: 0.5em 1em;
            margin-bottom: 1em; border-radius: 4px; }}
  nav a {{ margin-right: 1em; }}
  .pill {{ display: inline-block; padding: 0 6px; border-radius: 8px; font-size: 0.75em;
           background: #eee; }}
  .pill.addition {{ background: #e3f2e3; }}
  .pill.removal {{ background: #fde3e3; }}
  a.search-link {{ font-size: 0.8em; }}
</style>
</head><body>
{body}
</body></html>"""


def _index_page(store):
    rows = []
    for congress in store.available_congresses():
        events = store.load(congress) or []
        missing = sum(1 for e in events if _missing(e))
        rows.append(
            f"<tr><td>{html.escape(congress)}</td><td>{len(events)}</td>"
            f"<td>{missing}</td>"
            f"<td><a href='/congress/{congress}?filter=missing'>review missing</a>"
            f" &middot; <a href='/congress/{congress}?filter=all'>browse all</a></td></tr>"
        )
    table = "".join(rows) or "<tr><td colspan=4>No committee_changes_*.json files found.</td></tr>"
    body = f"""
<h1>congress-committees review</h1>
<p class="muted">Serving JSON files from <code>{html.escape(str(store.output_dir))}</code>.</p>
<table>
<tr><th>Congress</th><th>Total events</th><th>Missing bioguide_id</th><th></th></tr>
{table}
</table>
"""
    return _page("congress-committees review", body)


def _field_input(idx, field, value, narrow=False):
    """Per-row-namespaced input (e.g. name="committee__42") -- all rows on the
    page share ONE <form>, and the per-row Save button (see below) tells the
    server which row's fields to actually apply, so editing several rows
    before saving any of them never bleeds one row's edits into another."""
    val = "" if value is None else str(value)
    cls = "narrow" if narrow else ""
    return f'<input type="text" name="{field}__{idx}" value="{html.escape(val)}" class="{cls}">'


def _congress_page(store, congress, filt, q, page, flash=None, error=None):
    events = store.load(congress)
    if events is None:
        return None

    if filt == "missing":
        indexed = [(i, e) for i, e in enumerate(events) if _missing(e)]
    else:
        indexed = list(enumerate(events))

    if q:
        needle = q.lower()
        indexed = [
            (i, e) for i, e in indexed
            if needle in (e.get("member_name") or "").lower()
            or needle in (e.get("committee") or "").lower()
        ]

    total = len(indexed)
    start = (page - 1) * PAGE_SIZE
    page_rows = indexed[start:start + PAGE_SIZE]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    rows_html = []
    for idx, e in page_rows:
        guess = _guess_surname(e.get("member_name"))
        ref = e.get("source_ref") or {}
        link = ref.get("congress_gov_url") or ref.get("url") or ""
        change_type = html.escape(e.get("change_type") or "")
        rows_html.append(f"""
<tr>
<td>{idx}<br><span class="pill {change_type}">{change_type}</span></td>
<td class="committee-col">{_field_input(idx, 'committee', e.get('committee'))}</td>
<td class="name-col">{_field_input(idx, 'member_name', e.get('member_name'))}
  <div class="muted">{html.escape(e.get('member_name_raw') or '')}</div></td>
<td>{_field_input(idx, 'bioguide_id', e.get('bioguide_id'), narrow=True)}
  <div><a class="search-link" target="_blank"
     href="/search?{urlencode({'q': guess})}">search &ldquo;{html.escape(guess)}&rdquo;</a></div></td>
<td>{_field_input(idx, 'party_rank', e.get('party_rank'), narrow=True)}</td>
<td>{_field_input(idx, 'date', e.get('date'), narrow=True)}</td>
<td class="muted">{html.escape(e.get('source') or '')}<br>
  {f'<a href="{html.escape(link)}" target="_blank">source</a>' if link else ''}</td>
<td><button type="submit" name="save_idx" value="{idx}">Save</button></td>
</tr>""")

    form_rows = "".join(rows_html)

    def _qs(p):
        return html.escape(urlencode({"filter": filt, "q": q, "page": p}))

    prev_link = (
        f"<a href='/congress/{congress}?{_qs(page - 1)}'>&laquo; prev</a>"
        if page > 1 else "<span class='muted'>&laquo; prev</span>"
    )
    next_link = (
        f"<a href='/congress/{congress}?{_qs(page + 1)}'>next &raquo;</a>"
        if page < total_pages else "<span class='muted'>next &raquo;</span>"
    )

    flash_html = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""

    body = f"""
<nav><a href="/">&larr; all congresses</a></nav>
<h1>{html.escape(congress)}th Congress
  <span class="muted">({total} of {len(events)} events shown)</span></h1>
{flash_html}{error_html}
<form method="get" action="/congress/{congress}">
  <label><input type="radio" name="filter" value="missing" {"checked" if filt == "missing" else ""}
    onchange="this.form.submit()"> missing bioguide_id</label>
  <label><input type="radio" name="filter" value="all" {"checked" if filt == "all" else ""}
    onchange="this.form.submit()"> all events</label>
  &nbsp; <input type="text" name="q" value="{html.escape(q)}" placeholder="filter by name/committee">
  <button type="submit">Apply</button>
</form>
<p>{prev_link} &middot; page {page} of {total_pages} &middot; {next_link}</p>
<form method="post" action="/congress/{congress}/save">
<input type="hidden" name="filter" value="{html.escape(filt)}">
<input type="hidden" name="q" value="{html.escape(q)}">
<input type="hidden" name="page" value="{page}">
<table>
<tr><th>#</th><th>Committee</th><th>Member</th><th>Bioguide</th>
    <th>Rank</th><th>Date</th><th>Source</th><th></th></tr>
{form_rows}
</table>
</form>
<p>{prev_link} &middot; page {page} of {total_pages} &middot; {next_link}</p>
"""
    return _page(f"{congress}th Congress review", body)


def _search_page(legislator_rows, q):
    q = (q or "").strip()
    results = []
    if q:
        from congress_committees.legislators import _fold
        needle = _fold(q)
        for row in legislator_rows:
            haystack = _fold(f"{row['first']} {row['surname_key']}")
            if needle in haystack or needle in row["surname_key"]:
                results.append(row)
        results = results[:200]

    rows_html = []
    for r in results:
        terms = "; ".join(
            f"{s}-{e or 'present'}" for s, e in r["terms"]
        )
        rows_html.append(
            f"<tr><td><code>{html.escape(r['bioguide'])}</code></td>"
            f"<td>{html.escape(r['first'])}</td><td>{html.escape(r['surname_key'].title())}</td>"
            f"<td>{', '.join(r['states'])}</td><td class='muted'>{html.escape(terms)}</td></tr>"
        )
    table = "".join(rows_html) or (
        "<tr><td colspan=5 class='muted'>No matches (or the legislator search "
        "index isn't available -- see server startup log).</td></tr>" if q else ""
    )
    body = f"""
<nav><a href="/">&larr; all congresses</a></nav>
<h1>Legislator search</h1>
<form method="get" action="/search">
  <input type="text" name="q" value="{html.escape(q)}" placeholder="surname or first name" autofocus>
  <button type="submit">Search</button>
</form>
<p class="muted">Matches surname or first name (accent/hyphen-insensitive). Copy the bioguide ID
you want into the event's Bioguide field and Save.</p>
<table>
<tr><th>Bioguide</th><th>First</th><th>Last</th><th>States (House)</th><th>Terms</th></tr>
{table}
</table>
"""
    return _page("Legislator search", body)


def make_handler(store, legislator_rows):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

        def _send_html(self, body, status=200):
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _redirect(self, location):
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            parts = [p for p in parsed.path.split("/") if p]

            if not parts:
                self._send_html(_index_page(store))
                return

            if parts[0] == "search":
                q = qs.get("q", [""])[0]
                self._send_html(_search_page(legislator_rows, q))
                return

            if parts[0] == "congress" and len(parts) >= 2:
                congress = parts[1]
                filt = qs.get("filter", ["missing"])[0]
                q = qs.get("q", [""])[0]
                try:
                    page = max(1, int(qs.get("page", ["1"])[0]))
                except ValueError:
                    page = 1
                flash = qs.get("saved", [None])[0]
                page_html = _congress_page(
                    store, congress, filt, q, page,
                    flash=f"Saved event #{flash}." if flash else None,
                )
                if page_html is None:
                    self._send_html(_page("Not found", "<p>No such congress file.</p>"), status=404)
                    return
                self._send_html(page_html)
                return

            self._send_html(_page("Not found", "<p>Not found.</p>"), status=404)

        def do_POST(self):
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) == 3 and parts[0] == "congress" and parts[2] == "save":
                congress = parts[1]
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                # keep_blank_values -- parse_qs drops empty fields by default,
                # which would make "clear this field" (submit it blank)
                # indistinguishable from "field wasn't in the form at all".
                form = parse_qs(body, keep_blank_values=True)
                filt = form.get("filter", ["missing"])[0]
                q = form.get("q", [""])[0]
                page = form.get("page", ["1"])[0]
                page_num = int(page) if page.isdigit() else 1

                # Every row's inputs are namespaced "field__idx" and share one
                # <form>; "save_idx" (the value of whichever row's Save button
                # was actually clicked) says which row to apply -- so editing
                # several rows before saving any of them can't bleed one
                # row's unsaved edits into another.
                idx_raw = form.get("save_idx", [""])[0]

                events = store.load(congress)
                if events is None:
                    self._send_html(_page("Not found", "<p>No such congress file.</p>"), status=404)
                    return
                try:
                    idx = int(idx_raw)
                    event = events[idx]
                except (ValueError, IndexError):
                    self._send_html(
                        _congress_page(store, congress, filt, q, page_num,
                                       error=f"Bad row index {idx_raw!r} -- nothing saved."),
                        status=400,
                    )
                    return

                for field in EDITABLE_FIELDS:
                    key = f"{field}__{idx}"
                    if key not in form:
                        continue
                    raw = form[key][0].strip()
                    if field == "committee":
                        if raw:  # committee is required; blank submissions are ignored
                            event["committee"] = raw
                    elif field == "party_rank":
                        if not raw:
                            event["party_rank"] = None
                        else:
                            try:
                                event["party_rank"] = int(raw)
                            except ValueError:
                                pass  # leave the existing value rather than corrupt it
                    else:  # member_name, bioguide_id, date -- plain optional strings
                        event[field] = raw or None

                store.save(congress, events)
                qs = urlencode({"filter": filt, "q": q, "page": page, "saved": idx})
                self._redirect(f"/congress/{congress}?{qs}")
                return

            self._send_html(_page("Not found", "<p>Not found.</p>"), status=404)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="output", help="Directory of committee_changes_*.json files")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--legislators-path", default=None,
                         help="congress-legislators YAML file/dir (for the search helper); "
                              "defaults to CONGRESS_LEGISLATORS_PATH / .cache, same as the CLI")
    args = parser.parse_args()

    store = Store(args.output_dir)
    print("Loading legislator search index (for the /search helper)...", file=sys.stderr)
    legislator_rows = _load_legislator_search_index(args.legislators_path)
    print(f"Loaded {len(legislator_rows)} House-member records for search."
          if legislator_rows else "Legislator search unavailable -- browsing/editing still works.",
          file=sys.stderr)

    handler = make_handler(store, legislator_rows)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving {store.output_dir} at http://127.0.0.1:{args.port}/ (Ctrl-C to stop)", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
