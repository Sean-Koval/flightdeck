"""Opt-in incomplete-observation semantics; default v1 behavior stays unchanged."""
from __future__ import annotations

import copy

import pytest
from spec_traces import trace

from flightdeck.dataplane.flatten import flatten_trace
from flightdeck.dataplane.schema import to_table
from flightdeck.specs import checks, lang

POLICY = 'conservative-v1'
HEAD = f'schema: flightdeck.spec/v1\nharness: "*"\nobservation_policy: {POLICY}\nid: partial\nscope: job\n'
EDIT = [('tool', 'edit', 'x', [])]


def spec(assertion: str) -> dict:
    return lang.load(HEAD + 'assert: ' + assertion)[0]


def both(s: dict, tables: dict) -> dict[str, str]:
    py = lang.evaluate(s, tables)
    with lang.connect_tables(tables) as con:
        assert lang.evaluate_sql(s, con) == py
    return py


def one(assertion: str, steps: list | None = None, truncated: bool = True) -> str:
    result = both(spec(assertion), flatten_trace(trace(EDIT if steps is None else steps, truncated=truncated)))
    return next(iter(result.values()))


@pytest.mark.parametrize(('assertion', 'want'), [
    ('{eventually: {tool: {kind: shell}}}', 'unknown'),
    ('{never: {tool: {kind: edit}}}', 'fail'),
    ('{never: {tool: {kind: shell}}}', 'unknown'),
    ('{count: {match: {tool: {kind: edit}}, min: 2}}', 'unknown'),
    ('{count: {match: {tool: {kind: edit}}, max: 0}}', 'fail'),
    ('{count: {match: {tool: {kind: edit}}, max: 1}}', 'unknown'),
    ('{before: {first: {tool: {kind: plan}}, then: {tool: {kind: edit}}}}', 'unknown'),
    ('{each: {tool: {kind: edit}}, requires_prior: {tool: {kind: plan}}}', 'unknown'),
    ('{all: {paths: {from: [diff.files]}, match: "src/*"}}', 'unknown'),
])
def test_truncated_operator_matrix(assertion: str, want: str) -> None:
    assert one(assertion) == want


@pytest.mark.parametrize('assertion', [
    '{eventually: {tool: {kind: shell}}}', '{never: {tool: {kind: edit}}}',
    '{never: {tool: {kind: shell}}}', '{count: {match: {tool: {kind: edit}}, min: 2}}',
])
def test_complete_behavior_is_unchanged(assertion: str) -> None:
    tables = flatten_trace(trace(EDIT))
    s = spec(assertion)
    legacy = {k: v for k, v in s.items() if k != 'observation_policy'}
    assert both(s, tables) == both(legacy, tables)


def test_legacy_truncated_missing_event_still_fails() -> None:
    s = spec('{eventually: {tool: {kind: shell}}}')
    s.pop('observation_policy')
    assert set(both(s, flatten_trace(trace(EDIT, truncated=True))).values()) == {'fail'}


@pytest.mark.parametrize('value', ['future-v9', None, True, [], {}])
def test_invalid_policy_rejected_even_without_assertion(value: object) -> None:
    with pytest.raises(lang.SpecError, match='observation_policy'):
        lang.plan({'id': 'invalid', 'observation_policy': value})


def test_policy_inheritance_and_explicit_legacy() -> None:
    docs = lang.load(HEAD + 'assert: {eventually: {tool: {kind: shell}}}\n---\nid: child\n'
                     'assert: {eventually: {tool: {kind: shell}}}\n---\nid: old\n'
                     'observation_policy: legacy-v1\nassert: {eventually: {tool: {kind: shell}}}')
    tables = flatten_trace(trace(EDIT, truncated=True))
    assert [next(iter(both(s, tables).values())) for s in docs] == ['unknown', 'unknown', 'fail']


@pytest.mark.parametrize('assertion', [
    '{never: {tool: {kind: edit}, where: {path: null}}}',
    '{never: {tool: {kind: edit}, where: {custom: {in: [null, bad]}}}}',
    '{never: {event: test.run}}',
])
def test_unsupported_witness_shapes_never_prove_failure(assertion: str) -> None:
    assert one(assertion) == 'unknown'


def test_exact_duplicate_tool_is_safe_for_existence_not_positive_count() -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    tables['spans'].append(copy.deepcopy(tables['spans'][-1]))
    assert set(both(spec('{never: {tool: {kind: edit}}}'), tables).values()) == {'fail'}
    assert set(both(spec('{count: {match: {tool: {kind: edit}}, max: 1}}'), tables).values()) == {'unknown'}


@pytest.mark.parametrize('mutation', ['span_conflict', 'run_conflict', 'source_collision', 'missing_span_id',
                                      'trace_attribution', 'run_attribution'])
def test_ambiguous_observations_abstain_and_ignore_order(mutation: str) -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    if mutation == 'span_conflict':
        other = copy.deepcopy(tables['spans'][-1])
        other['tool_kind'] = 'shell'
        tables['spans'].append(other)
    elif mutation == 'run_conflict':
        other = copy.deepcopy(tables['runs'][0])
        other['harness'] = 'other'
        tables['runs'].append(other)
    elif mutation == 'source_collision':
        other = copy.deepcopy(tables['spans'][-1])
        other['source'] = 'session'
        other['span_id'] = 'other'
        tables['spans'].append(other)
    elif mutation == 'missing_span_id':
        tables['spans'][-1]['span_id'] = None
    elif mutation == 'trace_attribution':
        tables['spans'][-1]['job_id'] = 'other-job'
    else:
        tables['spans'][-1]['session_id'] = 'other-session'
    s = spec('{never: {tool: {kind: edit}}}')
    assert set(both(s, tables).values()) == {'unknown'}
    reverse = {k: list(reversed(v)) for k, v in tables.items()}
    assert both(s, reverse) == both(s, tables)


def test_missing_applicability_unknown_explicit_mismatch_not_applicable() -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    s = {**spec('{never: {tool: {kind: edit}}}'), 'applies_when': {'repo': '*required*'}}
    assert set(both(s, tables).values()) == {'not_applicable'}
    tables['runs'][0]['repo'] = None
    assert set(both(s, tables).values()) == {'unknown'}


def test_run_stores_policy_and_legacy_default() -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    s = spec('{eventually: {tool: {kind: shell}}}')
    old = {k: v for k, v in s.items() if k != 'observation_policy'}
    old['id'] = 'old'
    with lang.connect_tables(tables) as con:
        rows = checks.run(con, [s, old], tables['runs'][0]['dt'])
    assert {r['spec_id']: r['observation_policy'] for r in rows} == {'partial': POLICY, 'old': 'legacy-v1'}
    assert to_table('spec_results', rows).num_rows == 2


def test_alert_history_does_not_mix_observation_policies() -> None:
    rows = [{'spec_source': 'spec', 'spec_id': 'same', 'repo': 'r', 'dt': f'2026-10-0{day}',
             'run_id': f'{day}-{i}', 'result': 'pass' if day < 4 else 'fail',
             'observation_policy': None if day < 4 else POLICY}
            for day in range(1, 7) for i in range(40)]
    assert checks.alerts(rows) == []
    for r in rows:
        r.pop('observation_policy')
    assert len(checks.alerts(rows)) == 1


@pytest.mark.parametrize('field', ['harness', 'repo'])
def test_distinct_runs_with_conflicting_applicability_abstain(field: str) -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    other = copy.deepcopy(tables['runs'][0])
    other['run_id'] = 'run-2'
    other[field] = 'different'
    tables['runs'].append(other)
    s = {**spec('{never: {tool: {kind: edit}}}'), 'applies_when': {'repo': '*'}}
    assert set(both(s, tables).values()) == {'unknown'}
    assert both(s, {k: list(reversed(v)) for k, v in tables.items()}) == both(s, tables)


def test_missing_attribution_blocks_failure() -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    tables['spans'][-1]['job_id'] = None
    assert set(both(spec('{never: {tool: {kind: edit}}}'), tables).values()) == {'unknown'}


def test_absent_and_null_schema_columns_normalize_equally() -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    duplicate = copy.deepcopy(tables['spans'][-1])
    duplicate['end_ns'] = tables['spans'][-1]['end_ns']
    duplicate['skill_name'] = None
    tables['spans'].append(duplicate)
    assert set(both(spec('{never: {tool: {kind: edit}}}'), tables).values()) == {'fail'}


def test_positive_operation_witness_and_uninformative_tool_shape() -> None:
    steps = [('tool', 'shell', 'rm public-fixture', ['delete'])]
    assert one('{never: {tool: {ops: [delete]}}}', steps) == 'fail'
    assert one('{never: {tool: {}}}', steps) == 'unknown'
    assert one('{never: {tool: {ops: []}}}', steps) == 'unknown'


def test_gaps_do_not_prove_order_or_missing_approval_violation() -> None:
    assert one('{before: {first: {tool: {kind: plan}}, then: {tool: {kind: edit}}}}',
               EDIT + [('tool', 'plan', 'plan after edit', [])]) == 'unknown'
    assert one('{each: {tool: {ops: [delete]}}, requires_prior: {approval: {status: allowed}}}',
               [('tool', 'shell', 'rm public-fixture', ['delete'])]) == 'unknown'


def test_unrelated_consistent_addition_preserves_existence_witness() -> None:
    tables = flatten_trace(trace(EDIT, truncated=True))
    other = flatten_trace(trace([('tool', 'read', 'other', [])], job='other', session='other', runs='other'))
    extended = {k: rows + other.get(k, []) for k, rows in tables.items()}
    before = both(spec('{never: {tool: {kind: edit}}}'), tables)
    after = both(spec('{never: {tool: {kind: edit}}}'), extended)
    assert all(after[key] == value == 'fail' for key, value in before.items())


def test_conservative_alerts_keep_policy_in_identity() -> None:
    rows = [{'spec_source': 'spec', 'spec_id': 'same', 'repo': 'r', 'dt': f'2026-10-0{day}',
             'run_id': f'{day}-{i}', 'result': 'pass' if day < 4 else 'fail', 'observation_policy': POLICY}
            for day in range(1, 7) for i in range(40)]
    found = checks.alerts(rows)
    assert len(found) == 1 and found[0]['observation_policy'] == POLICY
    calls = []
    def gh(argv: list[str], **_: object):
        import subprocess
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='[]')
    checks.file_alerts(found, 'synthetic/no-network', gh=gh)
    assert any('[conservative-v1]' in arg for arg in calls[-1])


def test_partial_order_with_missing_timing_abstains_without_comparison() -> None:
    tables = flatten_trace(trace(EDIT + [('tool', 'plan', 'late', [])], truncated=True))
    for row in tables['spans']:
        row['seq'] = None
        row['start_ns'] = None
    s = spec('{before: {first: {tool: {kind: plan}}, then: {tool: {kind: edit}}}}')
    assert set(both(s, tables).values()) == {'unknown'}



def test_randomized_policy_parity_and_complete_legacy_agreement() -> None:
    import random

    from spec_traces import random_steps
    rng = random.Random(20261103)
    assertions = ['{never: {tool: {kind: edit}}}', '{never: {tool: {ops: [delete]}}}',
                  '{eventually: {event: test.run}}', '{count: {match: {tool: {kind: shell}}, max: 1}}',
                  '{before: {first: {tool: {kind: plan}}, then: {tool: {kind: edit}}}}',
                  '{each: {tool: {kind: edit}}, requires_prior: {tool: {kind: read}}}']
    for truncated in (False, True):
        tables: dict[str, list[dict]] = {}
        for n in range(10):
            data = flatten_trace(trace(random_steps(rng), job=f'j-{n}', session=f's-{n}', runs=f'r-{n}',
                                       truncated=truncated))
            for name, rows in data.items():
                tables.setdefault(name, []).extend(rows)
        with lang.connect_tables(tables) as con:
            for assertion in assertions:
                for scope in ('turn', 'job', 'session'):
                    s = {**spec(assertion), 'scope': scope}
                    py = lang.evaluate(s, tables)
                    assert lang.evaluate_sql(s, con) == py
                    if truncated:
                        assert 'pass' not in py.values()
                    else:
                        old = {k: v for k, v in s.items() if k != 'observation_policy'}
                        assert py == lang.evaluate(old, tables) == lang.evaluate_sql(old, con)
