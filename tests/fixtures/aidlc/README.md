ai-dlc's two evaluation suites (`evaluations/suites/{smoke,real-client}.json` at ai-dlc's handoff commit `f5be4f4`,
MIT License, see `tasks/fixtures/csv-validator/LICENSE.ai-dlc`), unchanged except that `fixture.path` and
`fixture.hidden` point at this repository's copy of the csv-validator fixture (`tasks/fixtures/csv-validator/`), whose
workspace hashes to the suites' `fixture.digest`. `tests/test_aidlc_import.py` imports both.
