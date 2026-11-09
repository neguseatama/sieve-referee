"""Base-document segment removal for sieve_referee (v1.6.0, M2).

The M2 request (§3.3) defines TWO obligations for base documents
(``--base`` / ``base_documents=``):

1. the base documents themselves never enter the evaluation universe
   (implemented in ``evaluator.batch_evaluate``);
2. spans INSIDE each submission that match a base document are removed
   BEFORE the comparison, so that submissions sharing only the assignment
   text do not look similar to each other.

This module implements obligation 2. Matching is exact-substring in NFKC
space, scanned left-to-right greedy maximal: at each position the longest
span that appears (contiguously) in any base document is taken; spans
shorter than ``min_span`` characters (default 10 — the same "meaningful
repetition" threshold the quote exclusion uses) are kept. The scan is a
SINGLE pass over the text as passed in: material that only becomes a match
through the adjacency created by a removal is conservatively kept (never
re-scanned), and every reported position is exact against the input text.

``strip_base_segments`` returns ``(stripped_text, removed_spans)`` where
each removed span is ``{"start", "end", "length", "text"}`` with positions
mapped back to the text AS PASSED IN through the same deterministic NFKC
position map the explanation layer uses (``explain.nfkc_starts``).
"""

import unicodedata
from typing import Dict, Iterable, List, Tuple

from .explain import nfkc_starts

__all__ = ["MIN_BASE_SPAN", "strip_base_segments"]

MIN_BASE_SPAN = 10


def _longest_match_at(norm_doc: str, i: int, base_norms: List[str], limit: int) -> int:
    """Largest L with ``norm_doc[i:i+L]`` a substring of some base (0 if none).

    Monotonic in L (any prefix of a substring is a substring), so the largest
    L is found by binary search per base; ``best`` carries the running
    maximum across bases.
    """
    best = 0
    for base in base_norms:
        lo, hi = best + 1, min(len(base), limit)
        while lo <= hi:
            mid = (lo + hi) // 2
            if norm_doc[i : i + mid] in base:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
    return best


def _strip_once(text: str, base_norms: List[str], min_span: int) -> Tuple[str, List[Dict[str, int]]]:
    """Single left-to-right greedy pass; positions are exact on ``text``."""
    norm, starts = nfkc_starts(text)
    n = len(norm)
    pieces: List[str] = []
    removed: List[Dict[str, int]] = []
    last = 0
    i = 0
    while i < n:
        length = _longest_match_at(norm, i, base_norms, n - i)
        if length >= min_span:
            r_start = starts[i]
            r_end = starts[i + length]
            if r_end > r_start:
                pieces.append(text[last:r_start])
                removed.append({
                    "start": r_start,
                    "end": r_end,
                    "length": r_end - r_start,
                    "text": text[r_start:r_end],
                })
                last = r_end
            i += length
        else:
            i += 1
    pieces.append(text[last:])
    return "".join(pieces), removed


def strip_base_segments(
    text: str,
    base_texts: Iterable[str],
    min_span: int = MIN_BASE_SPAN,
) -> Tuple[str, List[Dict[str, int]]]:
    """Remove spans of ``text`` that appear in any of ``base_texts``.

    Returns ``(stripped_text, removed_spans)``; the spans are reported
    against ``text`` as passed in (original positions, via the NFKC
    position map). Empty base texts are ignored; with no usable base the
    input is returned unchanged with an empty report.
    """
    base_norms = [unicodedata.normalize("NFKC", b) for b in base_texts if b]
    if not base_norms or not text:
        return text, []
    return _strip_once(text, base_norms, min_span)
