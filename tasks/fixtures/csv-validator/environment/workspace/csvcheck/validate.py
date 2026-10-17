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
    if header is None:
        problems.append(Problem(1, "empty-file", "no header"))
    return problems
