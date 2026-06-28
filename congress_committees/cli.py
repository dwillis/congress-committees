"""Command-line entry point: poll for committee-change resolutions and write JSON."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .api import CongressGovClient
from .collector import collect_committee_change_events
from .committees import CommitteeIndex
from .congressional_record import CRECClient
from .dates import congress_date_span
from .legislators import LegislatorIndex
from .resignations import collect_resignations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="congress-committees",
        description="Extract House committee membership changes from House "
        "resolutions via the congress.gov API and GPO bill XML.",
    )
    parser.add_argument("--congress", type=int, required=True, help="Congress number, e.g. 119")
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only resolutions updated on/after this ISO date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output JSON path (default: output/committee_changes_<congress>.json).",
    )
    parser.add_argument(
        "--legislators-path",
        type=str,
        default=os.environ.get("CONGRESS_LEGISLATORS_PATH"),
        help="Path to congress-legislators YAML file or directory. "
        "Defaults to $CONGRESS_LEGISLATORS_PATH, else downloads to .cache/.",
    )
    parser.add_argument(
        "--no-bioguide",
        action="store_true",
        help="Skip resolving member names to bioguide IDs.",
    )
    parser.add_argument(
        "--source",
        choices=["resolution", "record", "all"],
        default="all",
        help="Which source(s) to collect: resolution (House resolutions), "
        "record (Congressional Record resignations), or all (default).",
    )
    parser.add_argument(
        "--no-committee-codes",
        action="store_true",
        help="Skip fetching the congress.gov committees list for system_code lookup.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        client = CongressGovClient.from_env()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    legislators = None
    if not args.no_bioguide:
        try:
            legislators = LegislatorIndex.load(path=args.legislators_path)
        except Exception as exc:  # pragma: no cover - network/IO degradation
            print(f"warning: bioguide resolution disabled ({exc})", file=sys.stderr)

    events = []

    if args.source in ("resolution", "all"):
        events += collect_committee_change_events(
            args.congress, client=client, legislators=legislators, since=args.since
        )

    if args.source in ("record", "all"):
        span_start, span_end = congress_date_span(args.congress)
        start = args.since or span_start
        end = span_end

        committee_index = None
        if not args.no_committee_codes:
            try:
                committee_index = CommitteeIndex.from_records(
                    client.list_committees("house")
                )
            except Exception as exc:  # pragma: no cover - network/IO degradation
                print(
                    f"warning: committee system_code lookup disabled ({exc})",
                    file=sys.stderr,
                )

        try:
            crec = CRECClient.from_env()
        except RuntimeError as exc:
            print(
                f"warning: Congressional Record source skipped ({exc})",
                file=sys.stderr,
            )
        else:
            events += collect_resignations(
                congress=args.congress,
                client=crec,
                start=start,
                end=end,
                committees=committee_index,
                legislators=legislators,
            )

    out_path = Path(args.out or f"output/committee_changes_{args.congress}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([e.model_dump() for e in events], indent=2) + "\n"
    )

    additions = sum(1 for e in events if e.change_type == "addition")
    removals = sum(1 for e in events if e.change_type == "removal")
    print(
        f"Wrote {len(events)} committee change event(s) "
        f"({additions} addition(s), {removals} removal(s)) to {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
