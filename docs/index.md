---
hide:
  - navigation
  - toc
---

<div class="af-hero af-hero--visual" markdown>
<div markdown>
<span class="af-eyebrow">Agent factory · Judge plane</span>

# Did that harness change actually help?

<p class="af-lede">Flightdeck answers that from the runs hangar already records: paired statistics, behavior specs and a <a href="#the-verdict">verdict</a> posted on the pull request where the change is reviewed.</p>

[Get started](getting-started.md){ .md-button .md-button--primary } [Suite overview](https://sean-koval.github.io/agent-factory/){ .md-button }
</div>
<figure class="af-hero__visual">
<img src="assets/demo.svg" alt="A terminal session on the fixture experiment: flightdeck ingests the export, compares the variants paired by task and writes a report, printing its verdict, candidate is better than control on resolved: +21.2 pp (95% CI +1.5 to +43.9, margin −5.0). It opens on the finished session and then replays the typing." width="660" height="537">
<figcaption>ingest, stats compare, report on the fixture experiment, recorded by docs/assets/build.py</figcaption>
</figure>
</div>

<div id="the-verdict" markdown>
!!! verdict "The verdict"
    One of five words: *better*, *non-inferior*, *worse*, *No decision* or *No verdict*. It says how the candidate
    arm did against the control arm on one metric, with the paired difference and its 95% interval beside it:
    *candidate is better than control on resolved: +21.2 pp (95% CI +1.5 to +43.9, margin −5.0)*. The rule that picks the word
    (`decision.yaml`: metric, direction, margin, minimum tasks) is committed before the first trial, so nobody moves
    the goalposts. [Concepts](concepts.md) has the words; [Reports](reports.md#pre-registration) has the rule.
</div>

- **Is:** the judge. It reads what hangar recorded and says whether a change helped.
- **Isn't:** a runner, a dashboard, a leaderboard or a credential holder.
- **Sees:** changes of about 15 points at 500 trials a month; smaller ones through cost, tool calls and behavior
  specs ([what flightdeck can tell you](statistics.md#what-flightdeck-can-tell-you)).

## See it work

The verdict, posted as one pull-request comment that is updated in place. This one comes from the synthetic fixture
experiment (12 tasks × 2 variants × 3 trials):

<figure class="af-figure" markdown>
![The top of the flightdeck report as a pull-request comment: the headline is the verdict, candidate is better than control on resolved, +21.2 pp (95% CI +1.5 to +43.9, margin −5.0); under it the experiment, what differs between the arms, the pre-registered rule, and the Outcome table with 10 of 32 and 16 of 31 resolved, Wilson intervals and dollars per resolved task](assets/report-comment-dark.png#only-dark){ width=816 height=656 }
![The top of the flightdeck report as a pull-request comment: the headline is the verdict, candidate is better than control on resolved, +21.2 pp (95% CI +1.5 to +43.9, margin −5.0); under it the experiment, what differs between the arms, the pre-registered rule, and the Outcome table with 10 of 32 and 16 of 31 resolved, Wilson intervals and dollars per resolved task](assets/report-comment-light.png#only-light){ width=816 height=656 }
<figcaption>The top of the report on the pull request, from the fixture experiment</figcaption>
</figure>

The recording above is the run that produced it: `ingest → stats compare → report`. [Getting started](getting-started.md)
has the six commands and what each printed.

## Where it sits

<div class="af-figure" markdown>
--8<-- "docs/assets/suite.svg"
</div>

Flightdeck holds no sandbox code and no credentials ([ADR-0001](decisions/0001-boundary-with-hangar.md)). It reads
hangar's versioned interfaces and asks hangar to run the trials it plans.

## Three things people use it for

- **Bump the CLI lock with evidence.** Run the regression suite on the old lock and the new one; the canary PR gets one
  comment with the pre-registered verdict and the cost per resolved task of each.
- **Decide whether a workflow plugin pays for itself.** A/B the plugin on and off across 30 tasks. Pairing by task
  means far fewer runs than an unpaired comparison, and the rule was committed before the first trial.
- **Catch a behavior regression nobody tested for.** Write "never push to main" as a behavior spec. Nightly,
  `check run` scores every turn and opens an issue when the violation rate jumps, naming the harness digest that changed.

## Where to go next

- [Getting started](getting-started.md): six commands on the fixture, what they showed, then a real hangar.
- [Concepts](concepts.md): the vocabulary, and what is shipped.
- [Reports](reports.md): the pre-registered rule and the report's anatomy.
