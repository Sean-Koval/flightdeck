# Holdouts

A sealed holdout is a set of tasks nobody tuning a harness has seen, scored **once**, when a promotion needs one
honest number.

Custody is what keeps it unseen. Hashes refuse an edited file; canaries detect a leak; writers never read the code
they're testing; the approver isn't the candidate's author. The rules are
[ADR 0006](decisions/0006-holdout-custody.md); the discipline is Tower's, ported. Code:
`src/flightdeck/tasks/custody.py`, `flightdeck holdout ...`.

## Where things live

Everything is in the private data repository's `holdouts/` directory
([ADR-0002](decisions/0002-public-code-private-data.md)), never in this repository:

```
holdouts/
  manifest.json        committed: every sealed file's sha256, and each set's tasks, writers, canaries and status
  briefs/              committed: the writers' briefs
  results/<set>.json   committed: the one scoring, in the same commit as the manifest's scored_* fields
  incoming/<writer>/   never committed (.gitignore): a writer's tasks before sealing
  sealed/<set>/        never committed: sealed task directories, encrypted at rest in the bucket
```

`manifest.json`:

```json
{"files": {"sealed/reg-1/fix-retry/tests/test.sh": "<sha256>", "...": "..."},
 "min_hangar_version": "<the first hangar with grader isolation>",
 "sets": {"reg-1": {"tasks": {"fix-retry": "a"}, "writers": {"a": "<harness or person>"},
                    "canaries": {"fix-retry": "FLIGHTDECK-CANARY-<uuid>"}, "status": "sealed|scored|void",
                    "sealed_at": "...", "fresh_after": "YYYY-MM-DD",
                    "scored_at": null, "scored_by": null, "scored_against": null}}}
```

## The cycle

<div class="af-figure" markdown>
--8<-- "docs/assets/flow-holdout.svg"
<figcaption>Custody of a sealed set: briefed, written blind, sealed, run once, scored once; scanned nightly</figcaption>
</div>

### 1. Briefs

`flightdeck holdout brief reg-2 --writers 2 --count 20 --family regression --mined-after 2026-10-01` writes
`briefs/reg-2_writer_{a,b}.txt` in Tower's blind-writer shape. A brief says what the set is for and the format. Then
it says "do NOT read any file in this repository except what you create under `holdouts/incoming/<writer>/`", and
gives a check before delivering.

Give each brief to a writer who is not the author of any change the set will judge. That can be a person, or an agent
session in its own sandbox. Writers leave their tasks in `incoming/<writer>/`, uncommitted.

### 2. Seal

`flightdeck holdout seal reg-2 --writer a=<harness or person> --writer b=... --fresh-after <date>` checks each task:
it loads, `[flightdeck] sealed = true`, `mined_after` is later than `--fresh-after`, task ids are unique.

Then it appends a unique `FLIGHTDECK-CANARY-<uuid>` to its `instruction.md` and `tests/test.sh` and rewrites its
`files_digest`. It moves the task to `sealed/reg-2/` without anyone reading it, and records every file's sha256. A
set name is
used once; sealing into an existing set is refused.

Commit `manifest.json` on its own: adding or changing entries is its own commit. Then encrypt and upload
`sealed/reg-2/` (below) and delete the plaintext.

### 3. Run

When a candidate needs its number, decrypt the set. Submit it as an experiment pinned to the candidate
(`flightdeck experiment run`, one variant), and collect it into the data plane.

Sealed tasks never run on the local backend; it refuses them. Hangar's grader must run with egress `none`, or a patch
can exfiltrate the hidden tests.

### 4. Score once

`flightdeck holdout score reg-2 --run-set <id> --against <harness_digest> --approve <login> --author <login>
--by <login> --data <plane>` refuses unless:

- the set is `sealed`: a `scored` or `void` set is refused, naming when and by whom it was scored;
- the approver differs from the candidate's author and from whoever runs the scoring, and no writer of the set is
  the candidate's author;
- every sealed file still matches the manifest: the refusal names the path and both hashes;
- the run set covers every task of the set, pinned to `--against` (`harness_digest`, else `config_digest` until
  hangar emits it), on a hangar at least `min_hangar_version` (from each trial's manifest).

It writes `results/<set>.json` (resolved count, Wilson interval, per task) and the manifest's `scored_at`,
`scored_by`, `scored_against` and `approved_by`. When `holdouts/` is a git checkout, it commits both together.

### 5. Watch for leaks

`flightdeck holdout canary-scan --data <plane> --since 7 [--logs retrieval.log ...] [--alerts-repo owner/repo]`
searches the last days' spans (tool input and output, attributes) and events (message text, attributes), plus any
retrieval logs, for canary strings.

A hit marks its set `void` with the reason, opens an issue when `--alerts-repo` is given, and exits 1. Run it nightly
beside `flightdeck check run`.

## Encryption at rest

Sealed directories are never checked out on the data repository's default branch, so no indexer, retrieval tool or
agent can read them. At rest they are in the team bucket, encrypted with [`age`](https://age-encryption.org) under a
key kept in Secret Manager (or the bucket's CMEK):

```sh
tar -C holdouts/sealed -c reg-2 | age -r "$(gcloud secrets versions access latest --secret flightdeck-holdout-pub)" \
  | gcloud storage cp - gs://<team>-flightdeck/sealed/reg-2.tar.age
rm -rf holdouts/sealed/reg-2
# to score: fetch, decrypt with the private key, score, delete the plaintext again
gcloud storage cp gs://<team>-flightdeck/sealed/reg-2.tar.age - \
  | age -d -i <(gcloud secrets versions access latest --secret flightdeck-holdout-key) | tar -C holdouts/sealed -x
```

Flightdeck holds no key and no credential ([ADR-0001](decisions/0001-boundary-with-hangar.md)); the operator runs
these. **Losing the key loses every sealed set.** Keep a second copy of the private key offline, printed, in the team
safe. Test a restore when a set is sealed.

## Cadence

A sealed set is spent the first time it's scored. Plan one new set per promotion cycle, written by fresh writers from
work merged after the last set's `fresh_after`, rather than a reusable test set. A voided set is replaced the same
way.

!!! note "Status"
    Code merged ([#52](https://github.com/Sean-Koval/flightdeck/pull/52)). Issue
    [#13](https://github.com/Sean-Koval/flightdeck/issues/13) stays open until three things exist. The first sealed set
    from two blind writers, at least 20 regression tasks. The age key pair and its offline backup. A manifest
    `min_hangar_version` naming the first hangar release with grader isolation.

## See also

- [ADR 0006: Holdout custody](decisions/0006-holdout-custody.md): the rules this page carries out.
- [Tasks](tasks.md): the task directory a writer produces, with `sealed = true`.
- [Running experiments](runners.md): the one-variant experiment a set runs as.
- [Knowledge evals](knowledge-evals.md): the other sealed set, for retrieval.
