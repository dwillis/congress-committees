from congress_committees.dates import congress_date_span, organizing_window


def test_congress_date_span():
    assert congress_date_span(107) == ("2001-01-03", "2003-01-03")
    assert congress_date_span(119) == ("2025-01-03", "2027-01-03")


def test_organizing_window():
    assert organizing_window(119) == ("2025-01-03", "2025-01-31")
    assert organizing_window(117) == ("2021-01-03", "2021-01-31")
