import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    line: int
    code: str
    detail: str


def validate(path):
    problems = []
    header = None
    seen = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            row = next(csv.reader([raw]))
            if header is None:
                header = row
                continue
            if len(row) != len(header):
                problems.append(
                    Problem(number, "column-count", f"expected {len(header)} got {len(row)}")
                )
                continue
            key = tuple(row)
            if key in seen:
                problems.append(Problem(number, "duplicate-row", f"same as line {seen[key]}"))
            else:
                seen[key] = number
    if header is None:
        problems.append(Problem(1, "empty-file", "no header"))
    return problems
