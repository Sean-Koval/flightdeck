#!/bin/sh
# One night's work, in order: compact the outbox (today and the 3 days before), refresh the GitHub `prs` table when
# FLIGHTDECK_GITHUB_REPOS is set, then write last week's metrics to $FLIGHTDECK_REPORTS_URI/weekly/latest.json.
# Arguments are passed to `flightdeck compact` (for example --date 2026-11-03 --rebuild).
set -eu
flightdeck compact "$@"
if [ -n "${FLIGHTDECK_GITHUB_REPOS:-}" ]; then
  flightdeck ingest github
fi
if [ -n "${FLIGHTDECK_REPORTS_URI:-}" ]; then
  flightdeck metrics weekly --format json > /dev/null
fi
