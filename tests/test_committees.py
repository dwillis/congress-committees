from congress_committees.committees import CommitteeIndex

RECORDS = [
    {"systemCode": "hsfa00", "name": "Foreign Affairs Committee",
     "previous_names": ["Committee on International Relations"]},
    {"systemCode": "hsii00", "name": "Natural Resources Committee",
     "previous_names": ["Committee on Resources"]},
    {"systemCode": "hlig00", "name": "Permanent Select Committee on Intelligence",
     "previous_names": []},
]


def test_resolves_current_name():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("Committee on Foreign Affairs") == "hsfa00"


def test_resolves_previous_name():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("Committee on Resources") == "hsii00"
    assert idx.code_for("Committee on International Relations") == "hsfa00"


def test_resolves_intelligence_variant():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("House Permanent Select Committee on Intelligence") == "hlig00"


def test_unknown_returns_none():
    idx = CommitteeIndex.from_records(RECORDS)
    assert idx.code_for("Committee on Nonexistent Things") is None


def test_select_and_standing_committees_are_distinct():
    idx = CommitteeIndex.from_records([
        {"systemCode": "hshm00", "name": "Committee on Homeland Security", "previous_names": []},
        {"systemCode": "hlhm00", "name": "Select Committee on Homeland Security", "previous_names": []},
    ])
    assert idx.code_for("Committee on Homeland Security") == "hshm00"
    assert idx.code_for("Select Committee on Homeland Security") == "hlhm00"
