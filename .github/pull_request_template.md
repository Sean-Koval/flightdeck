## What and why

Closes #

## Checks

- [ ] `uv run ruff check src tests scripts`
- [ ] `uv run pyright`
- [ ] `uv run pytest -q`
- [ ] `python scripts/loc_budget.py` (within the line budget, ADR 0005)
- [ ] No team data: traces, Parquet, mined tasks, sealed sets or quoted team code (ADR-0002)
- [ ] Docs updated, or "no docs impact" stated here
