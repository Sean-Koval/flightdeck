"""Tail numbers: ported from hangar `src/hangar/tails.py` (KAN-114), with flightdeck's prefix, so a person reads
`FDK-EXP-…` for an experiment the way they read `HGR-JOB-…` for a hangar job (agent-factory `airframe/guide/brand.md`,
"Tail-number IDs").

The code is Crockford base32 of a 53-bit hash (cyrb53) of the whole real ID, four characters. Display only: commands,
the report's marker, URLs and the data plane keep the real ID; text a person reads (the PR comment) leads with the tail
and keeps the real ID beside it, since a comment has no hover and a person may paste the ID into the CLI.
"""

from __future__ import annotations

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PRODUCT = "FDK"
MIN, MAX = 4, 10
_M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & _M32


def hash53(s: str) -> int:
    """cyrb53 over the string's UTF-16 code units, as JavaScript's charCodeAt reads them."""
    h1, h2 = 0xDEADBEEF, 0x41C6CE57
    units = s.encode("utf-16-le")
    for i in range(0, len(units), 2):
        c = units[i] | units[i + 1] << 8
        h1 = _imul(h1 ^ c, 2654435761)
        h2 = _imul(h2 ^ c, 1597334677)
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507) ^ _imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507) ^ _imul(h1 ^ (h1 >> 13), 3266489909)
    return 4294967296 * (2097151 & h2) + (h1 & _M32)


def code(identifier: str, n: int = MIN) -> str:
    h = hash53(identifier)
    return "".join(ALPHABET[(h >> (45 - 5 * i)) & 31] for i in range(min(n, MAX)))


def tail(identifier: str, kind: str = "EXP") -> str:
    """job-expdemo -> FDK-EXP-…: the product prefix, the kind segment and the code."""
    return f"{PRODUCT}-{kind + '-' if kind else ''}{code(identifier)}"


def label(identifier: str, kind: str = "EXP") -> str:
    """For Markdown a person reads: the tail, then the real ID in code (`FDK-EXP-… (`job-expdemo`)`)."""
    return f"{tail(identifier, kind)} (`{identifier}`)"
