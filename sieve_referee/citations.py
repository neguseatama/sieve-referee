"""Quote / bibliography exclusion for sieve_referee (v1.6.0, M2).

Opt-in preprocessing (default OFF everywhere): removes from a document the
parts that legitimately repeat across authors. Per the M2 request (§3.4)
the two exclusions are INDEPENDENT: the CLI exposes them as the separate
flags ``--exclude-quotes`` and ``--exclude-bibliography`` and the library
as the separate ``batch_evaluate`` keyword arguments ``exclude_quotes`` /
``exclude_bibliography``. No combined flag or alias is provided (revised
in the design-review round; the first draft had one combined flag).

1. ``strip_bibliography``: a heading line whose text (surrounding whitespace
   and leading ``#`` markers stripped) equals one of the six heading words in
   ``BIB_HEADINGS`` — Latin words case-insensitively — excludes that line and
   everything after it (to the end of the document);
2. ``strip_quotes``: each ``「 ... 」`` pair whose inner text is at least
   ``quote_min_inner`` characters (default 10) is removed including the
   brackets. Scanning is a single left-to-right pass; the first ``」`` after
   an opening ``「`` closes it; pairs with shorter inner text are kept.

When both exclusions are requested the bibliography is removed first, then
the quotation pairs (the order fixed at the red stage). Each function is
idempotent: stripping already-stripped text returns it unchanged.
"""

from typing import Iterable

__all__ = ["BIB_HEADINGS", "strip_bibliography", "strip_quotes"]

BIB_HEADINGS = (
    "参考文献",
    "引用文献",
    "References",
    "Bibliography",
    "Works Cited",
    "Literature Cited",
)


def strip_bibliography(text: str, headings: Iterable[str] = BIB_HEADINGS) -> str:
    """Remove bibliography sections (heading line to end of document)."""
    folded = {h.casefold() for h in headings}
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        candidate = line.strip().lstrip("#").strip()
        if candidate.casefold() in folded:
            return "\n".join(lines[:idx]).rstrip("\n")
    return text


def strip_quotes(text: str, quote_min_inner: int = 10) -> str:
    """Remove 「…」 pairs whose inner text is at least ``quote_min_inner``."""
    out = []
    i = 0
    while i < len(text):
        op = text.find("「", i)
        if op == -1:
            out.append(text[i:])
            break
        cl = text.find("」", op + 1)
        if cl == -1:
            out.append(text[i:])
            break
        if cl - (op + 1) >= quote_min_inner:
            out.append(text[i:op])
            i = cl + 1
        else:
            out.append(text[i : cl + 1])
            i = cl + 1
    return "".join(out)
