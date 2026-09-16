"""Unit tests for SF HF court_party parsing. Synthetic names only — not real cases."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.sf_criminal_hf.map import payload_json  # noqa: E402
from sources.sf_criminal_hf.parse_party import (  # noqa: E402
    PAYLOAD_PARSE_STATUS,
    SOURCE_SYSTEM,
    parse_parties_from_payload,
    parse_sf_criminal_hf_bronze_row,
    split_sf_person_name,
)

# Brief synthetic fixtures. Never claimed as live defendants.
SYN_FIRST_MIDDLE_LAST = "JANE Q PUBLIC"
SYN_THREE_TOKEN = "JOHN MARSHALL FIXTURE"
SYN_TWO_TOKEN = "LUIS SINGLETOKENLAST"
SYN_COMMA = "FIXTURE, LASTCOMMA FIRST"
SYN_FOUR_PLUS = "A B C D FOURTOKEN"
SYN_SINGLE = "SINGLETOKENFIXTURE"


def _payload(defendant_name: str | None, **extra: object) -> str:
    row = {
        "case_number": "CRI00000000",
        "case_id": 99,
        "defendant_name": defendant_name,
        "filed_date": "2099-01-01",
        "scraped_at": "2099-01-02T00:00:00",
    }
    row.update(extra)
    return payload_json(row)


class SplitSfPersonNameTests(unittest.TestCase):
    def test_space_first_middle_last(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(SYN_FIRST_MIDDLE_LAST)
        self.assertEqual(first, "JANE")
        self.assertEqual(middle, "Q")
        self.assertEqual(last, "PUBLIC")
        self.assertFalse(ambiguous)

    def test_space_three_token(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(SYN_THREE_TOKEN)
        self.assertEqual(first, "JOHN")
        self.assertEqual(middle, "MARSHALL")
        self.assertEqual(last, "FIXTURE")
        self.assertFalse(ambiguous)

    def test_space_two_token(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(SYN_TWO_TOKEN)
        self.assertEqual(first, "LUIS")
        self.assertEqual(last, "SINGLETOKENLAST")
        self.assertIsNone(middle)
        self.assertFalse(ambiguous)

    def test_comma_last_first_middle(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(SYN_COMMA)
        self.assertEqual(last, "FIXTURE")
        self.assertEqual(first, "LASTCOMMA")
        self.assertEqual(middle, "FIRST")
        self.assertFalse(ambiguous)

    def test_four_plus_tokens_fill_and_flag(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(SYN_FOUR_PLUS)
        self.assertEqual(first, "A")
        self.assertEqual(last, "FOURTOKEN")
        self.assertEqual(middle, "B C D")
        self.assertTrue(ambiguous)

    def test_single_token_null_parts(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(SYN_SINGLE)
        self.assertIsNone(last)
        self.assertIsNone(first)
        self.assertIsNone(middle)
        self.assertTrue(ambiguous)

    def test_unreliable_comma_does_not_invent_space_order(self) -> None:
        last, first, middle, ambiguous = split_sf_person_name(", ONLYFIRST")
        self.assertIsNone(last)
        self.assertIsNone(first)
        self.assertIsNone(middle)
        self.assertTrue(ambiguous)


class ParsePayloadTests(unittest.TestCase):
    def test_emits_one_defendant_ordinal_1(self) -> None:
        rows = parse_parties_from_payload(_payload(SYN_FIRST_MIDDLE_LAST))
        self.assertEqual(len(rows), 1)
        party = rows[0]
        self.assertEqual(party.party_role, "defendant")
        self.assertEqual(party.party_ordinal, 1)
        self.assertEqual(party.raw_name, SYN_FIRST_MIDDLE_LAST)
        self.assertEqual(party.name_first, "JANE")
        self.assertEqual(party.name_middle, "Q")
        self.assertEqual(party.name_last, "PUBLIC")
        self.assertIsNone(party.dob)
        self.assertIsNone(party.sex)
        self.assertIsNone(party.address_raw)
        self.assertEqual(party.payload_parse_status, PAYLOAD_PARSE_STATUS)
        self.assertEqual(party.dq_flags, ("missing_dob",))
        self.assertEqual(PAYLOAD_PARSE_STATUS, "json_cases_v1")

    def test_skips_blank_and_missing_name(self) -> None:
        self.assertEqual(parse_parties_from_payload(_payload("")), ())
        self.assertEqual(parse_parties_from_payload(_payload("   ")), ())
        self.assertEqual(parse_parties_from_payload(_payload(None)), ())
        self.assertEqual(parse_parties_from_payload("{}"), ())
        self.assertEqual(parse_parties_from_payload("not-json"), ())
        self.assertEqual(parse_parties_from_payload('["JANE Q PUBLIC"]'), ())

    def test_skips_non_string_name(self) -> None:
        self.assertEqual(
            parse_parties_from_payload('{"defendant_name": 12345}'),
            (),
        )

    def test_single_token_flags(self) -> None:
        party = parse_parties_from_payload(_payload(SYN_SINGLE))[0]
        self.assertEqual(party.raw_name, SYN_SINGLE)
        self.assertIsNone(party.name_last)
        self.assertIn("missing_dob", party.dq_flags)
        self.assertIn("ambiguous_name_parts", party.dq_flags)
        self.assertIn("name_unparsed", party.dq_flags)

    def test_four_token_flags_without_name_unparsed(self) -> None:
        party = parse_parties_from_payload(_payload(SYN_FOUR_PLUS))[0]
        self.assertEqual(party.name_first, "A")
        self.assertIn("missing_dob", party.dq_flags)
        self.assertIn("ambiguous_name_parts", party.dq_flags)
        self.assertNotIn("name_unparsed", party.dq_flags)

    def test_does_not_emit_plaintiff_or_aka(self) -> None:
        rows = parse_parties_from_payload(_payload(SYN_TWO_TOKEN))
        self.assertEqual([p.party_role for p in rows], ["defendant"])

    def test_dict_payload_accepted(self) -> None:
        rows = parse_parties_from_payload({"defendant_name": SYN_TWO_TOKEN})
        self.assertEqual(rows[0].name_first, "LUIS")
        self.assertEqual(rows[0].name_last, "SINGLETOKENLAST")


class ParseBronzeRowTests(unittest.TestCase):
    def test_wrong_source_system_yields_nothing(self) -> None:
        self.assertEqual(
            parse_sf_criminal_hf_bronze_row(
                source_system="wcca",
                payload=_payload(SYN_FIRST_MIDDLE_LAST),
            ),
            (),
        )

    def test_sf_source_parses(self) -> None:
        rows = parse_sf_criminal_hf_bronze_row(
            source_system=SOURCE_SYSTEM,
            payload=_payload(SYN_COMMA),
        )
        self.assertEqual(rows[0].name_last, "FIXTURE")
        self.assertEqual(rows[0].name_first, "LASTCOMMA")
        self.assertEqual(rows[0].name_middle, "FIRST")

    def test_does_not_read_live_pii_from_other_keys(self) -> None:
        payload = json.dumps(
            {
                "case_number": "CRI00000000",
                "case_id": 7,
                "defendant_name": "",
                "caption": "JANE Q PUBLIC vs. CITY",
            }
        )
        self.assertEqual(parse_parties_from_payload(payload), ())


if __name__ == "__main__":
    unittest.main()
