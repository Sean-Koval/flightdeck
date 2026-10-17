#!/bin/bash
# Grade the semver smoke task: run the hidden tests on the agent's semver.py from a pristine copy, write reward.json.
#
# Where things are (docs/tasks.md#writing-a-safe-testsh):
#   the agent's tree   $FLIGHTDECK_WORKDIR, else $HANGAR_REPO (hangar's grader), else the current directory (Harbor)
#   these tests        the directory of this script (Harbor: /tests; hangar: $HANGAR_HIDDEN_TESTS/<task>/tests)
#   the reward         $FLIGHTDECK_REWARD_DIR/reward.json, else /logs/verifier/reward.json (Harbor); also
#                      $HANGAR_GRADE_OUT when hangar sets it
# Only semver.py leaves the agent's tree: nothing it carries (conftest.py, pytest settings, sitecustomize.py, *.pth)
# is in the directory the tests run from, and Python runs isolated (-I: no user site, no PYTHON* variables).
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${FLIGHTDECK_WORKDIR:-${HANGAR_REPO:-$PWD}}
OUT=${FLIGHTDECK_REWARD_DIR:-/logs/verifier}
G=$(mktemp -d "${TMPDIR:-/tmp}/semver-grade.XXXXXX")
trap 'rm -rf "$G"' EXIT
mkdir -p "$OUT" 2>/dev/null && [ -w "$OUT" ] || OUT=$G/reward
mkdir -p "$OUT"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

if [ -f "$WORK/semver.py" ] && [ ! -L "$WORK/semver.py" ]; then
  cp "$WORK/semver.py" "$G/semver.py"
  cp "$HERE/hidden_test_semver.py" "$G/"
  cd "$G" || exit 2
  if python3 -I -c 'import pytest' 2>/dev/null; then
    timeout 300 python3 -I -m pytest --noconftest -p no:cacheprovider -c /dev/null --rootdir "$G" -o addopts= -v \
      hidden_test_semver.py > "$G/out.txt" 2>&1
  else
    timeout 300 python3 -I hidden_test_semver.py -v > "$G/out.txt" 2>&1
  fi
else
  echo "no semver.py (or a symlink) in $WORK" > "$G/out.txt"
fi

python3 -I - "$G/out.txt" "$OUT/reward.json" "${HANGAR_GRADE_OUT:-}" <<'EOF'
import collections, json, re, sys
out, reward_path, hangar_out = sys.argv[1:4]
tot, ok, fails = collections.Counter(), collections.Counter(), []
for ln in open(out, errors="replace"):
    # unittest: "test_cat__007 (...) ... ok"; pytest: "hidden_test_semver.py::Hidden::test_cat__007 PASSED"
    m = re.match(r"test_([a-z_]+?)__(\d+) .*\.\.\. (ok|FAIL|ERROR)", ln) or \
        re.search(r"::test_([a-z_]+?)__(\d+) (PASSED|FAILED|ERROR)", ln)
    if m:
        tot[m.group(1)] += 1
        if m.group(3) in ("ok", "PASSED"):
            ok[m.group(1)] += 1
        else:
            fails.append(f"{m.group(1)}#{m.group(2)}")
passed, total = sum(ok.values()), sum(tot.values())
reward = 1 if total and passed == total else 0
# Harbor's reward.json takes numbers only; the categories go to RESULT and to hangar's grade
json.dump({"reward": reward, "passed": passed, "total": total}, open(reward_path, "w"))
result = {"reward": reward, "passed": passed, "total": total,
          "by_category": {k: [ok[k], tot[k]] for k in sorted(tot)}, "failed": fails}
if hangar_out:
    with open(hangar_out, "w") as f:
        json.dump(result, f)
print("RESULT " + json.dumps(result))
sys.exit(0 if reward else 1)
EOF
