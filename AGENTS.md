# Agent guidance

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev loop, the checks CI runs, the front-page assets and the line budget.

Design: Airframe, in [Sean-Koval/agent-factory](https://github.com/Sean-Koval/agent-factory) (`airframe/`), is the design
source of truth for everything visual here. Read its `airframe/README.md` and component READMEs before UI, report or docs
styling work; use `var(--af-*)` tokens and `af-` classes only; never edit the vendored `docs/stylesheets/airframe*.css`
(refresh with `sh scripts/sync-airframe.sh theme-vN`). See [CONTRIBUTING.md#design](CONTRIBUTING.md#design).
Coding agents: the Airframe skill is committed at `.claude/skills/airframe/` (Claude Code) and `.agents/skills/airframe/` (Codex) with the rules and the class map; refresh it with `npx shadcn@latest add https://sean-koval.github.io/agent-factory/r/skill.json` and never edit it here.
