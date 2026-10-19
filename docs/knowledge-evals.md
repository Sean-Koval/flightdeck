# Knowledge evals

A gold set of 40 questions, written by people and sealed, decides whether the team builds a retrieval service at all.
Each arm is scored once.

The knowledge plan builds no team retrieval service unless the gold set shows the baselines **losing by at least
15 points** on correctness or citation validity. The baselines are repo search and Claude Projects.

Flightdeck seals the set, scores each arm once, and keeps it as the regression gate for any retrieval tool a harness
later pins. Code: `src/flightdeck/tasks/knowledge.py`, `flightdeck knowledge ...`.

## The suite

`suites/knowledge-gold-v1/` in the private data repository ([ADR-0002](decisions/0002-public-code-private-data.md)):
questions can reference private decisions.

```
questions.jsonl   {id, question, kind, as_of, scope}: what an arm may read
keys.jsonl        {id, answer_key, required_facts[], valid_sources[{uri, sha256}], canary}: sealed until scored
manifest.json     sha256 of both files, written by `knowledge seal`
answers/<arm>.jsonl       {id, answer, citations[{uri, sha256}]}
answers/<arm>.meta.json   how the arm was run: person or harness, date, model, knowledge_snapshot
labels/<arm>.jsonl        {id, rater, correct, unsupported[uris]}
```

### Fields

`kind` is one of `decision-why`, `blocker`, `what-changed`, `how-to`, `who-owns`.

`as_of` pins the repository commits an arm may read. Decisions drift, so a changed question is a new version
(`knowledge-gold-v2`), never an edit. `knowledge seal` refuses an already sealed suite, and `knowledge score` refuses
a suite whose files no longer match `manifest.json`.

`valid_sources` are the sources that support the answer, each with its content's sha256 at `as_of`.

### Canaries

`seal` gives every answer key a canary ([holdouts](holdouts.md)). With `--holdouts <dir>` the canaries join that
manifest, so `flightdeck holdout canary-scan` voids the suite when one shows up in a trace or a retrieval log.

## Arms

### baseline-repo-search

An agent with only repository read and grep tools on the `as_of` commits, run as hangar trials through
`flightdeck experiment run`. Each question is one task; its answer and citations are written to a result file.

### baseline-projects

Claude Projects with the AI SDLC project's documents attached, run by a person or through the API. It can't be fully
automated, so `answers/baseline-projects.meta.json` records who ran it, when and with which model.
`knowledge score` prints each arm's meta, or says it is missing.

### retrieval:<tool>@<version>

Later: a harness with that retrieval MCP pinned, recording `knowledge.snapshot` from the manifest.

## Scoring

```sh
flightdeck knowledge seal suites/knowledge-gold-v1 --holdouts holdouts
flightdeck knowledge score suites/knowledge-gold-v1 --arm baseline-repo-search --arm baseline-projects \
  [--baseline baseline-repo-search --candidate retrieval]
```

### Correctness

Every required fact is present. Until a rubric judge is calibrated
([#27](https://github.com/Sean-Koval/flightdeck/issues/27), κ ≥ 0.6), two people rate each answer
(`labels/<arm>.jsonl`, `correct` true or false). The majority decides, and a tie counts as incorrect. The report
prints Cohen's κ between the first two raters.

### Citation validity

An answer is valid when it cites at least one source and every citation is valid. Each citation is one of:

- *fabricated*: not among the question's `valid_sources`;
- *stale*: a listed source whose cited content hash differs from the one at `as_of`;
- *unsupported*: a rater lists the uri in `unsupported`, because the cited span doesn't support the claim;
- *valid*: otherwise.

Fabricated, stale and unsupported citations are counted separately in the report.

### The report

Per arm: correctness and citation validity with 95% Wilson intervals, and the citation counts.

With `--baseline` and `--candidate`, it adds the paired difference per metric (bootstrap over questions, seeded) and
the rule in plain words. When an interval's lower bound reaches +15 points: "*baseline* is shown to lose by at least
15 points on ...". Otherwise: "*baseline* is not shown to lose by 15 points".

Link the report from [#21](https://github.com/Sean-Koval/flightdeck/issues/21) and from the knowledge ADR once both
baselines are scored.

!!! note "Status"
    Code merged ([#54](https://github.com/Sean-Koval/flightdeck/pull/54)). Issue
    [#21](https://github.com/Sean-Koval/flightdeck/issues/21) stays open until the 40 questions are written, sealed
    and both baselines scored once in the private data repository.

## See also

- [Holdouts](holdouts.md): the custody rules the gold set borrows, and the canary scan.
- [Judges](judges.md): the calibrated rubric that will replace the two human raters.
- [Statistics](statistics.md): Wilson intervals and the paired bootstrap.
- [Running experiments](runners.md): how the repo-search arm runs as trials.
