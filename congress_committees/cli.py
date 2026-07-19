"""Command-line entry point: poll for committee-change resolutions and write JSON."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

from .api import CongressGovClient
from .collector import collect_committee_change_events
from .committees import CommitteeIndex
from .congressional_record import CRECClient
from .dates import congress_date_span
from .legislators import LegislatorIndex
from .models import CommitteeChangeEvent
from .resignations import collect_resignations


def _event_source_key(event: CommitteeChangeEvent):
    """A stable identity for a committee-change event across re-runs, built
    from the underlying document's own identifier (resolution number / CREC
    granule id) plus committee/member/change-type -- events have no ID of
    their own. Used to carry a manually-set bioguide_id forward when the CLI
    regenerates an existing output file (see _merge_bioguide_ids)."""
    ref = event.source_ref
    ref_id = getattr(ref, "number", None) or getattr(ref, "granule_id", None)
    return (event.change_type, event.committee, event.member_name, ref.type, ref_id)


def _merge_bioguide_ids(old_events_raw: list, new_events: List[CommitteeChangeEvent]) -> int:
    """Fill in `bioguide_id` on any `new_events` entry that's missing one, from
    the matching event (see _event_source_key) in a previous run's raw JSON,
    if that older run had a bioguide_id there. That's typically a hand
    correction made via tools/review_server.py for something the automated
    lookup deliberately won't guess (a source-document typo, a member's
    later name change, etc.) -- a fresh automated re-run can't rediscover
    those on its own, so without this, regenerating the file would silently
    wipe them out. Returns the number of events filled in.
    """
    old_by_key = {}
    for raw in old_events_raw:
        bioguide = raw.get("bioguide_id")
        if not bioguide:
            continue
        ref = raw.get("source_ref") or {}
        ref_id = ref.get("number") or ref.get("granule_id")
        key = (raw.get("change_type"), raw.get("committee"), raw.get("member_name"), ref.get("type"), ref_id)
        old_by_key[key] = bioguide

    filled = 0
    for event in new_events:
        if event.bioguide_id is None:
            bioguide = old_by_key.get(_event_source_key(event))
            if bioguide:
                event.bioguide_id = bioguide
                filled += 1
    return filled


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
        help="Lower date bound (YYYY-MM-DD) for both sources: the "
        "'updated on/after' server filter for resolutions, and the start of the "
        "date-range walk for the Congressional Record path.",
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

    committee_index = None
    if not args.no_committee_codes:
        try:
            committee_index = CommitteeIndex.load(client)
        except Exception as exc:  # pragma: no cover - network/IO degradation
            print(
                f"warning: committee system_code lookup disabled ({exc})",
                file=sys.stderr,
            )

    events: List[CommitteeChangeEvent] = []

    if args.source in ("resolution", "all"):
        resolution_events = collect_committee_change_events(
            args.congress, client=client, legislators=legislators, since=args.since
        )
        if committee_index is not None:
            for event in resolution_events:
                if event.system_code is None:
                    event.system_code = committee_index.code_for(event.committee)
        events += resolution_events

    if args.source in ("record", "all"):
        span_start, span_end = congress_date_span(args.congress)
        start = args.since or span_start
        end = span_end

        try:
            crec = CRECClient.from_env()
        except RuntimeError as exc:
            print(
                f"warning: Congressional Record source skipped ({exc})",
                file=sys.stderr,
            )
        else:
            try:
                events += collect_resignations(
                    congress=args.congress,
                    client=crec,
                    start=start,
                    end=end,
                    committees=committee_index,
                    legislators=legislators,
                )
            except Exception as exc:  # pragma: no cover - network/IO degradation
                print(
                    f"warning: Congressional Record collection failed ({exc}); "
                    "continuing with other sources",
                    file=sys.stderr,
                )

    out_path = Path(args.out or f"output/committee_changes_{args.congress}.json")
    if out_path.exists():
        try:
            old_events_raw = json.loads(out_path.read_text())
        except (json.JSONDecodeError, OSError):
            old_events_raw = []
        filled = _merge_bioguide_ids(old_events_raw, events)
        if filled:
            print(
                f"Preserved {filled} manually-set bioguide_id(s) from the previous {out_path}",
                file=sys.stderr,
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([e.model_dump() for e in events], indent=2) + "\n"
    )

    additions = sum(1 for e in events if e.change_type == "addition")
    removals = sum(1 for e in events if e.change_type == "removal")
    missing_bioguide = sum(1 for e in events if e.bioguide_id is None)
    print(
        f"Wrote {len(events)} committee change event(s) "
        f"({additions} addition(s), {removals} removal(s)) to {out_path} "
        f"({missing_bioguide} with no bioguide_id)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
