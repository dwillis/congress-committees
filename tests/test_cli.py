from congress_committees.cli import build_parser


def test_source_flag_defaults_to_all():
    args = build_parser().parse_args(["--congress", "119"])
    assert args.source == "all"


def test_source_flag_accepts_record():
    args = build_parser().parse_args(["--congress", "119", "--source", "record"])
    assert args.source == "record"


def test_no_committee_codes_flag():
    args = build_parser().parse_args(["--congress", "119", "--no-committee-codes"])
    assert args.no_committee_codes is True
