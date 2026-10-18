# Reports

A decision about a harness change gets made where the change is reviewed: usually a GitHub pull request, such as
hangar's canary lock-bump PRs. Flightdeck's report is a markdown comment there, not a dashboard. Code:
`src/flightdeck/report/markdown.py`.

```sh
flightdeck report experiment <id> [--baseline control] [--b treat] [--decision decision.yaml] [--details]
                                  [--hangar URL] [--out report.md] [--post owner/repo#n] [--full-url URL | --gist]
flightdeck report post report.md --to owner/repo#n [--full-url URL | --gist]
```

The report reads only the data plane (`--data`, default `~/.flightdeck/data`), so it renders with hangar powered off.

## Anatomy

1. **Verdict**, in plain words, from the pre-registered rule (below): *treat is non-inferior to control on resolved
   (−2.0 pp, CI −4.0…+1.0, margin −5.0)*, or *No decision: underpowered*. Without a valid `decision.yaml` the report
   says **No verdict** and shows the numbers only.
2. **Pins** per variant: harness and version, model, environment, `config_digest`, `harness_digest`,
   `environment_digest`, the grader command, and hangar's version from the manifests; the number of base SHAs.
3. **Outcome**, **Process** (tool calls, wall time) and **Cost** tables from `flightdeck stats compare`
   ([statistics.md](statistics.md)), each with its exclusions, seed and n.
4. **Behavior specs**: pass rate per spec per variant, from `spec_results` (written by `flightdeck check run`,
   [behavior-specs.md](behavior-specs.md)) over the trials the Outcome table counts; `not_applicable` and `unknown`
   results are left out, and a spec with none of either has no row.
5. **Exclusions and drift**: the drifted trials.
6. With `--details`: the **per-task table** (discordant tasks first, base SHA, resolved per arm) inside a collapsed
   `<details>`, drift messages per trial, and with `--hangar` links to each trial's trace on hangar REST.

## Pre-registration

`decision.yaml`, written before the experiment runs (flat `key: value` lines):

```yaml
metric: resolved      # resolved | cost_usd | tool_calls | wall_s
direction: higher     # higher or lower is better
margin: -0.05         # non-inferiority margin, in the metric's units (a proportion for resolved)
min_tasks: 10         # fewer paired tasks: no decision
```

A worked example is agent-factory's
[`examples/team-harness/flightdeck/decision.yaml`](https://github.com/Sean-Koval/agent-factory/tree/main/examples/team-harness/flightdeck) (resolved, higher, margin −0.05, at least
10 tasks), next to its suite and specs; add a task before its `--dry-run` works (`flightdeck task new
flightdeck/tasks/<id>`). Choose the margin with the [power table](statistics.md#what-flightdeck-can-tell-you) in
mind: with 50 tasks × 3 trials and no real change, a −0.05 margin gives a verdict only about one time in five.

The report prints a verdict only when the file is committed as it is and the last commit that changed it is older
than the first finished trial: the git commit time, not the file's modification time, which any copy or checkout
resets. An uncommitted or locally edited `decision.yaml` gives **No verdict**. The rule:
fewer than `min_tasks` paired tasks (or an underpowered interval) is *No decision: underpowered*; an interval wholly
above zero is *better*; wholly above the margin is *non-inferior*; wholly below it is *worse*; anything else is *No
decision*.

## Posting

`--post owner/repo#n` (on `report experiment`) or `report post --to` creates one comment on that PR or issue, or
updates it in place: the comment starts with a hidden marker, `<!-- flightdeck:report:<experiment> -->`. The token
comes from `GITHUB_TOKEN`: a fine-grained token with `issues:write` / `pull_requests:write` on the target repo, kept in
the operator's environment. Posting is flightdeck's only GitHub write.

Before posting, the text is re-scanned with the data plane's secret patterns; a match refuses the post. Comments are
clipped to GitHub's 65,536-character limit with a link to the full report: `--full-url` (an `https://` URL, such as
the report committed to the private data repository) or `--gist` (a secret gist of it, created with the same token,
which then needs the `gist` scope). Without either the comment says the full report is not linked; it never points at
a local path.

Reports on public repositories must not quote private team code: the default report has counts and intervals only;
per-task rows and trial links need `--details`.
