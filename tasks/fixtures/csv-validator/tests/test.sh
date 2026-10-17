#!/bin/bash
# Grade csv-validator: ai-dlc's controller-side acceptance tests on the agent's csvcheck package, from a pristine copy.
# Same pattern as tasks/smoke/semver/tests/test.sh (docs/tasks.md#writing-a-safe-testsh): only csvcheck/ leaves the
# agent's tree, Python runs isolated, the reward is written last.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${FLIGHTDECK_WORKDIR:-${HANGAR_REPO:-$PWD}}
OUT=${FLIGHTDECK_REWARD_DIR:-/logs/verifier}
G=$(mktemp -d "${TMPDIR:-/tmp}/csv-grade.XXXXXX")
trap 'rm -rf "$G"' EXIT
mkdir -p "$OUT" 2>/dev/null && [ -w "$OUT" ] || OUT=$G/reward
mkdir -p "$OUT"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

if [ -d "$WORK/csvcheck" ] && [ ! -L "$WORK/csvcheck" ] && [ -z "$(find "$WORK/csvcheck" -type l)" ]; then
  mkdir "$G/run" && cp -R "$WORK/csvcheck" "$G/run/" && cp "$HERE/test_acceptance.py" "$G/run/"
  cd "$G/run" || exit 2
  timeout 300 python3 -I -c 'import os, sys, unittest; sys.path.insert(0, os.getcwd())
unittest.main(module="test_acceptance", argv=["test_acceptance", "-v"])' > "$G/out.txt" 2>&1
else
  echo "no csvcheck/ package (or a symlink in it) in $WORK" > "$G/out.txt"
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
