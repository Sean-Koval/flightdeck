"""Tail numbers (agent-factory `airframe/guide/brand.md`, "Tail-number IDs"): flightdeck's port of hangar's
`src/hangar/tails.py` must give the same code for the same real ID, so FDK-EXP-… and HGR-JOB-… agree on one hash."""

import re

from flightdeck.ported import tails

TAIL = re.compile(r"^FDK-(?:[A-Z]+-)?[0-9A-HJKMNP-TV-Z]{4,10}$")  # Crockford base32: no I, L, O, U


def test_codes_match_hangars_examples() -> None:
    assert tails.code("job-e0123d68") == "VDTR" and tails.code("sb-8e7f50c8") == "8AS5"  # hangar's docstring


def test_an_experiment_reads_fdk_exp_with_the_real_id_beside_it() -> None:
    assert TAIL.match(tails.tail("job-expdemo")) and tails.tail("job-expdemo").startswith("FDK-EXP-")
    assert tails.label("job-expdemo") == f"{tails.tail('job-expdemo')} (`job-expdemo`)"
    assert tails.code("job-expdemo", 6).startswith(tails.code("job-expdemo"))  # lengthened on a collision
