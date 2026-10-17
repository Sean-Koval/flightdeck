#!/bin/bash
# Harbor's oracle: the reference validate.py, the fixture's own tests, then a commit. The local runner's deterministic
# driver runs the same steps from deterministic.json, one command per step.
set -eu
cp "$(dirname "${BASH_SOURCE[0]}")/validate.py" csvcheck/validate.py
python -m unittest discover -s tests
git add -A && git -c user.name=oracle -c user.email=oracle@localhost commit -qm "csvcheck: report duplicate rows"
