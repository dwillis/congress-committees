#!/usr/bin/env python3
"""Render committee-change events (JSON, on stdin) as a Markdown issue body."""

import json
import sys


def main() -> int:
    events = json.loads(sys.stdin.read())
    missing = [e for e in events if e.get("bioguide_id") is None and e.get("member_name")]
    lines = [f"Found {len(events)} new committee change event(s):", ""]
    if missing:
        lines.append(
            f"⚠️ **{len(missing)} of these have no `bioguide_id`** (flagged below) — "
            "a source-document typo, a member's name changing since, or genuine "
            "ambiguity. Check with `uv run python tools/review_server.py`."
        )
        lines.append("")
    for event in events:
        ref = event.get("source_ref") or {}
        url = ref.get("congress_gov_url") or ref.get("url") or ""
        line = (
            f"- **{event['change_type']}** — "
            f"{event['member_name'] or 'unknown member'} "
            f"({event['committee']}), {event['date']}, source: {event['source']}"
        )
        if url:
            line += f" — [details]({url})"
        if event.get("bioguide_id") is None and event.get("member_name"):
            line += " — ⚠️ no bioguide_id"
        lines.append(line)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
