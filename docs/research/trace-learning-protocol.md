# How should later trace-learning evaluations avoid leakage?

This is a design for a later evaluation, not permission to run it or evidence of generalization.
It preserves KAN-249's simple baselines and KAN-31's cost-primary decision gate. No threshold or spending allowance is introduced.

## Separate evidence layers

Trace Compiler candidates describe observed activity. They are not verified outcomes or causal rewards.
Flightdeck's explicit-rule `step_labels` and process counts remain separate from trusted test events and independently reviewed labels.
Missing evidence requires exclusion or explicit abstention with a reason, never a fabricated zero.

The proposed Trace Compiler `trace-bench/v1` manifest is an experimental repository-local synthetic-conformance format, not a Flightdeck import contract.
It separates Development, Calibration and Test cases and pins protocol, label-guide and rulepack digests.
A future adapter needs a reviewed compatibility contract and counted-source design before runtime adoption.

## Freeze assignment before development

Use one private manifest containing immutable input digests and run, session, task, family, entity, repository, harness and version identifiers.
Record collection windows, duplicate groups, selection policy and exclusions. Keep sensitive contents outside the public repository.

Assign whole connected groups to one split. Group edges include shared runs, sessions, task identity, corrections, entities and exact or near-duplicate content.
Hold out complete workflow families rather than randomly splitting events from familiar templates. Declare repository, time-window and harness holdouts separately.

Freeze the manifest digest, label guide, scoring rules and allowed development feedback before trials.
Require independent review of the assignment. Reject cross-split group membership, missing identifiers, ambiguous provenance and post-freeze changes.
Do not silently drop inconvenient cases. Report repeated-example repair separately from unseen valid cases and near-miss invalid cases.

## Preserve simple comparators

| Arm | Available context | Purpose |
| --- | --- | --- |
| Unchanged incumbent | Original permitted context | Detect regressions against current behavior |
| Raw conversation history | Same permitted observations and correction history | Test whether compilation adds value beyond history |
| Explicit rules | Frozen rules derived only from development corrections | Test a transparent, inexpensive alternative |
| Candidate | The same permitted information through its declared mechanism | Test the proposed change |

Log prompts, context selection, tokens, cost, latency and configuration digests for every arm.
Keep model weights frozen for prompt, memory or controller comparisons. Parameter training requires a separate protocol and authorization.
Equalize access and approved budgets, not only nominal prompts. Never expose holdout answers through history, rule extraction or compiler tuning.

## Reject label-ranking shortcuts

For trace-label ranking, add a position/length control using last-assistant status, normalized turn position and length features.
Freeze its feature definitions before evaluation. Record whether features need finalized traces; retrospective accuracy does not establish online availability.

Also compare a simple structural classifier with the richer candidate using identical permitted features, splits, calibration and tuning budgets.
This matched-feature baseline separates model complexity from additional information. Neither control replaces raw history or explicit rules in the later harness comparison.

Report average precision and top-one localization on the same held-out sessions.
Pair comparisons by session and cluster uncertainty at the frozen independent assignment unit.
Freeze per-session versus pooled aggregation, zero-positive handling and top-one eligibility before scoring.
Choose any F1 threshold using calibration data only. Event-level F1 or pooled ranking scores alone cannot establish semantic learning.

Pre-register tests that vary position and length while preserving the labelled behavior, plus near-miss controls that preserve structure but change correctness.
Require held-out evidence beyond the strongest simple and matched-feature controls. Beating controls is necessary but insufficient evidence of semantic learning.
If paired gains remain inconclusive, retain that result rather than claiming improved understanding.

## Report and decide

Report valid-case success, invalid-case false acceptance, valid-case false rejection, abstention, cost and latency by family and split.
Include denominators, exclusions and uncertainty. Cluster inference by the assignment unit; multiple events from one task are not independent samples.
Retain negative and inconclusive results. Include memorized-identifier, template, blanket-refusal, abstain-all and reward-hacking controls.

Pre-register numerical criteria, sample size and budgets only after separate approval.
A generalization claim needs held-out evidence beyond repaired examples, both simple baselines and the applicable shortcut controls.
Leakage, missing controls or policy violations invalidate that claim.

KAN-25's twenty human-labelled failures remain separate human work. Synthetic fixtures cannot replace them.
Neither this protocol nor passing integrity tests authorizes paid evaluation, model training, private uploads, worker activation or changes to KAN-31's decision rule.
