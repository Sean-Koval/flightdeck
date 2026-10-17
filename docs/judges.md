# Judges

Some outcomes need a judge: the quality of a handoff (ai-dlc's `quality` dimension, human-only until now), whether a
cited span supports a claim ([knowledge evals](knowledge-evals.md)), steer avoidance (#29), episode labels such as
stuck loops or test gaming. Model judges drift and disagree by model, so the rule is: people label 100-200 items per
rubric version, a judge is used only where it agrees with them (Cohen's κ, lower bound ≥ 0.6, the floor hangar 0007
§5.5 set), and estimates combine judge and human labels by prediction-powered inference. **A raw judge average never
gates anything.** Code: `src/flightdeck/judges/`, `src/flightdeck/stats/ppi.py`.

## A rubric version

```yaml
id: handoff-quality
version: 1
question: Is the handoff note complete?
scale: binary              # or ordinal, with levels: [0, 1, 2, 3]
criteria: [names what changed, names what is left, links the evidence]
examples: []               # labelled examples the prompt shows
judge: {model: claude-opus-5-5, prompt: "..."}   # a concrete model id: no alias, no policy
```

Its digest covers all of it. Changing the text, the examples, the prompt or the judge model is a new version: the
rubric's status turns `stale` and it must be calibrated again.

## The lifecycle

1. **Label.** `flightdeck judge label <rubric> --data <plane> --sample 150 --stratify-by variant,task_id --raters 2
   --overlap 30 > sheet.csv` samples runs in proportion to each stratum (seeded) and writes a sheet: the first 30
   items for both raters, the rest shared out. Variant names stay off the sheet, so raters judge blind; when a rubric
   compares two outputs side by side, randomize their order too.
2. **Judge.** Flightdeck holds no model credentials ([ADR-0001](decisions/0001-boundary-with-hangar.md)), so the judge
   runs elsewhere, on an API key with a spend cap: a hangar job, or an operator's script. It writes one line per run:
   `{"run_id", "label", "rationale"}`. Judge calls on tainted runs are allowed but labelled by the run's own flag.
3. **Calibrate.** `flightdeck judge calibrate <rubric> sheet.csv judge.jsonl` compares the judge with the primary human
   label per run (the first rater by name): Cohen's κ for binary scales, quadratically weighted κ for ordinal ones,
   with a 95% bootstrap interval over runs, plus the raters' own κ on the overlap and a calibration curve (for each
   judge label, how many runs and the human mean). It writes `<rubric>.calibration.json`:
   - `usable`: the interval's lower bound is at least 0.6;
   - `provisional`: the point estimate is at least 0.6 but the interval isn't;
   - `unusable`: below that.
4. **Score.** `flightdeck judge score <rubric> judge.jsonl --data <plane>` stores the labels in `judge_labels`
   (`rubric@version`, its digest, the judge model, the label, the rubric's status at the time). The rationale's text is
   not stored, only its digest: keep the text in the private bucket, since it quotes team code.
5. **Estimate.** `flightdeck judge estimate <rubric> sheet.csv --data <plane>` prints the
   [PPI](statistics.md#ppi) estimate of the rubric's mean with its interval, and the raw judge mean only beside it,
   marked as not an estimate.

A `decision.yaml` may name a rubric (`rubric: handoff.yaml`, relative to the decision file); `report experiment`
refuses to render a verdict unless that rubric is `usable`. Label drift is visible because every stored label
carries its rubric version and judge.
