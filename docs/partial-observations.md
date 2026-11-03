# Judge an incomplete export

Opt into `conservative-v1` when missing events should not become definite violations. Existing specs keep their legacy behavior.

```yaml
schema: flightdeck.spec/v1
id: no-observed-delete
harness: "*"
observation_policy: conservative-v1
scope: job
assert:
  never:
    tool: {ops: [delete]}
```

The policy changes only units marked truncated. Complete units retain existing results. Missing truncation metadata does not prove completeness.

## Results

A truncated applicable unit never passes. A missing eventual event, missing prerequisite or incomplete order produces `unknown`.

A definite failure requires an observed forbidden tool kind or operation. This includes `never` and `count` with `min: 0, max: 0`.
The matcher must contain only `tool`, with a concrete `kind`, a nonempty `ops` list, or both.

Other matcher shapes remain `unknown`, including event, path, text and attribute predicates. Positive count limits remain unknown because replayed observations can inflate counts.

| Observation | Constraint | Conservative result |
| --- | --- | --- |
| Only an edit is visible | Eventually run a shell tool | Unknown |
| Edit is visible | Never edit | Fail |
| No edit is visible | Never edit | Unknown |
| Same edit appears twice | At most one edit | Unknown |
| Edit precedes a plan | Plan before edit | Unknown |

## Evidence limits

Observed run and span identities must be explicit and consistent. Exact duplicate rows are allowed for existence checks; conflicting rows block definite partial verdicts.

Run-to-span and trace attribution must agree. All constituent runs must agree on requested applicability fields and harness, with explicit values.
Missing or ambiguous applicability produces unknown, not non-applicability. A known mismatching applicability filter remains `not_applicable`.

These guards are deliberately conservative across the supplied export. An unrelated identity conflict can make otherwise usable partial results unknown.

Failure witnesses remain valid when added records preserve established identity, attribution and applicability metadata. Conflicting additions or revisions require reevaluation.
The policy does not authenticate records, establish capture completeness or certify unseen data. Truncation is not assumed to mean a clean prefix.

Inputs must satisfy the existing flattened data contract, including valid JSON attribute strings. Malformed attributes can still be rejected by SQL evaluation.

## Versioning and history

Omitting `observation_policy`, or setting `legacy-v1`, preserves existing semantics. Unknown versions and non-string values are rejected, including explicit null.
YAML documents inherit the first document's policy unless they override it.

Stored `spec_results` include `observation_policy`. Historical rows with no value mean legacy. Alert histories stay separate by policy; nonlegacy issue titles include it.
Changing a check's policy is an edit that requires review. The policy is opt-in; no existing spec or nightly configuration is enabled automatically.
