# Synthetic evaluation contract fixtures

Every record is invented. Locators point to no stored artifacts; digest values are shape-only placeholders,
not hashes that authenticate any evidence. Model names identify no real service. These fixtures need no
network, credentials, provider, production runtime, or private run data.

| Fixture | Structural case |
| --- | --- |
| `complete-outcome-pass-process-fail.json` | Complete process-judge coverage; outcome success and process failure coexist. |
| `deterministic-valid-failure-zero.json` | A deterministic failed outcome has a real numeric zero; process coverage is not applicable. |
| `partial-process-abstain-outcome-pass.json` | Clipped evaluation input prevents full process judgment without erasing the outcome. |
| `unknown-denominator.json` | Partial source/input and an unknown eligible-step denominator stay explicit. |
| `explicit-deterministic-fallback.json` | Requested process judge falls back explicitly to a deterministic test with a reason. |
| `infrastructure-error-no-score.json` | Infrastructure error, unavailable provenance, no determinate results, and no fabricated score. |
| `missing-probabilities-no-score.json` | A learned-policy evaluator abstains when probabilities are unavailable; no reward is invented. |

Run the offline structural checks from the repository root:

```sh
python -m unittest discover -s tests -p test_evaluation_contract.py -v
```

The same `unittest.TestCase` tests are collectable by pytest. They exercise JSON Schema Draft 2020-12 directly;
there is no production semantic validator hidden in a fixture loader or test helper.

## Deliberate limits

Passing this schema is not proof of evidence authenticity, source membership, immutability, adequate coverage,
training eligibility, or promotion safety. Tests explicitly show that a well-shaped wrong digest, direct evaluator
identity mismatch, impossible count arithmetic, false complete coverage with an abstaining step and a retained
aggregate score, conflicting (non-identical) records sharing a step ID, foreign-run evidence, and an invalid external
ordinal value can remain structurally conformant. Exact duplicate step objects
are rejected, but unique step identity is a different property.

A later counted production validator must reject such semantic errors before ingestion or decision use, resolve
and verify evidence, derive denominators from the pinned selection policy, and safely parse finite JSON without
duplicate keys. These fixtures must never be treated as runtime safety guarantees or real evaluation results.
