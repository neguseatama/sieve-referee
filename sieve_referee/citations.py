"""Citation / bibliography exclusion for sieve_referee (added in v1.6.0, M2).

Opt-in preprocessing (default OFF everywhere): removes from a document the
parts that legitimately repeat across authors —

1. bibliography sections: a heading line whose text (surrounding whitespace
   and leading ``#`` markers stripped) equals one of the six heading words in
   ``BIB_HEADINGS`` — Latin words case-insensitively — excludes that line and
   everything after it (to the end of the document);
2. long quotation pairs: each ``「 ... 」`` pair whose inner text is at least
   ``quote_min_inner`` characters (default 10) is removed including the
   brackets. Scanning is a single left-to-right pass; the first ``」`` after
   an opening ``「`` closes it; pairs with shorter inner text are kept.

Bibliography lines are removed first, then quotation pairs. The function is
idempotent: stripping already-stripped text returns it unchanged.
"""

from typing import Iterable

__all__ = ["BIB_HEADINGS", "strip_citations"]

BIB_HEADINGS = (
    "参考文献",
    "引用文献",
    "References",
    "Bibliography",
    "Works Cited",
    "Literature Cited",
)


def strip_citations(text: str, quote_min_inner: int = 10, headings: Iterable[str] = BIB_HEADINGS) -> str:
    """Remove bibliography sections and long quotation pairs from ``text``."""
    text = _strip_bibliography(text, headings)
    text = _strip_long_quotes(text, quote_min_inner)
    return text


def _strip_bibliography(text: str, headings: Iterable[str]) -> str:
    folded = {h.casefold() for h in headings}
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        candidate = line.strip().lstrip("#").strip()
        if candidate.casefold() in folded:
            return "\n".join(lines[:idx]).rstrip("\n")
    return text


def _strip_long_quotes(text: str, min_inner: int) -> str:
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
        if cl - (op + 1) >= min_inner:
            out.append(text[i:op])
            i = cl + 1
        else:
            out.append(text[i : cl + 1])
            i = cl + 1
    return "".join(out)
