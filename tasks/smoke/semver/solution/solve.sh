#!/bin/bash
# Harbor's oracle: put the reference semver.py in the agent's working directory and commit it.
set -eu
cp "$(dirname "${BASH_SOURCE[0]}")/semver.py" ./semver.py
git add semver.py 2>/dev/null && git -c user.name=oracle -c user.email=oracle@localhost commit -qm "semver: reference" || true
