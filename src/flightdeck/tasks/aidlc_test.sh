#!/bin/bash
# Grade an imported ai-dlc scenario (flightdeck task import-aidlc): its hidden test_*.py with unittest, as ai-dlc's
# controller did (`PYTHONPATH=. python -m unittest discover -s ../hidden`), on a copy of the agent's tree without .git.
# Safer than ai-dlc's: Python runs isolated (-I), from a pristine copy, and the reward is written last
# (docs/tasks.md#writing-a-safe-testsh). It copies the whole tree because the importer can't know the code under test;
# narrow the copy to that package when you can (tasks/fixtures/csv-validator/tests/test.sh does).
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${FLIGHTDECK_WORKDIR:-${HANGAR_REPO:-$PWD}}
OUT=${FLIGHTDECK_REWARD_DIR:-/logs/verifier}
G=$(mktemp -d "${TMPDIR:-/tmp}/aidlc-grade.XXXXXX")
trap 'rm -rf "$G"' EXIT
mkdir -p "$OUT" 2>/dev/null && [ -w "$OUT" ] || OUT=$G/reward
mkdir -p "$OUT"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

if [ -d "$WORK" ] && [ -z "$(find "$WORK" -path "$WORK/.git" -prune -o -type l -print)" ]; then
  mkdir -p "$G/run/hidden" && cp "$HERE"/test_*.py "$G/run/hidden/"
  (cd "$WORK" && tar --exclude=./.git -cf - .) | (mkdir "$G/run/project" && cd "$G/run/project" && tar -xf -)
  cd "$G/run/project" || exit 2
  timeout 600 python3 -I -c 'import os, sys, unittest; sys.path.insert(0, os.getcwd())
unittest.main(module=None, argv=["unittest", "discover", "-s", "../hidden", "-p", "test_*.py", "-v"])' \
    > "$G/out.txt" 2>&1
else
  echo "no work tree at $WORK, or a symlink in it" > "$G/out.txt"
fi

python3 -I - "$G/out.txt" "$OUT/reward.json" "${HANGAR_GRADE_OUT:-}" <<'PY'
import json, re, sys
out, reward_path, hangar_out = sys.argv[1:4]
text = open(out, errors="replace").read()
ran = re.search(r"^Ran (\d+) tests? in ", text, re.M)
total = int(ran.group(1)) if ran else 0
bad = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", text))
ok = bool(ran) and re.search(r"^OK\b", text, re.M) is not None
passed = total - bad if ran else 0
reward = 1 if ok and total else 0
json.dump({"reward": reward, "passed": passed, "total": total}, open(reward_path, "w"))
result = {"reward": reward, "passed": passed, "total": total,
          "failed": re.findall(r"^(?:FAIL|ERROR): (\S+)", text, re.M)}
if hangar_out:
    with open(hangar_out, "w") as f:
        json.dump(result, f)
print(text[-4000:])
print("RESULT " + json.dumps(result))
sys.exit(0 if reward else 1)
PY
