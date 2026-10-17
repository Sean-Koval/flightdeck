# 0008: Agents never push to the default branch

Status: Accepted · Oct 15, 2026

Synthetic fixture (flightdeck's plain-text template).

## Checks (optional)

```yaml
checks:
  - id: never-push-main
    scope: turn
    assert: {never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}}
```
