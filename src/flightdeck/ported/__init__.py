"""Code ported from hangar and ai-dlc, kept close to its source; outside the line budget (docs/decisions/0003).

Every file here is kept on purpose and has a caller (KAN-93):

- `modelpolicy.py` (hangar): the model-concreteness rule, for `experiment run`'s refusal of floating model ids;
- `hangar_traces.py` (hangar): `shell_ops` for the local backend's spans, `tool_kind` for the process-metric tests;
- `tails.py` (hangar): tail numbers in reports;
- `aidlc/`: the local backend's attempt runner and `task import-aidlc`'s contracts (see its docstring).
"""
