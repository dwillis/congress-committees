#!/usr/bin/env python3
"""Re-filter committee-change events (JSON, on stdin) to only those whose OWN
`date` is on/after a given ISO date (argv[1]), writing the filtered list to
stdout.

congress.gov's bill `updateDate` -- used server-side to narrow the initial
`--since` fetch -- can be bumped by unrelated metadata reprocessing (a bulk
touch of hundreds of bills) well after a resolution's actual action date, so
the CLI's `--since` can return events that aren't actually new. This
re-filters on each event's own `date` field (the resolution's real
agreed-to date, or the resignation letter's issue date) so a daily digest
only ever reports genuinely new changes.
"""

import json
import sys


def main() -> int:
    since = sys.argv[1]
    events = json.loads(sys.stdin.read())
    filtered = [e for e in events if (e.get("date") or "") >= since]
    json.dump(filtered, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
