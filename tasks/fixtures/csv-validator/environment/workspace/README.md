# csvcheck

Validates a CSV file and reports problems. Standard library only.

```sh
python -m csvcheck data.csv
python -m unittest discover -s tests
```

`validate(path)` returns a list of `Problem(line, code, detail)`, ordered by line.
Lines are 1-based and count every physical line, including the header and blank
lines. Blank lines are ignored. The command prints one problem per line as
`<line>:<code>:<detail>` and exits 1 when there are problems, otherwise 0.

Current codes: `empty-file`, `column-count`.
