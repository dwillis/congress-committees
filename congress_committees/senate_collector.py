"""Orchestrate discovery, parsing, and roster-diffing for Senate S.Res.
committee-assignment resolutions.

Unlike the House pipeline (collector.py), a single Senate resolution never
states an addition or removal explicitly -- it restates a committee's ENTIRE
current roster for one party (or, in the older single-add schema, adds
exactly one Senator). Additions/removals are inferred here by diffing each
resolution's roster against the last one seen for that (committee, party)
pair, so resolutions MUST be processed in chronological (agreed-to-date)
order -- unlike collect_committee_changes, where each resolution is entirely
self-contained and order never matters.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple

from .api import extract_agreed_to_date
from .gpo import SENATE_STAGES
from .gpo import fetch_resolution_text as gpo_fetch_resolution_text
from .gpo import fetch_resolution_xml as gpo_fetch_resolution_xml
from .gpo import html_url
from .legislators import LegislatorIndex
from .models import CommitteeChange, CommitteeChangeEvent, ResolutionRecord, to_events
from .senate_parser import (
    classify_senate_title,
    parse_senate_resolution_text,
    parse_senate_resolution_xml,
)

logger = logging.getLogger(__name__)

# (committee, party) -> {identity: (clean_name, raw_name)}, where identity is
# a bioguide ID when resolved, or a normalized-name fallback key otherwise.
_RosterKey = Tuple[str, str]
_RosterState = Dict[str, Tuple[str, Optional[str]]]


def senate_congress_gov_url(congress: int, number: str) -> str:
    return f"https://www.congress.gov/bill/{congress}th-congress/senate-resolution/{number}"


def _identity(clean_name: str, bioguide: Optional[str]) -> str:
    # A resolved bioguide is a stable identity across resolutions even if the
    # printed name's formatting varies slightly; an unresolved member falls
    # back to their normalized clean name -- a known limitation (see module
    # docstring/design notes): if that name's printed form changes between
    # resolutions, diffing could see a spurious remove+re-add pair.
    return bioguide or f"name:{clean_name.lower()}"


def collect_senate_committee_changes(
    congress: int,
    *,
    client,
    gpo_fetch: Callable = gpo_fetch_resolution_xml,
    gpo_fetch_text: Callable = gpo_fetch_resolution_text,
    legislators: Optional[LegislatorIndex] = None,
    since: Optional[str] = None,
) -> List[ResolutionRecord]:
    """Return Senate committee-change resolution records for a Congress."""
    bills = client.list_committee_change_resolutions(congress, since=since, bill_type="sres")

    fetched: List[dict] = []
    for bill in bills:
        number = str(bill.get("number"))
        party = classify_senate_title(bill.get("title", ""))
        if party is None:
            # Not attributable to a majority/minority roster (e.g. a
            # party-agnostic single-Senator appointment resolution) --
            # skipped rather than guessed at. See senate_parser's docstring.
            continue

        rosters, single_adds, stage, package_id = [], [], None, None
        xml_result = gpo_fetch(congress, number, stages=SENATE_STAGES, bill_type="sres")
        if xml_result:
            xml, package_id, stage = xml_result
            rosters, single_adds = parse_senate_resolution_xml(xml)
        else:
            text_result = gpo_fetch_text(congress, number, stages=SENATE_STAGES, bill_type="sres")
            if not text_result:
                logger.warning("No bill XML or text found for SRES %s in congress %s", number, congress)
                continue
            text, package_id, stage = text_result
            rosters, single_adds = parse_senate_resolution_text(text)

        actions = client.get_actions(congress, number, bill_type="sres")
        agreed_to_date = extract_agreed_to_date(actions)

        fetched.append(
            {
                "number": number,
                "title": bill.get("title", ""),
                "party": party,
                "rosters": rosters,
                "single_adds": single_adds,
                "stage": stage,
                "package_id": package_id,
                "actions": actions,
                "agreed_to_date": agreed_to_date,
            }
        )

    # Diffing requires chronological order -- the API's own listing is sorted
    # by last-updated, not by when a resolution was agreed to. A missing date
    # sorts first (empty string), same tolerance as the rest of the pipeline.
    fetched.sort(key=lambda item: item["agreed_to_date"] or "")

    last_known: Dict[_RosterKey, _RosterState] = {}
    records: List[ResolutionRecord] = []

    for item in fetched:
        changes: List[CommitteeChange] = []
        on_date = item["agreed_to_date"]

        for roster in item["rosters"]:
            key = (roster.committee, item["party"])
            old_state = last_known.get(key, {})

            new_identities: List[str] = []
            new_state: _RosterState = {}
            for clean, raw in roster.members:
                bioguide = legislators.lookup(clean, on_date=on_date) if legislators else None
                identity = _identity(clean, bioguide)
                new_identities.append(identity)
                new_state[identity] = (clean, raw)

            new_identity_set = set(new_identities)
            added = [i for i in new_identities if i not in old_state]
            removed = [i for i in old_state if i not in new_identity_set]

            for identity in added:
                clean, raw = new_state[identity]
                changes.append(
                    CommitteeChange(
                        change_type="addition",
                        committee=roster.committee,
                        committee_code=roster.committee_code,
                        member_name=clean,
                        member_name_raw=raw,
                        bioguide_id=None if identity.startswith("name:") else identity,
                    )
                )
            for identity in removed:
                clean, raw = old_state[identity]
                changes.append(
                    CommitteeChange(
                        change_type="removal",
                        committee=roster.committee,
                        committee_code=roster.committee_code,
                        member_name=clean,
                        member_name_raw=raw,
                        bioguide_id=None if identity.startswith("name:") else identity,
                    )
                )

            last_known[key] = new_state

        for addition in item["single_adds"]:
            key = (addition.committee, item["party"])
            bioguide = legislators.lookup(addition.member, on_date=on_date) if legislators else None
            identity = _identity(addition.member, bioguide)
            changes.append(
                CommitteeChange(
                    change_type="addition",
                    committee=addition.committee,
                    committee_code=None,
                    member_name=addition.member,
                    member_name_raw=addition.member_raw,
                    bioguide_id=bioguide,
                )
            )
            last_known.setdefault(key, {})[identity] = (addition.member, addition.member_raw)

        record = ResolutionRecord(
            congress=str(congress),
            type="SRES",
            number=item["number"],
            title=item["title"],
            chamber="senate",
            stage=item["stage"],
            date=None,
            govinfo_xml_url=html_url(item["package_id"]) if item["package_id"] else None,
            congress_gov_url=senate_congress_gov_url(congress, item["number"]),
            actions=item["actions"],
            agreed_to_date=item["agreed_to_date"],
            committee_changes=changes,
        )
        records.append(record)

    return records


def collect_senate_committee_change_events(congress: int, **kwargs) -> List[CommitteeChangeEvent]:
    """Resolution path, flattened to unified committee-change events."""
    events: List[CommitteeChangeEvent] = []
    for record in collect_senate_committee_changes(congress, **kwargs):
        events.extend(to_events(record))
    return events
