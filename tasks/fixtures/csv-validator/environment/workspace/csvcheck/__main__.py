import sys

from csvcheck.validate import validate


def main(argv):
    if len(argv) != 2:
        print("usage: python -m csvcheck FILE", file=sys.stderr)
        return 2
    problems = validate(argv[1])
    for problem in problems:
        print(f"{problem.line}:{problem.code}:{problem.detail}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
