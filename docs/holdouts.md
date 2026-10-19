# Holdouts

!!! note "Status"
    Code merged ([#52](https://github.com/Sean-Koval/flightdeck/pull/52)); issue [#13](https://github.com/Sean-Koval/flightdeck/issues/13) stays open until two blind writers produce the first sealed set
    (at least 20 regression tasks), the age key pair and its offline backup exist, and the manifest's
    `min_hangar_version` names the first hangar release with grader isolation.

A sealed holdout is a set of tasks that nobody tuning a harness has seen, scored **once**, when a search winner or a
promotion needs one honest number. Custody is what keeps it unseen: hashes that refuse an edited file, canaries that
detect a leak, writers who never read the code they're testing, and an approver who isn't the candidate's author. The
rules are [ADR 0006](decisions/0006-holdout-custody.md); the discipline is Tower's (formerly the governed workspace), ported. Code:
`src/flightdeck/tasks/custody.py`, `flightdeck holdout ...`.

## Where things live

Everything is in the private data repository's `holdouts/` directory ([ADR-0002](decisions/0002-public-code-private-data.md)),
never in this repository:

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

1. **Briefs.** `flightdeck holdout brief reg-2 --writers 2 --count 20 --family regression --mined-after 2026-10-01`
   writes `briefs/reg-2_writer_{a,b}.txt` in Tower's blind-writer shape: what the set is for, the
   format, "do NOT read any file in this repository except what you create under `holdouts/incoming/<writer>/`",
   and a check before delivering. Give each brief to a writer (a person or an agent session in its own sandbox) who is
   not the author of any change the set will judge. Writers leave their tasks in `incoming/<writer>/`, uncommitted.
2. **Seal.** `flightdeck holdout seal reg-2 --writer a=<harness or person> --writer b=... --fresh-after <date>` checks
   each task (it loads, `[flightdeck] sealed = true`, `mined_after` later than `--fresh-after`, task ids unique),
   appends a unique `FLIGHTDECK-CANARY-<uuid>` to its `instruction.md` and `tests/test.sh`, rewrites its
   `files_digest`, moves it to `sealed/reg-2/` without anyone reading it, and records every file's sha256. A set name is
   used once: sealing into an existing set is refused. Commit `manifest.json` on its own (adding or changing entries
   is its own commit), then encrypt and upload `sealed/reg-2/` (below) and delete the plaintext.
3. **Run.** When a candidate needs its number, decrypt the set, submit it as an experiment pinned to the candidate
   (`flightdeck experiment run`, one variant), and collect it into the data plane. Sealed tasks never run on the local
   backend (it refuses them); hangar's grader must run with egress `none`, or a patch can exfiltrate the hidden tests.
4. **Score once.** `flightdeck holdout score reg-2 --run-set <id> --against <harness_digest> --approve <login>
   --author <login> --by <login> --data <plane>` refuses unless:
   - the set is `sealed` (a `scored` or `void` set is refused, naming when and by whom it was scored);
   - the approver differs from the candidate's author and from whoever runs the scoring, and no writer of the set is
     the candidate's author;
   - every sealed file still matches the manifest (the refusal names the path and both hashes);
   - the run set covers every task of the set, pinned to `--against` (`harness_digest`, else `config_digest` until
     hangar emits it), on a hangar at least `min_hangar_version` (from each trial's manifest).
   It writes `results/<set>.json` (resolved count, Wilson interval, per task) and the manifest's `scored_at`,
   `scored_by`, `scored_against` and `approved_by`, and commits both together when `holdouts/` is a git checkout.
5. **Watch for leaks.** `flightdeck holdout canary-scan --data <plane> --since 7 [--logs retrieval.log ...]
   [--alerts-repo owner/repo]` searches the last days' spans (tool input and output, attributes) and events (message
   text, attributes), plus any retrieval logs, for canary strings. A hit marks its set `void` with the reason, opens an
   issue when `--alerts-repo` is given, and exits 1. Run it nightly beside `flightdeck check run`.

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
these. **Losing the key loses every sealed set**: keep a second copy of the private key offline (printed, in the team
safe), and test a restore when a set is sealed.

## Cadence

A sealed set is spent the first time it's scored. Plan one new set per promotion cycle, written by fresh writers from
work merged after the last set's `fresh_after`, rather than a reusable test set. A voided set is replaced the same way.
