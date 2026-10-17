import tempfile
import unittest
from pathlib import Path

from csvcheck import Problem, validate


def check(text):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "data.csv"
        path.write_text(text, encoding="utf-8")
        return validate(path)


class ValidateTests(unittest.TestCase):
    def test_clean_file(self):
        self.assertEqual(check("a,b\n1,2\n"), [])

    def test_column_count(self):
        self.assertEqual(check("a,b\n1\n"), [Problem(2, "column-count", "expected 2 got 1")])

    def test_empty_file(self):
        self.assertEqual(check("\n\n"), [Problem(1, "empty-file", "no header")])


if __name__ == "__main__":
    unittest.main()
