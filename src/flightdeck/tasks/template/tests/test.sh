#!/bin/bash
# Grade one trial: run the hidden tests on the agent's work from a pristine copy, write reward.json (docs/tasks.md).
#   the agent's tree   $FLIGHTDECK_WORKDIR, else $HANGAR_REPO (hangar's grader), else the current directory (Harbor)
#   these tests        this script's directory, copied out before anything of the agent's runs
#   the reward         $FLIGHTDECK_REWARD_DIR/reward.json, else /logs/verifier/reward.json; also $HANGAR_GRADE_OUT
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${FLIGHTDECK_WORKDIR:-${HANGAR_REPO:-$PWD}}
OUT=${FLIGHTDECK_REWARD_DIR:-/logs/verifier}
G=$(mktemp -d "${TMPDIR:-/tmp}/grade.XXXXXX")
trap 'rm -rf "$G"' EXIT
mkdir -p "$OUT" 2>/dev/null && [ -w "$OUT" ] || OUT=$G/reward
mkdir -p "$OUT"
cp -R "$HERE" "$G/tests" && rm -f "$G/tests/test.sh"   # the pristine copy, outside the agent's tree
cp -R "$WORK" "$G/work"                                 # the code under test
rm -rf "$G/work/.git"
cd "$G" || exit 2
# Nothing the agent's tree carries loads first: --noconftest skips every conftest.py, -c /dev/null its pytest
# settings, python -I its sitecustomize.py, user site and PYTHON* variables. The tests import from $GRADE_WORK.
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 GRADE_WORK="$G/work"
timeout 600 python3 -I -m pytest --noconftest -p no:cacheprovider -c /dev/null --rootdir "$G" -o addopts= -q \
  "$G/tests"
code=$?
reward=0; [ "$code" -eq 0 ] && reward=1
echo "{\"reward\": $reward, \"exit_code\": $code}" > "$OUT/reward.json"
[ -n "${HANGAR_GRADE_OUT:-}" ] && cp "$OUT/reward.json" "$HANGAR_GRADE_OUT"
exit "$code"
