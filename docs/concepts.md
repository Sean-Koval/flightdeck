# Concepts

One vocabulary for flightdeck's code, docs and reports. Where hangar or ai-dlc uses a word differently, the entry
says so.

| Term | Meaning | Source |
| --- | --- | --- |
| **runtime** | The agent CLI or loop (Claude Code, Codex, pi, Antigravity) at a version. Hangar calls this the *harness* in its manifest (`harness.name`, `harness.version`) | hangar `harnesses.lock.yaml`, manifest `harness` |
| **harness** | A git directory of native files (`AGENTS.md`, skills, one plugin, per-runtime fragments) plus a `harness.lock` pinning each component's digest, the CLI version and the concrete model. Identity: `harness_digest = sha256(canonical lock)`. Not portable across runtimes; its components are. Note: hangar's manifest `harness` section names the runtime, and its `config_digest` mixes harness and environment | team plan; hangar manifest |
| **environment** | Image, services, egress, resources and credential policy a sandbox gets (`environment_digest`). Not part of the harness | hangar manifest `environment`, `egress`, `resources` |
| **session** | A hangar conversation over time, with its sandbox and checkpoints | hangar `docs/sessions.md` |
| **turn** / **run** | One agent invocation: `hangar.run.id`, one `invoke_agent` span with `hangar.kind = turn`. Flightdeck's `runs` table has one row per turn or per trial | `hangar.trace/v1` |
| **job** | A hangar unit of delivered work: turns, verify, git, PR. Its `source` says where it came from (api, jira, github, ..., experiment) | hangar jobs |
| **work item** | The ticket or issue a job serves (Jira, GitHub) | |
| **trial** | One job run for `(task, variant, n)` under pinned conditions, keyed `<task>/<variant>/<n>` | `hangar.experiment/v1` |
| **experiment** | A batch of trials across tasks and variants. Hangar runs it; flightdeck designs and judges it | hangar spec 0014 §4 |
| **pin set** | The immutable `{harness_digest, environment_digest, model_id, base_sha, grader_digest, knowledge_snapshot?}` a trial runs against | team plan |
| **task** | A Harbor task directory: `task.toml` (flightdeck's keys under `[flightdeck]`), `instruction.md`, `environment/`, hidden `tests/`, optional `solution/`. Identity: `task_digest`. See [tasks.md](tasks.md) | hangar spec 0008; Harbor |
| **suite** | A versioned list of tasks and specs | |
| **holdout** | A sealed suite, scored once | |
| **knowledge snapshot** | The identity of what a retrieval tool could read for a trial (an index's version or digest), recorded in the manifest as `knowledge.snapshot` and in the pin set. The knowledge gold set ([knowledge-evals.md](knowledge-evals.md)) pins questions to `as_of` commits instead | hangar manifest `knowledge` |
| **check** | The repository's own command hangar runs after a turn (`verify`), recorded as a `test.run` event; `hangar.test.run.trusted = true` when hangar ran it, false for the agent's own in-turn runs. The agent can see and change it; a grader it never sees | `hangar.trace/v1` |
| **grader** | A task's hidden tests (`tests/test.sh`, which writes `reward.json`), run on the trial's patch in a clean sandbox outside the agent's reach, from a pristine copy. Identity: `files_digest`. Unlike a check, the agent never sees it | `hangar.experiment/v1` `grade`; [tasks.md](tasks.md) |
| **spec** | A behavior predicate over a trace export | |
| **judge** | A model rubric, used only once calibrated against people (κ ≥ 0.6) | |
| **resolved** | The grader passed (`exit_code == 0` and `applied`), else hangar's verify after the turn passed. Reports always say which | |
| **infra_error** | A trial that failed for infrastructure reasons, not the agent's. Retried, and excluded from statistics | |
| **drift** | A trial whose configuration differs from its variant's other trials (`trial.drift`) | `hangar.experiment/v1` |
| **tainted** | A run that read untrusted content; excluded from promotion evidence | |
| **saturated task** | A task where every trial of every arm had the same outcome: it carries no information for a comparison | |
| **discordant pair** | A task where the two arms disagree on the outcome | |

## Words we don't use

- "eval run" for a trial; "test" for a grader (a test is one case in a check or a grader).
- "harness" for the runtime alone, in flightdeck's own text: say runtime.
