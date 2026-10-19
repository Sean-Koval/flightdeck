# Agent guidance

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev loop, the checks CI runs, the front-page assets and the line budget.

Design: Airframe, in [Sean-Koval/agent-factory](https://github.com/Sean-Koval/agent-factory) (`airframe/`), is the design
source of truth for everything visual here. Read its `airframe/README.md` and component READMEs before UI, report or docs
styling work; use `var(--af-*)` tokens and `af-` classes only; never edit the vendored `docs/stylesheets/airframe*.css`
(refresh with `sh scripts/sync-airframe.sh theme-vN`). See [CONTRIBUTING.md#design](CONTRIBUTING.md#design).
Coding agents: the Airframe skill is committed at `.claude/skills/airframe/` (Claude Code) and `.agents/skills/airframe/` (Codex) with the rules and the class map; refresh it with `npx shadcn@latest add https://sean-koval.github.io/agent-factory/r/skill.json` and never edit it here.

## Tracking

- Work is tracked in Jira project KAN (<https://seanmkoval.atlassian.net>). GitHub Projects is retired; GitHub Issues are for outside reports only.
- Work tied to a ticket carries its key, so the GitHub for Jira app links it: the branch starts with it (`KAN-35-apply-atomic`), the PR title starts with it (`KAN-35: make hangar apply all or nothing`) and the PR body has a `Jira: KAN-35` line. Commits may mention it. Work without a ticket (typo fixes, outside contributions) needs no key.
- Lanes: only `lane:agent` tickets (job-sized: one repo or one change-set profile, acceptance criteria, a verify command) start a hangar job, when moved to "Ready for agent". `lane:pair` is Sean with Claude Code; `lane:human` is Sean only.
