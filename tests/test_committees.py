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


class _FakeClient:
    """Offline stand-in for CongressGovClient with no network."""

    def __init__(self):
        self.history_calls = []

    def list_committees(self, chamber="house"):
        return [
            {"systemCode": "hsii00", "name": "Natural Resources Committee"},
            {"systemCode": "hzxx00", "name": "Sub", "parent": {"systemCode": "hsii00"}},
        ]

    def get_committee(self, system_code, chamber="house"):
        self.history_calls.append(system_code)
        if system_code == "hsii00":
            return {"history": [
                {"officialName": "Committee on Natural Resources",
                 "libraryOfCongressName": "Natural Resources"},
                {"officialName": "Committee on Resources",
                 "libraryOfCongressName": "Resources",
                 "endDate": "2007-01-02T05:00:00Z"},
            ]}
        return {"history": []}


def test_from_client_folds_history_and_skips_subcommittees():
    fake = _FakeClient()
    idx = CommitteeIndex.from_client(fake)
    # Renamed historical name resolves to the current code.
    assert idx.code_for("Committee on Resources") == "hsii00"
    # Current official name also resolves.
    assert idx.code_for("Committee on Natural Resources") == "hsii00"
    # The subcommittee was skipped: its detail was never fetched.
    assert fake.history_calls == ["hsii00"]
