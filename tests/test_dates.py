from congress_committees.dates import congress_date_span


def test_congress_date_span():
    assert congress_date_span(107) == ("2001-01-03", "2003-01-03")
    assert congress_date_span(119) == ("2025-01-03", "2027-01-03")
