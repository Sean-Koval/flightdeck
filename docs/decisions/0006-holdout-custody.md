# 0006: Sealed holdouts are hash-manifested, canaried, written blind and scored once

Status: Accepted · Oct 17, 2026 (agent-proposed; owner review requested)

## Context

Every search winner and every promotion gets measured once on held-out tasks (#13). A held-out set that anyone tuning
the harness can read, or that is scored repeatedly, stops measuring generalization: it becomes one more thing to fit.
The governed workspace (now Tower) already practices custody for its labelled sets, and flightdeck may reuse it:

- `server/evals/manifest.json` lists every labelled set with its sha256, and `aw.rules_report.check_manifest`
  (`server/aw/rules_report.py:32-46`) refuses to score a listed file whose hash differs.
- Independent writers work from briefs without reading the repository (`server/evals/briefs/blind_v2_writer_a.txt`:
  "do NOT read any file in this repository except what you create under ...").
- Sealed sets in `server/evals/sealed/` were "scored once, on the user's go-ahead"
  (`docs/research/2026-10-09-risk-rules-v4.md`).

## Options

| Option | What it is | For | Against |
| --- | --- | --- | --- |
| A. A reusable test set | One held-out suite, scored whenever needed | Cheap | Repeated scoring leaks it into decisions; no longer held out |
| B. Port the governed workspace's custody | Hashes, blind writers, scored once, plus canaries and encryption | Practiced already; each rule closes a known leak | Writers cost time every promotion cycle |

## Decision

B. `flightdeck holdout` (docs/holdouts.md) enforces:

1. **Manifest.** `holdouts/manifest.json` in the private data repo holds every sealed file's sha256. A listed file
   that is missing or whose hash differs is refused, naming the path and both hashes. Adding or changing entries is
   its own commit.
2. **Sealed storage.** Sealed task directories are encrypted at rest in the team bucket and never committed to the
   data repo's default branch, so no indexer, retrieval tool or agent reads them. The key lives in Secret Manager
   with an offline backup.
3. **Canaries.** Sealing appends a unique `FLIGHTDECK-CANARY-<uuid>` to each task's `instruction.md` and `tests/`. A
   canary found in traces or retrieval logs voids its set.
4. **Blind writers.** Sets are written from briefs by writers who read nothing else in the repository and are not
   the authors (people or agent sessions) of the changes the set judges. Writer identity and harness are recorded.
5. **Freshness.** Tasks record `mined_after`, which must be later than both the knowledge snapshot and the model's
   training cutoff.
6. **Scored once.** Scoring needs an approver who is neither the candidate's author nor whoever runs it, a run set
   that covers every task pinned to the candidate, and a hangar version with grader isolation (egress `none`). It
   records `scored_at`, `scored_by`, `scored_against` in the manifest in the same commit as the result, and a scored
   set is never scored again.

## Consequences

- One new set per promotion cycle: writer time is the recurring cost.
- Losing the encryption key loses the holdouts; the runbook covers the backup.
- The first set (two writers, at least 20 regression tasks) is an owner action in the private data repo; its manifest
  commit is linked from #13.
- Shadows as a continuous holdout are #31's, not this ADR's.
