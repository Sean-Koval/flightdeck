"""The knowledge gold set (#21, docs/knowledge-evals.md): sealing, citation validity, correctness, the 15-point rule."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.stats.core import cohen_kappa
from flightdeck.tasks import custody, knowledge

run = CliRunner().invoke
SRC = [{"uri": "repo://app/docs/adr/0007.md@abc", "sha256": "a" * 64}]


def _w(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _suite(tmp: Path, n: int = 20) -> Path:
    s = tmp / "knowledge-gold-v1"
    _w(s / "questions.jsonl", [{"id": f"q{i}", "question": f"Why {i}?", "kind": "decision-why", "as_of": "2026-10-01",
                                "scope": ["app"]} for i in range(n)])
    _w(s / "keys.jsonl", [{"id": f"q{i}", "answer_key": "because", "required_facts": ["x"], "valid_sources": SRC}
                          for i in range(n)])
    return s


def _arm(s: Path, arm: str, correct: list[bool], cite: dict | None = None, raters: tuple = ("r1", "r2")) -> None:
    _w(s / "answers" / f"{arm}.jsonl", [{"id": f"q{i}", "answer": "a", "citations": [cite or SRC[0]]}
                                        for i in range(len(correct))])
    _w(s / "labels" / f"{arm}.jsonl", [{"id": f"q{i}", "rater": r, "correct": c} for i, c in enumerate(correct)
                                       for r in raters])


def test_citation_validity_catches_fabricated_stale_and_unsupported() -> None:
    key = {"valid_sources": SRC}
    assert knowledge.citation(SRC[0], key, set()) == "valid"
    assert knowledge.citation({"uri": "repo://app/docs/made-up.md", "sha256": "a" * 64}, key, set()) == "fabricated"
    assert knowledge.citation({**SRC[0], "sha256": "b" * 64}, key, set()) == "stale"
    assert knowledge.citation(SRC[0], key, {SRC[0]["uri"]}) == "unsupported"


def test_score_arm_counts_classes_and_needs_a_valid_citation() -> None:
    keys = {"q1": {"valid_sources": SRC}, "q2": {"valid_sources": SRC}, "q3": {"valid_sources": SRC}}
    answers = [{"id": "q1", "citations": [SRC[0], {"uri": "x://fake"}]}, {"id": "q2", "citations": []}]
    labels = [{"id": "q1", "rater": "a", "correct": True}, {"id": "q1", "rater": "b", "correct": False},
              {"id": "q2", "rater": "a", "correct": True}, {"id": "q2", "rater": "b", "correct": True}]
    s = knowledge.score_arm(keys, answers, labels)
    assert s["correct"] == {"q1": False, "q2": True, "q3": False}  # a tie is incorrect; unanswered is incorrect
    assert s["valid"] == {"q1": False, "q2": False, "q3": False}  # one fabricated citation spoils q1; q2 cites none
    assert s["citations"]["fabricated"] == 1 and s["answered"] == 2 and s["raters"] == ["a", "b"]
    assert cohen_kappa([(True, True), (False, False)]) == 1.0 and cohen_kappa([(True, False), (False, True)]) == -1.0


def test_seal_is_once_hashes_and_plants_canaries(tmp_path: Path) -> None:
    s, h = _suite(tmp_path), tmp_path / "holdouts"
    assert run(app, ["knowledge", "seal", str(s), "--holdouts", str(h)]).exit_code == 0
    keys = [json.loads(x) for x in (s / "keys.jsonl").read_text().splitlines()]
    assert all(custody.CANARY.fullmatch(k["canary"]) for k in keys)
    assert custody.load(h)["sets"]["knowledge-gold-v1"]["canaries"]["q0"] == keys[0]["canary"]
    assert "new version" in run(app, ["knowledge", "seal", str(s)]).output
    with (s / "questions.jsonl").open("a") as f:
        f.write(json.dumps({"id": "q99", "question": "edited in place"}) + "\n")
    res = run(app, ["knowledge", "score", str(s), "--arm", "x"])
    assert res.exit_code == 1 and "questions.jsonl has changed" in res.output


def test_seal_refuses_incomplete_records(tmp_path: Path) -> None:
    s = _suite(tmp_path, 2)
    _w(s / "keys.jsonl", [{"id": "q0", "required_facts": ["x"], "valid_sources": SRC}, {"id": "q1"}])
    assert "valid_sources" in run(app, ["knowledge", "seal", str(s)]).output
    assert not (s / "manifest.json").exists()


def test_report_states_the_fifteen_point_rule_plainly(tmp_path: Path) -> None:
    s = _suite(tmp_path)
    assert run(app, ["knowledge", "seal", str(s)]).exit_code == 0
    _arm(s, "baseline-repo-search", [i < 8 for i in range(20)], {**SRC[0], "sha256": "0" * 64})  # all stale
    _arm(s, "baseline-projects", [i < 9 for i in range(20)])
    _arm(s, "retrieval", [True] * 20)
    (s / "answers" / "baseline-projects.meta.json").write_text('{"person": "dev-a", "date": "2026-10-20"}')
    res = run(app, ["knowledge", "score", str(s), "--arm", "baseline-repo-search", "--arm", "baseline-projects",
                    "--arm", "retrieval", "--baseline", "baseline-repo-search", "--candidate", "retrieval"])
    assert res.exit_code == 0, res.output
    assert "| baseline-repo-search | 20/20 | 8/20 [" in res.output and "| 0/20 [0%, 16%] | 0 | 20 | 0 |" in res.output
    assert "baseline-projects: {\"person\": \"dev-a\"" in res.output and "retrieval: no meta.json" in res.output
    assert "correctness: retrieval - baseline-repo-search = +60.0 points" in res.output
    assert "**baseline-repo-search is shown to lose by at least 15 points on correctness and citation validity.**" \
        in res.output
    close = run(app, ["knowledge", "score", str(s), "--arm", "baseline-projects", "--arm", "baseline-repo-search",
                      "--baseline", "baseline-projects", "--candidate", "baseline-repo-search"])
    assert "**baseline-projects is not shown to lose by 15 points**" in close.output
