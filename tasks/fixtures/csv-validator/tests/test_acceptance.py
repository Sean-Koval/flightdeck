"""Controller-side acceptance tests. Never staged into an attempt."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from csvcheck import validate


def check(text):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "data.csv"
        path.write_text(text, encoding="utf-8")
        return [(p.line, p.code, p.detail) for p in validate(path)]


class DuplicateRows(unittest.TestCase):
    def test_duplicate_reports_the_later_line_and_the_first_occurrence(self):
        self.assertEqual(
            check("a,b\n1,2\n3,4\n1,2\n"), [(4, "duplicate-row", "same as line 2")]
        )

    def test_every_later_copy_points_at_the_first_occurrence(self):
        self.assertEqual(
            check("a,b\n1,2\n1,2\n1,2\n"),
            [(3, "duplicate-row", "same as line 2"), (4, "duplicate-row", "same as line 2")],
        )

    def test_blank_lines_count_toward_line_numbers_but_are_not_rows(self):
        self.assertEqual(check("a,b\n1,2\n\n1,2\n"), [(4, "duplicate-row", "same as line 2")])

    def test_header_is_not_a_row(self):
        self.assertEqual(check("a,b\na,b\n"), [])

    def test_comparison_is_by_parsed_fields_not_raw_text(self):
        self.assertEqual(check('a,b\n1,2\n"1","2"\n'), [(3, "duplicate-row", "same as line 2")])

    def test_whitespace_is_significant(self):
        self.assertEqual(check("a,b\n1,2\n1, 2\n"), [])

    def test_malformed_rows_are_not_compared(self):
        self.assertEqual(
            check("a,b\n1\n1\n"),
            [(2, "column-count", "expected 2 got 1"), (3, "column-count", "expected 2 got 1")],
        )

    def test_problems_are_ordered_by_line(self):
        self.assertEqual(
            check("a,b\n1,2\n1,2\n9\n"),
            [(3, "duplicate-row", "same as line 2"), (4, "column-count", "expected 2 got 1")],
        )


class ExistingBehavior(unittest.TestCase):
    def test_clean_and_empty_files_are_unchanged(self):
        self.assertEqual(check("a,b\n1,2\n3,4\n"), [])
        self.assertEqual(check(""), [(1, "empty-file", "no header")])

    def test_command_prints_problems_and_exits_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.csv"
            path.write_text("a,b\n1,2\n1,2\n", encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "csvcheck", str(path)],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout.strip(), "3:duplicate-row:same as line 2")


if __name__ == "__main__":
    unittest.main()
