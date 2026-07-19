"""Congress-number ↔ calendar-date helpers."""

from typing import Tuple


def congress_date_span(congress: int) -> Tuple[str, str]:
    """Return (start, end) ISO dates for a Congress. Congress 1 began 1789-01-03."""
    start_year = 1789 + (congress - 1) * 2
    return f"{start_year}-01-03", f"{start_year + 2}-01-03"


def organizing_window(congress: int) -> Tuple[str, str]:
    """(start, end) ISO dates of a Congress's organizing window: Jan 3-31 of its
    first session, when chairs/ranking members are elected in single-member
    resolutions and rank-and-file members in party-seniority-ordered lists."""
    start_year = 1789 + (congress - 1) * 2
    return f"{start_year}-01-03", f"{start_year}-01-31"
