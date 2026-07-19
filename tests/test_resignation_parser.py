"""Tests for parsing Congressional Record committee-resignation letters."""

from pathlib import Path

from congress_committees.parser import parse_resignation_granule

FIX = Path(__file__).parent / "fixtures"
INTEL = (FIX / "CREC-2001-02-08-pt1-PgH228-resignation.txt").read_text()
INTEL_TITLE = "RESIGNATION AS MEMBER OF HOUSE PERMANENT SELECT COMMITTEE ON INTELLIGENCE"
MULTI = (FIX / "CREC-2001-02-08-multi-resignation.txt").read_text()
MULTI_TITLE = "RESIGNATION AS MEMBER OF COMMITTEE ON AGRICULTURE AND COMMITTEE ON RESOURCES"


def test_parses_single_committee_resignation():
    result = parse_resignation_granule(INTEL_TITLE, INTEL)
    assert result.committees == ["House Permanent Select Committee on Intelligence"]
    assert result.member_name == "Charles F. Bass"
    assert result.signed_date == "2001-02-07"


def test_parses_multi_committee_resignation():
    result = parse_resignation_granule(MULTI_TITLE, MULTI)
    assert result.committees == ["Committee on Agriculture", "Committee on Resources"]
    assert result.member_name == "Jane Q. Member"


# --- signature-block variants (all from real CREC granules) ----------------


def test_parses_respectfully_valediction():
    # CREC-2026-03-25-pt1-PgH2687-5: "Respectfully," instead of "Sincerely,".
    text = (
        "Washington, DC, March 25, 2026. Hon. Mike Johnson, Speaker, House of "
        "Representatives, Washington, DC. Dear Speaker Johnson: I write to "
        "respectfully tender my resignation as a member of the Committee on "
        "Small Business effective March 25, 2026.\n"
        "     Respectfully,\n"
        "          Troy Downing,\n"
        "          Member of Congress.\n"
    )
    result = parse_resignation_granule("RESIGNATION AS MEMBER OF COMMITTEE ON SMALL BUSINESS", text)
    assert result.member_name == "Troy Downing"
    assert result.signed_date == "2026-03-25"


def test_parses_most_sincerely_valediction():
    # CREC-2025-06-25-pt1-PgH2962-3: "Most sincerely," (lowercase s).
    text = (
        "Washington, DC, June 25, 2025. Speaker Johnson: With this letter, I "
        "respectfully resign from the Transportation and Infrastructure "
        "Committee. As always, I remain,\n"
        "     Most sincerely,\n"
        "          Steven Cohen,\n"
        "          Member of Congress.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON TRANSPORTATION AND INFRASTRUCTURE", text
    )
    assert result.member_name == "Steven Cohen"


def test_parses_congressman_role_with_suffix():
    # CREC-2026-02-02-pt1-PgH1935: role "Congressman." and a ", Jr.," suffix.
    text = (
        "Washington, DC, February 2, 2026. Speaker Johnson: With this letter, "
        "I respectfully resign from the House Small Business Committee.\n"
        "     Most sincerely,\n"
        "          Herb Conaway, Jr.,\n"
        "          Congressman.\n"
    )
    result = parse_resignation_granule("RESIGNATION AS MEMBER OF COMMITTEE ON SMALL BUSINESS", text)
    assert result.member_name == "Herb Conaway, Jr."


def test_parses_congresswoman_role_with_district_line():
    # CREC-2026-06-09-pt1-PgH4037: role "Congresswoman," + district line.
    text = (
        "Hon. Mike Johnson, Speaker, House of Representatives, Washington, DC. "
        "Dear Speaker Johnson: I hereby resign my position on the House "
        "Committee on Oversight and Government Reform.\n"
        "     Sincerely,\n"
        "          Summer L. Lee,\n"
        "          Congresswoman,\n"
        "          Pennsylvania's 12th Congressional District.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON OVERSIGHT AND GOVERNMENT REFORM", text
    )
    assert result.member_name == "Summer L. Lee"


def test_parses_united_states_representative_role_with_district_line():
    # CREC-2011-06-22-pt1-PgH4420: role "United States Representative," +
    # district line -- not "Member of Congress"/"Congressman"/"Congresswoman",
    # the only variants previously recognized. Without matching this as a
    # role line, the district line ("Florida District 11.") gets wrongly
    # taken as the "name" instead of "Kathy Castor," above it.
    text = (
        "Washington, DC, June 22, 2011. Hon. John Boehner, Speaker of the "
        "House, The Capitol, Washington, DC. Dear Speaker Boehner, I am "
        "writing to notify you of my resignation from the Armed Services "
        "Committee, effective June 22, 2011.\n"
        "     Sincerely,\n"
        "          Kathy Castor,\n"
        "     United States Representative,\n"
        "          Florida District 11.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON ARMED SERVICES", text
    )
    assert result.member_name == "Kathy Castor"


def test_parses_us_representative_role_abbreviated():
    # CREC-2007-04-20-pt1-PgH3721-6: role "U.S. Representative." -- the
    # abbreviated form, not "United States Representative,".
    text = (
        "Washington, DC, Apr. 19, 2007. Hon. Nancy Pelosi, Speaker, the "
        "Capitol, Washington, DC. Dear Speaker Pelosi: I am writing to "
        "temporarily resign from my seat on the Committee on "
        "Appropriations, effective immediately.\n"
        "     Sincerely,\n"
        "          John T. Doolittle,\n"
        "        U.S. Representative.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON APPROPRIATIONS", text
    )
    assert result.member_name == "John T. Doolittle"


def test_parses_us_congressman_role_with_district_line():
    # CREC-2007-04-23-pt1-PgH3741: role "U.S. Congressman," + district line
    # -- the "U.S." prefix, not bare "Congressman,".
    text = (
        "April 20, 2007. Hon. Nancy Pelosi, Speaker of the House, "
        "Washington, DC. Dear Madam Speaker: It is my desire to resign from "
        "the House Select Committee on Intelligence immediately.\n"
        "     Sincerely,\n"
        "     Rick Renzi,\n"
        "       U.S. Congressman, First District of Arizona.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF PERMANENT SELECT COMMITTEE ON INTELLIGENCE", text
    )
    assert result.member_name == "Rick Renzi"


def test_parses_leadership_title_role_with_no_congress_wording():
    # CREC-2008-01-15-pt1-PgH5-2: role "Republican Whip." -- a House
    # leadership title, not any Congress/Representative phrasing at all.
    # Without recognizing this as a role line, it gets taken as the "name"
    # itself instead of "Roy Blunt," above it.
    text = (
        "Washington, DC, December 18, 2007. Hon. Nancy Pelosi, Speaker of "
        "the House, House of Representatives. Dear Speaker Pelosi: This "
        "letter serves as a notice of resignation from the Foreign Affairs "
        "Committee, effective today.\n"
        "     Sincere regards,\n"
        "          Roy Blunt,\n"
        "     Republican Whip.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON FOREIGN AFFAIRS", text
    )
    assert result.member_name == "Roy Blunt"


def test_parses_signature_with_no_role_line():
    # CREC-2022-02-02-pt1-PgH357-2: signature is just "Sincerely," + name, with
    # no role line ("Member of Congress."/"Congressman.") afterward at all.
    text = (
        "House of Representatives, February 1, 2022. Hon. Nancy Pelosi, "
        "Speaker, House of Representatives, Washington, DC. Dear Speaker "
        "Pelosi: I write today to request to be removed from the House "
        "Veterans Affairs Committee to allow the newly elected Representative "
        "from Florida's 20th Congressional District, Sheila "
        "Cherfilus-McCormick, to serve on this committee.\n"
        "     Sincerely,\n"
        "          Anthony G. Brown.\n"
        "\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON VETERANS' AFFAIRS", text
    )
    assert result.member_name == "Anthony G. Brown"


def test_parses_signer_when_valediction_word_appears_earlier_as_prose():
    # CREC-2019-02-13-pt1-PgH1558: the letter body itself opens a paragraph
    # with "Respectfully, I am writing to tender my resignation..." -- a
    # rhetorical use of a valediction word, not the actual sign-off. The real
    # sign-off ("Sincerely, Doris Matsui, Member of Congress.") comes after.
    text = (
        "Washington, DC, February 13, 2019. Hon. Nancy Pelosi, Speaker, House "
        "of Representatives, The Capitol, Washington, DC. Dear Speaker Pelosi: "
        "I was honored to return to serve on the Rules Committee at the start "
        "of the 116th Congress. It has been my privilege to work alongside "
        "Chairman McGovern, Ranking Member Cole, and the hardworking members "
        "that work so hard to bring serious legislation and policy to the "
        "House Floor.\n"
        "     Respectfully, I am writing to tender my resignation as a member "
        "of the Rules Committee, effective February 13, 2019.\n"
        "     Thank you for this opportunity and to my colleagues on the "
        "Committee for their hard work and friendship.\n"
        "          Sincerely,\n"
        "                    Doris Matsui,\n"
        "                    Member of Congress.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule("RESIGNATION AS MEMBER OF COMMITTEE ON RULES", text)
    assert result.member_name == "Doris Matsui"


def test_parses_semper_fidelis_valediction():
    # CREC-2020-01-15-pt1-PgH258-5: a military-veteran signer's letter closes
    # with "Semper Fidelis," instead of any of the civilian valedictions.
    text = (
        "Washington, DC, January 15, 2020. Hon. Nancy Pelosi, Speaker, House "
        "of Representatives, Washington, DC. Dear Speaker Pelosi: I write to "
        "respectfully tender my resignation as a member of the House "
        "Committee on Homeland Security. It has been an honor to serve in "
        "this capacity.\n"
        "     Semper Fidelis,\n"
        "                    Van Taylor,\n"
        "                    Member of Congress.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON HOMELAND SECURITY", text
    )
    assert result.member_name == "Van Taylor"


def test_parses_signer_regardless_of_arbitrary_valediction_wording():
    # CREC-2020-01-15-pt1-PgH274: closes with "With my deepest appreciation,"
    # -- not any of the enumerable valedictions. Signature valedictions are an
    # open-ended, creative space; this confirms extraction no longer depends
    # on recognizing the specific closing phrase at all.
    text = (
        "Washington, DC, January 8, 2020. Hon. Nancy Pelosi, Speaker, House "
        "of Representatives, Washington, DC. Dear Speaker Pelosi: I am "
        "writing to submit my formal resignation as Vice Chair of the Joint "
        "Economic Committee, effective immediately.\n"
        "     With my deepest appreciation,\n"
        "                    Carolyn B. Maloney,\n"
        "                    Member of Congress.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF JOINT ECONOMIC COMMITTEE", text
    )
    assert result.member_name == "Carolyn B. Maloney"


def test_parses_signer_with_no_valediction_at_all():
    # CREC-2024-09-18-pt1-PgH5354: no valediction word whatsoever -- the
    # letter goes straight from "Thank you." to the name, and the role clause
    # carries extra trailing text ("Nevada's 4th District.") on the same line.
    text = (
        "Washington, DC. Dear Speaker Johnson and Minority Leader Jeffries: "
        "I hereby resign from the Committee on Financial Services. Thank "
        "you.\n"
        "     Steven Horsford,\n"
        "     Member of Congress, Nevada's 4th District.\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON FINANCIAL SERVICES", text
    )
    assert result.member_name == "Steven Horsford"


def test_parses_signer_with_title_prefix_and_no_separate_role_line():
    # CREC-2015-12-08-pt1-PgH9032-6: "Congressman Vern Buchanan." -- the title
    # is a prefix directly attached to the name on ONE line, not a bare role
    # designation on its own line with the name above it. Must not mistake
    # this line for a role-clause anchor (which would wrongly grab the
    # valediction "Best Regards," above it as the "name").
    text = (
        "Washington, DC, December 4, 2015. Hon. Paul D. Ryan, Office of the "
        "Speaker, Washington, DC. Mr. Speaker, In light of my recent "
        "appointment as Chairman of the Human Resource Subcommittee on Ways "
        "and Means, I hereby resign my position on the House Budget "
        "Committee.\n"
        "     Best Regards,\n"
        "          Congressman Vern Buchanan.\n"
        "  The SPEAKER. Without objection, the resignation is accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON THE BUDGET", text
    )
    assert result.member_name == "Congressman Vern Buchanan"


def test_parses_signer_when_representative_appears_in_body_prose():
    # CREC-2022-02-02-pt1-PgH357-2: the letter body itself refers to "the
    # newly elected Representative from Florida's 20th Congressional
    # District" -- must not be mistaken for a role-clause anchor.
    text = (
        "House of Representatives, February 1, 2022. Hon. Nancy Pelosi, "
        "Speaker, House of Representatives, Washington, DC. Dear Speaker "
        "Pelosi: I write today to request to be removed from the House "
        "Veterans Affairs Committee to allow the newly elected Representative "
        "from Florida's 20th Congressional District, Sheila "
        "Cherfilus-McCormick, to serve on this committee.\n"
        "     Sincerely,\n"
        "          Anthony G. Brown.\n"
        "\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is "
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON VETERANS' AFFAIRS", text
    )
    assert result.member_name == "Anthony G. Brown"


def test_split_tolerates_and_the_committee_joiner():
    # Some titles use "... AND THE COMMITTEE ON ..." — must still split into two.
    title = "RESIGNATION AS MEMBER OF COMMITTEE ON SCIENCE AND THE COMMITTEE ON VETERANS' AFFAIRS"
    result = parse_resignation_granule(title, "")
    assert result.committees == ["Committee on Science", "Committee on Veterans' Affairs"]


def test_does_not_split_on_non_committee_and():
    # "AND" not followed by COMMITTEE/HOUSE must NOT split the name.
    title = "RESIGNATION AS MEMBER OF COMMITTEE ON BANKING AND FINANCIAL SERVICES"
    result = parse_resignation_granule(title, "")
    assert result.committees == ["Committee on Banking and Financial Services"]


def test_split_on_qualified_committee_joiner():
    # Second committee starts with a qualifier ("SELECT COMMITTEE"); the joiner
    # must still split, while an "AND" inside the second name does not.
    title = (
        "RESIGNATION AS MEMBER OF COMMITTEE ON ARMED SERVICES AND SELECT "
        "COMMITTEE ON COMPETITION BETWEEN THE UNITED STATES AND THE CHINESE "
        "COMMUNIST PARTY"
    )
    result = parse_resignation_granule(title, "")
    assert result.committees == [
        "Committee on Armed Services",
        "Select Committee on Competition Between the United States and the "
        "Chinese Communist Party",
    ]


def test_splits_three_item_oxford_comma_list():
    # CREC-2013-12-11-pt1-PgH7638-3: "A, B, AND C" -- only the LAST pair is
    # joined by "AND"; the first two are comma-separated only. The old regex
    # only split on " AND ", leaving "Committee on the Judiciary, Committee
    # on Natural Resources," glued together with a trailing comma.
    title = (
        "RESIGNATION AS MEMBER OF COMMITTEE ON THE JUDICIARY, COMMITTEE ON "
        "NATURAL RESOURCES, AND COMMITTEE ON VETERANS' AFFAIRS"
    )
    result = parse_resignation_granule(title, "")
    assert result.committees == [
        "Committee on the Judiciary",
        "Committee on Natural Resources",
        "Committee on Veterans' Affairs",
    ]


def test_oxford_comma_list_preserves_committee_with_internal_comma():
    # CREC-2013-12-11-pt1-PgH7638-5: one of the three committees in the list
    # ("Science, Space, and Technology") has its OWN internal comma-list name
    # -- must not be split apart by the same Oxford-comma-list logic.
    title = (
        "RESIGNATION AS MEMBER OF COMMITTEE ON SCIENCE, SPACE, AND "
        "TECHNOLOGY, COMMITTEE ON HOMELAND SECURITY, AND COMMITTEE ON "
        "NATURAL RESOURCES"
    )
    result = parse_resignation_granule(title, "")
    assert result.committees == [
        "Committee on Science, Space, and Technology",
        "Committee on Homeland Security",
        "Committee on Natural Resources",
    ]


def test_editorial_note_after_letter_does_not_confuse_signer_extraction():
    # CREC-2013-12-11-pt1-PgH7638-3: govinfo appends an editorial "NOTE"
    # correcting a typo in the ORIGINAL proceedings, appended after the real
    # letter. That block repeats "Without objection"/"resignation is
    # accepted" phrases, which previously threw off the trailer anchor when
    # the letter itself has no role-clause line to fall back on.
    text = (
        "Washington, DC, December 9, 2013. Hon. John Boehner, Speaker, House "
        "of Representatives, Washington, DC. Dear Speaker Boehner: I wish to "
        "resign from my assignments to the House Committee on the "
        "Judiciary.\n"
        "     Sincerely,\n"
        "          Mark E. Amodei.\n"
        "\n"
        "  The SPEAKER pro tempore. Without objection, the resignations are\n"
        "accepted.\n"
        "\n"
        "\n"
        " =========================== NOTE =========================== \n"
        "\n"
        "  \n"
        "  December 11, 2013, on page H7638, the following appeared (in\n"
        "three places): Without objection, the resignation is accepted.\n"
        "  \n"
        "  The online version should be corrected to read: Without\n"
        "objection, the resignations are accepted.\n"
        "  There was no objection.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON THE JUDICIARY", text
    )
    assert result.member_name == "Mark E. Amodei"


def test_parses_signer_with_chairman_role_line():
    # CREC-2001-02-08-pt1-PgH228-6: the signer is a committee chairman
    # resigning from a DIFFERENT committee, so the role line reads
    # "Chairman." instead of "Member of Congress."/"Representative." --
    # unrecognized, this fell back to the line-before-trailer, which WAS the
    # role line itself, returning "Chairman" as the "name".
    text = (
        "                                         House of Representatives,\n"
        "\n"
        "                                   Committee on the Judiciary,\n"
        "\n"
        "                                 Washington, DC, February 6, 2001.\n"
        "     Hon. Dennis Hastert,\n"
        "     Speaker, House of Representatives,\n"
        "     Washington, DC.\n"
        "       Dear Mr. Speaker: Effective today, I wish to resign from \n"
        "     the Committee on Science. Your assistance in accommodating my \n"
        "     request is greatly appreciated.\n"
        "           Sincerely,\n"
        "                                      F. James Sensenbrenner, Jr.,\n"
        "                                                         Chairman.\n"
        "\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is \n"
        "accepted.\n"
    )
    result = parse_resignation_granule("RESIGNATION AS MEMBER OF COMMITTEE ON SCIENCE", text)
    assert result.member_name == "F. James Sensenbrenner, Jr."


def test_parses_signer_with_district_role_line():
    # CREC-2001-02-08-pt1-PgH228-7: the role line gives a district instead
    # of "Member of Congress." ("First District, Arizona."), which fell
    # through the same way as the Chairman case above, returning "First
    # District, Arizona" as the "name".
    text = (
        "                                    Congress of the United States,\n"
        "\n"
        "                                     House of Representatives,\n"
        "\n"
        "                                 Washington, DC, February 7, 2001.\n"
        "     Hon. Dennis Hastert,\n"
        "     Speaker of The House,\n"
        "     Washington, DC.\n"
        "       Speaker Hastert: Effective today, I resign my position on \n"
        "     the House Committee on Government Reform. Thank you.\n"
        "           Sincerely,\n"
        "                                                       Jeff Flake,\n"
        "                                          First District, Arizona.\n"
        "\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is \n"
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON GOVERNMENT REFORM", text
    )
    assert result.member_name == "Jeff Flake"


def test_parses_signer_with_bare_representative_role_line():
    # CREC-2001-07-11-pt1-PgH3927: the role line is bare "Representative."
    # (not "U.S. Representative."/"United States Representative,"), which
    # was deliberately excluded from the role-line pattern out of caution
    # about colliding with body prose -- but that exclusion meant the real
    # signature block's bare "Representative." line was never recognized
    # either, returning "Representative" as the "name" instead of "Rob
    # Portman".
    text = (
        "                                    Congress of the United States,\n"
        "\n"
        "                                     House of Representatives,\n"
        "\n"
        "                                    Washington, DC, June 29, 2001.\n"
        "     Hon. J. Dennis Hastert,\n"
        "     Speaker, House of Representatives, Washington, DC.\n"
        "       Dear Mr. Speaker: I am writing to submit my resignation \n"
        "     from the Committee on Standards of Official Conduct.\n"
        "       I will consider my resignation effective immediately.\n"
        "           Sincerely,\n"
        "                                                      Rob Portman,\n"
        "                                                   Representative.\n"
        "\n"
        "  The SPEAKER pro tempore. Without objection, the resignation is \n"
        "accepted.\n"
    )
    result = parse_resignation_granule(
        "RESIGNATION AS MEMBER OF COMMITTEE ON STANDARDS OF OFFICIAL CONDUCT", text
    )
    assert result.member_name == "Rob Portman"


def test_parses_signer_with_no_role_line_and_trailing_separator():
    # CREC-1999-06-25-pt1-PgH4988-4: the letter has no role line AND no
    # "Without objection"/"resignation is accepted" trailer sentence in this
    # granule at all -- it just ends "Yours truly, Ed Bryant." followed by a
    # decorative "____________________" separator marking the end of the
    # granule. With no trailer and no role hit, the fallback took the LAST
    # line, which was that separator, as the "name".
    text = (
        "                                               Washington, DC,\n"
        "\n"
        "                                                    June 24, 1999.\n"
        "     Hon. J. Dennis Hastert,\n"
        "     The Capitol.\n"
        "       Dear Mr. Speaker: Effective immediately, I hereby resign \n"
        "     from the House Judiciary Committee.\n"
        "           Yours truly,\n"
        "     Ed Bryant.\n"
        "\n"
        "                          ____________________\n"
    )
    result = parse_resignation_granule("RESIGNATION AS MEMBER OF COMMITTEE ON THE JUDICIARY", text)
    assert result.member_name == "Ed Bryant"
