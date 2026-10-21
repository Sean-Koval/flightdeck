"""Offline structural conformance only, not an ingestion or semantic validator."""

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/evaluation/evaluation.schema.json"
FIXTURES = ROOT / "tests/fixtures/evaluation"
COMPLETE = "complete-outcome-pass-process-fail"
ZERO = "deterministic-valid-failure-zero"
PARTIAL = "partial-process-abstain-outcome-pass"
UNKNOWN = "unknown-denominator"
FALLBACK = "explicit-deterministic-fallback"
ERROR = "infrastructure-error-no-score"
MISSING_PROBABILITIES = "missing-probabilities-no-score"


def fixture(name: str = COMPLETE) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def changed(record: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    """Mutate one field in a fresh test document; perform no semantic validation."""
    result = copy.deepcopy(record)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return result


class EvaluationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCHEMA_PATH.is_file(), f"Missing proposed evaluation schema: {SCHEMA_PATH}")
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def assertConformant(self, record: dict[str, Any]) -> None:
        errors = [f"{list(error.absolute_path)}: {error.message}" for error in self.validator.iter_errors(record)]
        self.assertEqual(errors, [], "\n".join(errors))

    def assertRejected(self, record: dict[str, Any]) -> None:
        self.assertTrue(list(self.validator.iter_errors(record)), "Mutation unexpectedly conforms")

    def test_schema_is_valid_draft_2020_12(self) -> None:
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        Draft202012Validator.check_schema(self.schema)

    def test_synthetic_fixtures_conform(self) -> None:
        paths = sorted(FIXTURES.glob("*.json"))
        self.assertEqual({path.stem for path in paths},
                         {COMPLETE, ZERO, PARTIAL, UNKNOWN, FALLBACK, ERROR, MISSING_PROBABILITIES})
        for path in paths:
            with self.subTest(fixture=path.name):
                self.assertConformant(fixture(path.stem))

    def test_outcome_and_process_are_independent(self) -> None:
        for name, process in ((COMPLETE, "fail"), (PARTIAL, "abstain")):
            with self.subTest(fixture=name):
                record = fixture(name)
                self.assertEqual(record["assessments"]["outcome"]["status"], "pass")
                self.assertEqual(record["assessments"]["process"]["status"], process)
                self.assertConformant(record)

    def test_real_zero_is_not_missing_or_error(self) -> None:
        record = fixture(ZERO)
        self.assertEqual(record["assessments"]["outcome"]["status"], "fail")
        self.assertEqual(record["assessments"]["outcome"]["score"]["value"], 0)
        self.assertEqual(record["coverage"]["eligible_steps"], 0)
        self.assertConformant(record)

    def test_model_and_deterministic_families_share_the_envelope(self) -> None:
        kinds = {fixture(name)["actual_evaluator"]["kind"] for name in (COMPLETE, ZERO, MISSING_PROBABILITIES)}
        self.assertEqual(kinds, {"process_judge", "deterministic_test", "learned_policy"})
        for kind in ("trace_predicate", "outcome_grader", "future_method"):
            record = fixture(ZERO)
            for field in ("requested_evaluator", "actual_evaluator"):
                record[field]["kind"] = kind
            with self.subTest(kind=kind):
                self.assertConformant(record)

    def test_required_top_level_fields_cannot_be_missing(self) -> None:
        for key in fixture():
            if key == "extensions":
                continue
            record = fixture()
            del record[key]
            with self.subTest(field=key):
                self.assertRejected(record)

    def test_required_nested_pins_cannot_be_missing(self) -> None:
        paths = {
            "subject": ("run_id", "source", "scope", "attempt"),
            "input": ("artifact", "format", "completeness"),
            "requested_evaluator": ("id", "version", "kind", "implementation_digest", "config_digest"),
            "actual_evaluator": ("id", "version", "kind", "implementation_digest", "config_digest"),
            "specification": ("id", "version", "digest", "digest_method"),
            "coverage": ("scope", "selection_digest", "eligible_steps", "attempted_steps",
                         "determinate_steps", "status"),
            "execution": ("status",),
            "assessments": ("outcome", "process"),
        }
        for parent, keys in paths.items():
            for key in keys:
                record = fixture()
                del record[parent][key]
                with self.subTest(parent=parent, field=key):
                    self.assertRejected(record)
        for key in ("source", "input", "redaction"):
            record = fixture()
            del record["input"]["completeness"][key]
            with self.subTest(completeness=key):
                self.assertRejected(record)

    def test_schema_revision_and_known_states_are_strict(self) -> None:
        mutations = [
            (("schema",), "flightdeck.evaluation/v2"), (("schema_revision",), 2),
            (("schema_revision",), "1"), (("execution", "status"), "direct"),
            (("coverage", "status"), "full"), (("coverage", "scope"), "all"),
            (("subject", "source"), "remote"), (("subject", "scope"), "experiment"),
            (("assessments", "outcome", "status"), "success"),
            (("input", "completeness", "input"), "clipped"),
            (("specification", "digest_method"), "selected_fields_sha256"),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.assertRejected(changed(fixture(), path, value))

    def test_digest_shape_and_opaque_locators_are_required(self) -> None:
        paths = [
            ("input", "artifact", "digest"), ("requested_evaluator", "implementation_digest"),
            ("requested_evaluator", "config_digest"), ("actual_evaluator", "implementation_digest"),
            ("actual_evaluator", "config_digest"), ("specification", "digest"),
            ("coverage", "selection_digest"), ("calibration", "digest"),
            ("assessments", "outcome", "evidence", 0, "digest"),
        ]
        for path in paths:
            for value in ("sha256:abc", "sha256:" + "A" * 64, "sha1:" + "a" * 64):
                with self.subTest(path=path, digest=value):
                    self.assertRejected(changed(fixture(), path, value))
        for locator in ("https://example.invalid/evidence", "file:///tmp/evidence", "artifact:", "artifact:bad name"):
            with self.subTest(locator=locator):
                self.assertRejected(changed(fixture(), ("assessments", "outcome", "evidence", 0, "locator"), locator))
        for key in ("locator", "digest"):
            record = fixture()
            del record["assessments"]["outcome"]["evidence"][0][key]
            self.assertRejected(record)

    def test_pinned_strings_and_extension_keys_reject_trailing_newlines(self) -> None:
        record = fixture()
        paths = [("evaluation_id",), ("input", "artifact", "digest"), ("input", "artifact", "locator")]
        for path in paths:
            value: Any = record
            for key in path:
                value = value[key]
            with self.subTest(path=path):
                self.assertRejected(changed(record, path, value + "\n"))
        self.assertRejected(changed(record, ("extensions",), {"vendor.field\n": 1}))

    def test_selectors_are_optional_nonempty_and_closed(self) -> None:
        path = ("assessments", "outcome", "evidence", 0, "selector")
        for selector in ({"trace_id": "trace-1"}, {"span_id": "span-1", "step_id": "step-1"}):
            self.assertConformant(changed(fixture(), path, selector))
        for selector in ({}, {"trace_id": ""}, {"span_id": None}, {"unknown": "value"}):
            with self.subTest(selector=selector):
                self.assertRejected(changed(fixture(), path, selector))

    def test_identifiers_and_nonempty_strings_reject_malformed_values(self) -> None:
        token_paths = [("evaluation_id",), ("requested_evaluator", "id"), ("actual_evaluator", "version"),
                       ("actual_evaluator", "kind"), ("steps", 0, "step_id"),
                       ("assessments", "outcome", "score", "metric", "id")]
        for path in token_paths:
            for value in ("", "contains spaces"):
                with self.subTest(path=path, value=value):
                    self.assertRejected(changed(fixture(), path, value))
        for path in (("input", "format"), ("actual_evaluator", "model_id"),
                     ("assessments", "outcome", "score", "metric", "unit")):
            self.assertRejected(changed(fixture(), path, ""))
        self.assertRejected(changed(fixture(FALLBACK), ("execution", "reason"), "contains spaces"))

    def test_modeled_kinds_require_model_identity_for_both_descriptors(self) -> None:
        for kind in ("process_judge", "learned_policy"):
            for field in ("requested_evaluator", "actual_evaluator"):
                record = fixture()
                record[field]["kind"] = kind
                del record[field]["model_id"]
                with self.subTest(kind=kind, descriptor=field):
                    self.assertRejected(record)

    def test_all_assessment_states_require_status_and_evidence_array(self) -> None:
        for status in ("pass", "fail", "scored", "abstain", "error", "not_applicable"):
            for missing in ("status", "evidence"):
                record = fixture()
                assessment = record["assessments"]["outcome"]
                assessment["status"] = status
                if status in ("abstain", "error", "not_applicable"):
                    assessment.pop("score")
                    assessment["reason"] = "synthetic_reason"
                elif status == "fail":
                    assessment["score"]["value"] = 0
                assessment.pop(missing)
                with self.subTest(status=status, missing=missing):
                    self.assertRejected(record)

    def test_determinate_assessments_require_nonempty_evidence_everywhere(self) -> None:
        for path in (("assessments", "outcome"), ("assessments", "process"), ("steps", 0, "assessment")):
            for status in ("pass", "fail", "scored"):
                assessment = copy.deepcopy(fixture()["assessments"]["outcome"])
                assessment["status"] = status
                assessment["evidence"] = []
                assessment["score"]["value"] = 0 if status == "fail" else 1
                with self.subTest(path=path, status=status):
                    self.assertRejected(changed(fixture(), path, assessment))

    def test_nondeterminate_assessments_require_reason_and_forbid_any_score(self) -> None:
        for path in (("assessments", "outcome"), ("assessments", "process"), ("steps", 0, "assessment")):
            for status in ("abstain", "error", "not_applicable"):
                assessment = {"status": status, "reason": "unavailable", "evidence": []}
                with self.subTest(path=path, status=status):
                    self.assertConformant(changed(fixture(), path, assessment))
                    self.assertRejected(changed(fixture(), path, {"status": status, "evidence": []}))
                    assessment["score"] = copy.deepcopy(fixture()["assessments"]["outcome"]["score"])
                    self.assertRejected(changed(fixture(), path, assessment))
                    assessment["score"] = None
                    self.assertRejected(changed(fixture(), path, assessment))

    def test_scored_status_requires_score_but_pass_and_fail_do_not(self) -> None:
        for status in ("pass", "fail", "scored"):
            record = fixture()
            record["assessments"]["outcome"]["status"] = status
            del record["assessments"]["outcome"]["score"]
            if status == "scored":
                self.assertRejected(record)
            else:
                record["assessments"]["outcome"]["reason"] = "observed_result"
                self.assertConformant(record)

    def test_binary_score_values_match_pass_and_fail(self) -> None:
        for status in ("pass", "fail", "scored"):
            for value in (-1, 0, 0.5, 1, 2, "0", False):
                record = fixture()
                record["assessments"]["outcome"]["status"] = status
                record["assessments"]["outcome"]["score"]["value"] = value
                allowed = type(value) is int and value in (0, 1) and (
                    status == "scored" or value == (1 if status == "pass" else 0)
                )
                with self.subTest(status=status, value=value):
                    if allowed:
                        self.assertConformant(record)
                    else:
                        self.assertRejected(record)

    def test_scores_preserve_explicit_nonbinary_scale_unit_and_direction(self) -> None:
        for scale, value, direction in (("ordinal", 3, "none"), ("continuous", -0.25, "lower")):
            record = fixture()
            assessment = record["assessments"]["outcome"]
            assessment["status"] = "scored"
            assessment["score"] = {"value": value, "metric": {"id": "synthetic.metric", "scale": scale,
                                                             "unit": "points", "direction": direction}}
            self.assertConformant(record)
        for key in ("value", "metric"):
            record = fixture()
            del record["assessments"]["outcome"]["score"][key]
            self.assertRejected(record)
        for key in ("id", "scale", "unit", "direction"):
            record = fixture()
            del record["assessments"]["outcome"]["score"]["metric"][key]
            self.assertRejected(record)
        for key, value in (("scale", "probability"), ("direction", "maximize")):
            self.assertRejected(changed(fixture(), ("assessments", "outcome", "score", "metric", key), value))

    def test_execution_states_require_reasons_and_actual_evaluator(self) -> None:
        for name in (FALLBACK, ERROR):
            record = fixture(name)
            del record["execution"]["reason"]
            with self.subTest(fixture=name):
                self.assertRejected(record)
        self.assertRejected(changed(fixture(), ("execution", "reason"), "not_needed"))
        for name in (COMPLETE, FALLBACK):
            self.assertRejected(changed(fixture(name), ("actual_evaluator",), None))

    def test_error_execution_forbids_determinate_results_and_counts(self) -> None:
        record = fixture(MISSING_PROBABILITIES)
        record["execution"] = {"status": "error", "reason": "infrastructure_failure"}
        record["coverage"]["status"] = "complete"
        self.assertConformant(record)
        self.assertRejected(changed(record, ("coverage", "determinate_steps"), 1))
        for path in (("assessments", "outcome"), ("assessments", "process"), ("steps", 0, "assessment")):
            for status in ("pass", "fail", "scored"):
                assessment = copy.deepcopy(fixture()["assessments"]["outcome"])
                assessment["status"] = status
                assessment["score"]["value"] = 0 if status == "fail" else 1
                with self.subTest(path=path, status=status):
                    self.assertRejected(changed(record, path, assessment))

    def test_missing_provenance_cannot_support_determinate_results(self) -> None:
        for field in ("input", "actual_evaluator", "specification"):
            record = fixture(MISSING_PROBABILITIES)
            record[field] = None
            if field == "actual_evaluator":
                record["execution"] = {"status": "error", "reason": "evaluator_unavailable"}
            self.assertConformant(record)
            for path in (("assessments", "outcome"), ("assessments", "process"), ("steps", 0, "assessment")):
                for status in ("pass", "fail", "scored"):
                    assessment = copy.deepcopy(fixture()["assessments"]["outcome"])
                    assessment["status"] = status
                    assessment["score"]["value"] = 0 if status == "fail" else 1
                    if path == ("assessments", "process") and status == "fail":
                        del assessment["score"]
                    with self.subTest(field=field, path=path, status=status):
                        self.assertRejected(changed(record, path, assessment))

    def test_complete_coverage_rejects_clipped_redacted_or_unknown_input(self) -> None:
        for field, values in (("source", ("partial", "unknown")), ("input", ("partial", "unknown")),
                              ("redaction", ("present", "unknown"))):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertRejected(changed(fixture(), ("input", "completeness", field), value))
        self.assertRejected(changed(fixture(), ("input",), None))

    def test_selection_scope_can_be_complete_without_complete_source(self) -> None:
        record = fixture()
        record["coverage"]["scope"] = "selection"
        for source in ("partial", "unknown"):
            record["input"]["completeness"]["source"] = source
            self.assertConformant(record)
        self.assertRejected(changed(record, ("input", "completeness", "input"), "partial"))

    def test_partial_or_unknown_process_cannot_claim_pass_or_a_score(self) -> None:
        for name in (PARTIAL, UNKNOWN):
            for status in ("pass", "scored"):
                assessment = copy.deepcopy(fixture()["assessments"]["outcome"])
                assessment["status"] = status
                with self.subTest(fixture=name, status=status):
                    self.assertRejected(changed(fixture(name), ("assessments", "process"), assessment))
                    if status == "pass":
                        del assessment["score"]
                        self.assertRejected(changed(fixture(name), ("assessments", "process"), assessment))
            assessment = copy.deepcopy(fixture()["assessments"]["process"])
            self.assertRejected(changed(fixture(name), ("assessments", "process"), assessment))
            del assessment["score"]
            self.assertConformant(changed(fixture(name), ("assessments", "process"), assessment))

    def test_coverage_denominators_distinguish_zero_partial_and_unknown(self) -> None:
        for name in (COMPLETE, PARTIAL):
            for value in (0, None):
                self.assertRejected(changed(fixture(name), ("coverage", "eligible_steps"), value))
        for value in (0, 1):
            self.assertRejected(changed(fixture(UNKNOWN), ("coverage", "eligible_steps"), value))
        for key in ("eligible_steps", "attempted_steps", "determinate_steps"):
            self.assertRejected(changed(fixture(ZERO), ("coverage", key), 1))
        self.assertRejected(changed(fixture(ZERO), ("steps",), fixture()["steps"]))
        self.assertRejected(changed(fixture(ZERO), ("assessments", "process"),
                                    {"status": "abstain", "reason": "no_steps", "evidence": []}))

    def test_counts_and_attempts_reject_negative_fractional_or_wrong_types(self) -> None:
        for key in ("eligible_steps", "attempted_steps", "determinate_steps"):
            for value in (-1, 1.5, "2", True):
                with self.subTest(field=key, value=value):
                    self.assertRejected(changed(fixture(), ("coverage", key), value))
        for key in ("attempted_steps", "determinate_steps"):
            self.assertRejected(changed(fixture(), ("coverage", key), None))
        for value in (0, -1, 1.5, "1", True):
            self.assertRejected(changed(fixture(), ("subject", "attempt"), value))

    def test_exact_duplicate_steps_are_rejected(self) -> None:
        record = fixture()
        record["steps"] = [record["steps"][0], copy.deepcopy(record["steps"][0])]
        self.assertRejected(record)
        for key in ("step_id", "assessment"):
            record = fixture()
            del record["steps"][0][key]
            self.assertRejected(record)

    def test_core_objects_reject_extra_fields_including_reward(self) -> None:
        paths = [(), ("subject",), ("input",), ("input", "artifact"), ("input", "completeness"),
                 ("requested_evaluator",), ("actual_evaluator",), ("specification",), ("execution",),
                 ("coverage",), ("assessments",), ("assessments", "outcome"),
                 ("assessments", "outcome", "score"), ("assessments", "outcome", "score", "metric"),
                 ("steps", 0), ("calibration",)]
        for path in paths:
            with self.subTest(path=path):
                self.assertRejected(changed(fixture(), (*path, "reward"), 1))

    def test_only_namespaced_extensions_accept_arbitrary_json(self) -> None:
        record = fixture()
        del record["extensions"]
        self.assertConformant(record)
        self.assertConformant(changed(record, ("extensions",), {}))
        self.assertConformant(changed(record, ("extensions",),
                                      {"vendor.field": {"nested": [None, True, 1, "text"]}, "vendor.flag": False}))
        for key in ("reward", "", ".field", "vendor."):
            with self.subTest(key=key):
                self.assertRejected(changed(record, ("extensions",), {key: 1}))

    def test_well_shaped_wrong_digest_remains_a_deferred_semantic_check(self) -> None:
        record = changed(fixture(), ("input", "artifact", "digest"), "sha256:" + "0" * 64)
        self.assertConformant(record)

    def test_direct_identity_substitution_remains_a_deferred_semantic_check(self) -> None:
        record = fixture()
        record["actual_evaluator"]["id"] = "synthetic.unrequested_evaluator"
        record["actual_evaluator"]["config_digest"] = "sha256:" + "0" * 64
        self.assertConformant(record)

    def test_arithmetic_mismatch_remains_a_deferred_semantic_check(self) -> None:
        record = fixture()
        record["coverage"].update(eligible_steps=1, attempted_steps=2, determinate_steps=3)
        self.assertConformant(record)

    def test_false_complete_coverage_remains_a_deferred_semantic_check(self) -> None:
        record = fixture()
        record["coverage"]["determinate_steps"] = 1
        record["steps"][1]["assessment"] = {"status": "abstain", "reason": "missing_context", "evidence": []}
        # Complete claims 2 eligible and 2 attempted, but only 1 determinate step; the aggregate score remains.
        # A later production validator must reject it, even though the structural schema permits it.
        self.assertConformant(record)

    def test_conflicting_step_ids_remain_a_deferred_semantic_check(self) -> None:
        record = fixture()
        record["steps"][1]["step_id"] = record["steps"][0]["step_id"]
        self.assertConformant(record)

    def test_foreign_evidence_and_external_scale_semantics_remain_deferred(self) -> None:
        record = fixture()
        record["assessments"]["outcome"]["evidence"][0]["locator"] = "artifact:synthetic/other-run/evidence.json"
        record["assessments"]["outcome"]["status"] = "scored"
        record["assessments"]["outcome"]["score"]["metric"]["scale"] = "ordinal"
        record["assessments"]["outcome"]["score"]["value"] = 999
        self.assertConformant(record)


if __name__ == "__main__":
    unittest.main()
