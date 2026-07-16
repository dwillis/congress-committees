#!/usr/bin/env python3
"""Render committee-change events (JSON, on stdin) as a Markdown issue body."""

import json
import sys


def main() -> int:
    events = json.loads(sys.stdin.read())
    lines = [f"Found {len(events)} new committee change event(s):", ""]
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
        lines.append(line)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
