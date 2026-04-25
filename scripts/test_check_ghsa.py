"""Tests for check_ghsa.py.

Run with: ``python3 -m unittest scripts.test_check_ghsa``
or ``python3 scripts/test_check_ghsa.py``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_ghsa import (  # noqa: E402
    matches_range,
    match_advisories,
)


class RangeMatchingTests(unittest.TestCase):
    def test_less_than(self):
        self.assertTrue(matches_range("1.0.0", "<1.5.0"))
        self.assertFalse(matches_range("1.5.0", "<1.5.0"))
        self.assertFalse(matches_range("2.0.0", "<1.5.0"))

    def test_less_or_equal(self):
        self.assertTrue(matches_range("1.5.0", "<=1.5.0"))
        self.assertFalse(matches_range("1.5.1", "<=1.5.0"))

    def test_greater_than(self):
        self.assertTrue(matches_range("2.0.0", ">1.5.0"))
        self.assertFalse(matches_range("1.5.0", ">1.5.0"))

    def test_greater_or_equal(self):
        self.assertTrue(matches_range("1.5.0", ">=1.5.0"))
        self.assertFalse(matches_range("1.4.9", ">=1.5.0"))

    def test_exact(self):
        self.assertTrue(matches_range("1.5.0", "=1.5.0"))
        self.assertFalse(matches_range("1.5.1", "=1.5.0"))

    def test_bare_version_is_exact(self):
        self.assertTrue(matches_range("1.5.0", "1.5.0"))
        self.assertFalse(matches_range("1.5.1", "1.5.0"))

    def test_compound_space(self):
        # Real GHSA range: jquery CVE-2020-11023.
        rng = ">=1.0.3 <3.5.0"
        self.assertTrue(matches_range("2.0.0", rng))
        self.assertFalse(matches_range("1.0.0", rng))
        self.assertFalse(matches_range("3.5.0", rng))

    def test_compound_comma(self):
        rng = ">=1.0.0, <2.0.0"
        self.assertTrue(matches_range("1.5.0", rng))
        self.assertFalse(matches_range("2.0.0", rng))

    def test_whitespace_around_comparator(self):
        self.assertTrue(matches_range("1.0.0", "< 1.5.0"))
        self.assertTrue(matches_range("1.5.0", ">= 1.5.0"))

    def test_padding(self):
        self.assertTrue(matches_range("1.5", ">=1.5.0"))
        self.assertTrue(matches_range("1.5.0", ">=1.5"))
        self.assertFalse(matches_range("1.4", ">=1.5"))

    def test_empty_range_is_no_match(self):
        self.assertFalse(matches_range("1.0.0", ""))

    def test_empty_version_is_no_match(self):
        self.assertFalse(matches_range("", "<1.0.0"))

    def test_malformed_does_not_crash(self):
        # Trailing operator with no version.
        self.assertFalse(matches_range("1.0.0", ">="))
        # Garbage.
        self.assertFalse(matches_range("1.0.0", "not a range"))
        # Operator without operand at end.
        self.assertFalse(matches_range("1.0.0", ">=1.0.0 <"))


# Realistic GHSA payload shape pulled from the API.
ADVISORY_JQUERY = {
    "ghsa_id": "GHSA-jpcq-cgw6-v4j6",
    "cve_id": "CVE-2020-11023",
    "severity": "medium",
    "state": "published",
    "html_url": (
        "https://github.com/jquery/jquery/security/advisories/"
        "GHSA-jpcq-cgw6-v4j6"
    ),
    "vulnerabilities": [
        {
            "package": {"ecosystem": "npm", "name": "jquery"},
            "vulnerable_version_range": ">=1.0.3 <3.5.0",
            "patched_versions": "3.5.0",
        }
    ],
}


class MatchAdvisoriesTests(unittest.TestCase):
    def test_matches_current_only(self):
        out = match_advisories(
            [ADVISORY_JQUERY],
            [("current", "2.0.0"), ("upstream", "3.6.0")],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["applies_to"], ["current"])
        self.assertEqual(out[0]["cve_id"], "CVE-2020-11023")

    def test_matches_upstream_only(self):
        out = match_advisories(
            [ADVISORY_JQUERY],
            [("current", "3.6.0"), ("upstream", "3.4.0")],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["applies_to"], ["upstream"])

    def test_matches_both(self):
        out = match_advisories(
            [ADVISORY_JQUERY],
            [("current", "1.5.0"), ("upstream", "3.0.0")],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["applies_to"], ["current", "upstream"])

    def test_skips_unpublished(self):
        adv = dict(ADVISORY_JQUERY)
        adv["state"] = "draft"
        out = match_advisories(
            [adv],
            [("current", "2.0.0")],
        )
        self.assertEqual(out, [])

    def test_no_match_when_versions_outside_range(self):
        out = match_advisories(
            [ADVISORY_JQUERY],
            [("current", "3.6.0"), ("upstream", "3.7.0")],
        )
        self.assertEqual(out, [])

    def test_advisory_with_no_vulnerabilities_does_not_crash(self):
        adv = {**ADVISORY_JQUERY, "vulnerabilities": None}
        out = match_advisories(
            [adv],
            [("current", "2.0.0")],
        )
        self.assertEqual(out, [])

    def test_multiple_vuln_entries_dedup_to_one_advisory(self):
        adv = {
            **ADVISORY_JQUERY,
            "vulnerabilities": [
                {"vulnerable_version_range": ">=1.0.0 <2.0.0"},
                {"vulnerable_version_range": ">=2.0.0 <3.5.0"},
            ],
        }
        out = match_advisories(
            [adv],
            [("current", "1.5.0"), ("upstream", "2.5.0")],
        )
        # One advisory reported (not two), with both labels.
        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0]["applies_to"]), {"current", "upstream"})

    def test_malformed_range_does_not_crash(self):
        adv = {
            **ADVISORY_JQUERY,
            "vulnerabilities": [
                {"vulnerable_version_range": "not-a-range"},
            ],
        }
        out = match_advisories(
            [adv],
            [("current", "1.5.0")],
        )
        self.assertEqual(out, [])

    def test_handles_non_dict_advisory(self):
        out = match_advisories(
            ["not-a-dict", None, ADVISORY_JQUERY],
            [("current", "2.0.0")],
        )
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
