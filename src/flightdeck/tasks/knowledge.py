"""`flightdeck knowledge seal|score`: the knowledge gold set, scored on correctness and citation validity
(docs/knowledge-evals.md).

A suite directory (private data repo, e.g. `suites/knowledge-gold-v1/`) holds `questions.jsonl` (`id, question, kind,
as_of, scope`: what an arm may read), `keys.jsonl` (`id, answer_key, required_facts, valid_sources [{uri, sha256}],
canary`: sealed until scored) and `manifest.json` (both files' sha256; a changed file is refused, so a new version is a
new suite). Each arm's answers are `answers/<arm>.jsonl` (`id, answer, citations [{uri, sha256}]`) with
`answers/<arm>.meta.json` (how it was run: person or harness, date, model, knowledge_snapshot), and raters' labels are
`labels/<arm>.jsonl` (`id, rater, correct` = every required fact present, `unsupported` = cited uris whose span
doesn't support the claim).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer

from flightdeck.stats.core import cohen_kappa, paired_bootstrap, wilson
from flightdeck.tasks import custody

KINDS = {"decision-why", "blocker", "what-changed", "how-to", "who-owns"}
RULE = 0.15  # the knowledge plan: build retrieval only if the baselines lose by at least 15 points


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.is_file() else []


def seal(suite: Path, holdouts: Path | None = None) -> int:
    """Check the records, give each answer key a canary, and hash both files into manifest.json. A suite is sealed
    once; with `holdouts`, its canaries join that manifest so `holdout canary-scan` voids it on a leak."""
    if (suite / "manifest.json").is_file():
        raise custody.CustodyError(f"{suite} is sealed: questions change only in a new version (v2)")
    qs, keys = _jsonl(suite / "questions.jsonl"), _jsonl(suite / "keys.jsonl")
    if sorted(q["id"] for q in qs) != sorted(k["id"] for k in keys) or len({q["id"] for q in qs}) < len(qs):
        raise custody.CustodyError("questions.jsonl and keys.jsonl need the same unique ids")
    for q, k in zip(qs, keys, strict=True):
        if q.get("kind") not in KINDS or not q.get("as_of") or not k.get("required_facts") or not k.get(
                "valid_sources"):
            raise custody.CustodyError(f"{q['id']}: needs kind in {sorted(KINDS)}, as_of, required_facts, "
                                       "valid_sources")
    for k in keys:
        k.setdefault("canary", f"FLIGHTDECK-CANARY-{uuid.uuid4()}")
    (suite / "keys.jsonl").write_text("".join(json.dumps(k) + "\n" for k in keys))
    doc = {"files": {f: custody.sha256(suite / f) for f in ("questions.jsonl", "keys.jsonl")}, "sets": {}}
    custody.save(suite, doc)
    if holdouts:
        h = custody.load(holdouts)
        h["sets"][suite.name] = {"tasks": {k["id"]: "knowledge" for k in keys}, "writers": {}, "status": "sealed",
                                 "canaries": {k["id"]: k["canary"] for k in keys}, "kind": "knowledge"}
        custody.save(holdouts, h)
    return len(keys)


def citation(c: dict[str, Any], key: dict[str, Any], unsupported: set[str]) -> str:
    """valid, fabricated (not a source the question allows), stale (the content's hash differs from the source's at
    as_of) or unsupported (a rater says the cited span doesn't support the claim)."""
    want = {s["uri"]: s.get("sha256") for s in key["valid_sources"]}
    if c.get("uri") not in want:
        return "fabricated"
    if want[c["uri"]] and c.get("sha256") != want[c["uri"]]:
        return "stale"
    return "unsupported" if c["uri"] in unsupported else "valid"


def score_arm(keys: dict[str, dict], answers: list[dict], labels: list[dict]) -> dict[str, Any]:
    """Per-question correctness (raters' majority; a tie is incorrect) and citation validity (at least one citation,
    all valid), each with a Wilson interval, the citation classes and the raters' agreement."""
    by_q: dict[str, list[dict]] = {}
    for lab in labels:
        by_q.setdefault(lab["id"], []).append(lab)
    got = {a["id"]: a for a in answers}
    correct, valid, classes = {}, {}, {"valid": 0, "fabricated": 0, "stale": 0, "unsupported": 0}
    for qid, key in keys.items():
        labs = by_q.get(qid, [])
        correct[qid] = sum(bool(x["correct"]) for x in labs) * 2 > len(labs) if labs else False
        unsup = {u for x in labs for u in x.get("unsupported") or []}
        cs = [citation(c, key, unsup) for c in (got.get(qid) or {}).get("citations") or []]
        for c in cs:
            classes[c] += 1
        valid[qid] = bool(cs) and all(c == "valid" for c in cs)
    raters = sorted({x["rater"] for x in labels})[:2]
    pairs = [(a["correct"], b["correct"]) for q in by_q.values() for a in q for b in q
             if len(raters) == 2 and (a["rater"], b["rater"]) == tuple(raters)]
    n = len(keys)
    return {"n": n, "answered": sum(q in got for q in keys), "correct": correct, "valid": valid, "citations": classes,
            "correctness": (sum(correct.values()), wilson(sum(correct.values()), n)),
            "citation_validity": (sum(valid.values()), wilson(sum(valid.values()), n)),
            "kappa": cohen_kappa(pairs) if pairs else None, "raters": raters}


def render(arms: dict[str, dict], baseline: str | None, candidate: str | None, seed: int = 0) -> str:
    out = ["| arm | answered | correctness (95% Wilson) | citation validity (95% Wilson) | fabricated | stale | "
           "unsupported | raters' κ |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, s in arms.items():
        cell = lambda m, n=s["n"]: f"{m[0]}/{n} [{m[1][0]:.0%}, {m[1][1]:.0%}]"  # noqa: E731
        k = "-" if s["kappa"] is None else f"{s['kappa']:.2f} ({' vs '.join(s['raters'])})"
        out.append(f"| {name} | {s['answered']}/{s['n']} | {cell(s['correctness'])} | {cell(s['citation_validity'])}"
                   f" | {s['citations']['fabricated']} | {s['citations']['stale']} | {s['citations']['unsupported']}"
                   f" | {k} |")
    if baseline and candidate:
        b, c = arms[baseline], arms[candidate]
        out.append("")
        lose = []
        for m in ("correct", "valid"):
            d = paired_bootstrap({q: ([float(b[m][q])], [float(c[m][q])]) for q in b[m]}, seed=seed)
            name = "correctness" if m == "correct" else "citation validity"
            out.append(f"- {name}: {candidate} - {baseline} = {d.estimate * 100:+.1f} points, 95% CI "
                       f"{d.low * 100:+.1f} to {d.high * 100:+.1f} (bootstrap over {d.n_tasks} questions, seed {seed})")
            lose += [name] if d.low >= RULE else []
        out.append("")
        out.append(f"**{baseline} is shown to lose by at least 15 points on {' and '.join(lose)}.**" if lose else
                   f"**{baseline} is not shown to lose by 15 points** (neither interval's lower bound reaches +15).")
    return "\n".join(out)


app = typer.Typer(help="The knowledge gold set: seal it, score arms on correctness and citations.",
                  no_args_is_help=True)


@app.command("seal")
def seal_cmd(suite: Path, holdouts: Annotated[Path | None, typer.Option(help="Register canaries here.")] = None):
    """Check the suite, plant canaries in the answer keys and write manifest.json (commit it on its own)."""
    try:
        typer.echo(f"sealed {seal(suite, holdouts)} questions in {suite}")
    except custody.CustodyError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None


@app.command("score")
def score_cmd(suite: Path, arm: Annotated[list[str], typer.Option(help="An arm with answers/<arm>.jsonl.")],
              baseline: str | None = None, candidate: str | None = None, seed: int = 0) -> None:
    """Score each arm; with --baseline and --candidate, the paired difference and the 15-point rule."""
    try:
        custody.check_manifest(suite, custody.load(suite))
        if not (suite / "manifest.json").is_file():
            raise custody.CustodyError(f"{suite} isn't sealed (flightdeck knowledge seal)")
    except custody.CustodyError as e:
        typer.secho(f"error: {e}", fg="red", err=True)
        raise typer.Exit(1) from None
    keys = {k["id"]: k for k in _jsonl(suite / "keys.jsonl")}
    arms = {a: score_arm(keys, _jsonl(suite / "answers" / f"{a}.jsonl"), _jsonl(suite / "labels" / f"{a}.jsonl"))
            for a in arm}
    for a in arm:
        meta = suite / "answers" / f"{a}.meta.json"
        typer.echo(f"{a}: " + (meta.read_text().strip() if meta.is_file() else "no meta.json: say how it was run"))
    typer.echo(render(arms, baseline, candidate, seed))
