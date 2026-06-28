"""Command-line entry point: poll for committee-change resolutions and write JSON."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .api import CongressGovClient
from .collector import collect_committee_changes
from .legislators import LegislatorIndex


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

    records = collect_committee_changes(
        args.congress, client=client, legislators=legislators, since=args.since
    )

    out_path = Path(args.out or f"output/committee_changes_{args.congress}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([r.model_dump() for r in records], indent=2) + "\n"
    )

    changes = sum(len(r.committee_changes) for r in records)
    print(
        f"Wrote {len(records)} resolution(s) / {changes} committee change(s) to {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
