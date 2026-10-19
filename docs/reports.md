# Reports

A decision about a harness change gets made where the change is reviewed: usually a GitHub pull request, such as
hangar's canary lock-bump PRs. Flightdeck's report is a markdown comment there, not a dashboard. Code:
`src/flightdeck/report/markdown.py`.

```sh
flightdeck report experiment <id> [options]
flightdeck report post report.md --to owner/repo#n [--full-url URL | --gist]
```

`report experiment` reads only the data plane (`--data`, default `~/.flightdeck/data`), so it renders with hangar
powered off. Its options:

- `--baseline control`, `--b treat`: the two arms (the verdict is always `--b` against `--baseline`).
- `--decision decision.yaml`: the pre-registered rule; without it the report says *No verdict*.
- `--out report.md`: write the report (markdown) and print the verdict; without it the report prints as a terminal
  readout. `--post owner/repo#n`: post it as one comment, updated in place
  (`GITHUB_TOKEN`), with `--full-url URL` or `--gist` for where the full text lives when a comment is clipped.
- `--details`: per-task rows and trial links (keep it off for public repositories); `--hangar URL`: the trial links.

<figure class="af-figure" markdown>
![The whole flightdeck report as a pull-request comment: the verdict as its headline, the experiment and the rule, then the Outcome, Process and Cost tables, the behavior-spec pass rates, the exclusions and drift, and the pins collapsed at the end](assets/report-comment-full-dark.png#only-dark){ width=816 height=1638 }
![The whole flightdeck report as a pull-request comment: the verdict as its headline, the experiment and the rule, then the Outcome, Process and Cost tables, the behavior-spec pass rates, the exclusions and drift, and the pins collapsed at the end](assets/report-comment-full-light.png#only-light){ width=816 height=1638 }
<figcaption>A whole report on a pull request (fixture experiment)</figcaption>
</figure>

## Anatomy

1. **The verdict is the headline**, in plain words from the pre-registered rule (below), with the numbers beside it:
   *treat is non-inferior to control on resolved: −2.0 pp (95% CI −4.0 to +1.0, margin −5.0)*, or *No decision:
   underpowered*. Without a valid `decision.yaml` the headline is **No verdict** and the numbers follow anyway.
2. **One line on the experiment**: the arms, how many tasks and trials, the seed, and which pins differ between the
   arms; then the rule as pre-registered (metric, direction, margin, minimum tasks).
3. **Outcome**, **Process** (tool calls, wall time) and **Cost** tables from `flightdeck stats compare`
   ([statistics.md](statistics.md)), each with only the columns that apply and every number with its unit
   (`10 of 32 (31%)`, `3.0 calls`, `174.9 s`, `$0.42`).
4. **Behavior specs**: pass rate per spec per variant, from `spec_results` (written by `flightdeck check run`,
   [behavior-specs.md](behavior-specs.md)) over the trials the Outcome table counts; `not_applicable` and `unknown`
   results are left out, and a spec with none of either has no row.
5. **Exclusions and drift**: what every table left out and why, once; the drifted trials.
6. **Pins**, collapsed: the rows that differ between the arms (harness and version, model, environment,
   `config_digest`, `harness_digest`, `environment_digest`, the grader command, hangar's version), the ones that
   are the same in one line, and the number of base SHAs. A missing pin says *not recorded*; a digest is never cut.
7. With `--details`: the **per-task table** (discordant tasks first, base SHA, resolved per arm) inside a collapsed
   `<details>`, drift messages per trial, and with `--hangar` links to each trial's trace on hangar REST.

## Pre-registration

`decision.yaml`, written before the experiment runs (flat `key: value` lines):

```yaml
metric: resolved      # resolved | cost_usd | tool_calls | wall_s
direction: higher     # higher or lower is better
margin: -0.05         # non-inferiority margin, in the metric's units (a proportion for resolved)
min_tasks: 10         # fewer paired tasks: no decision
```

A worked example is `flightdeck/decision.yaml` in the [team-harness repo](https://github.com/Sean-Koval/team-harness/tree/main/flightdeck) (resolved, higher, margin
−0.05, at least 10 tasks), next to `flightdeck/suite.yaml` and its specs; add a task before its `--dry-run` works (`flightdeck task new
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
