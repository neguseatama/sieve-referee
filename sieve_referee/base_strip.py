"""Base-document segment removal for sieve_referee (v1.6.0, M2).

The M2 request (§3.3) defines TWO obligations for base documents
(``--base`` / ``base_documents=``):

1. the base documents themselves never enter the evaluation universe
   (implemented in ``evaluator.batch_evaluate``);
2. spans INSIDE each submission that match a base document are removed
   BEFORE the comparison, so that submissions sharing only the assignment
   text do not look similar to each other.

This module implements obligation 2 with the M2 request §3.2 winnowing
fingerprint (design review round 3): the match seeds are
the §3.2 fingerprint spans (k=8 characters, w=5 — the constants in
``sieve_referee.fingerprint``) between the submission and each base
document, each seed is extended over the surrounding verbatim exact match,
and only runs of at least ``MIN_BASE_SPAN`` characters (16 — §3.2's
fingerprint minimum, NOT §3.4's quote minimum) are removed. Shared runs
shorter than that are never removed and never reported (pinned by
RF-T11c). The scan is a SINGLE pass over the text as passed in: material
that only becomes a match through the adjacency created by a removal is
conservatively kept (never re-scanned), and every reported position is
exact against the input text.

``strip_base_segments`` returns ``(stripped_text, removed_spans)`` where
each removed span is ``{"start", "end", "length", "text"}`` with positions
mapped back to the text AS PASSED IN through the same deterministic NFKC
position map the explanation layer uses (``explain.nfkc_starts``).
"""

import unicodedata
from typing import Dict, Iterable, List, Tuple

from .explain import nfkc_starts
from .fingerprint import MIN_FINGERPRINT_SPAN, fingerprint_match_spans

__all__ = ["MIN_BASE_SPAN", "strip_base_segments"]

MIN_BASE_SPAN = MIN_FINGERPRINT_SPAN  # M2 request §3.2 (16 chars)


def strip_base_segments(
    text: str,
    base_texts: Iterable[str],
    min_span: int = MIN_BASE_SPAN,
) -> Tuple[str, List[Dict[str, int]]]:
    """Remove spans of ``text`` that match any of ``base_texts``.

    Returns ``(stripped_text, removed_spans)``; the spans are reported
    against ``text`` as passed in (original positions, via the NFKC
    position map). Empty base texts are ignored; with no usable base the
    input is returned unchanged with an empty report.
    """
    base_norms = [unicodedata.normalize("NFKC", b) for b in base_texts if b]
    if not base_norms or not text:
        return text, []

    norm, starts = nfkc_starts(text)
    if not norm:
        return text, []

    # §3.2 fingerprint seeds between the submission and every base document
    spans: List[Dict[str, int]] = []
    for base in base_norms:
        spans.extend(fingerprint_match_spans(norm, base, min_span=min_span))
    if not spans:
        return text, []
    spans.sort(key=lambda d: (d["a_start"], d["a_end"]))

    pieces: List[str] = []
    removed: List[Dict[str, int]] = []
    last = 0  # original-text position up to which everything is kept
    pos = 0   # normalized position up to which everything is decided
    for sp in spans:
        s, e = sp["a_start"], sp["a_end"]
        if e <= pos:
            continue  # fully covered by an earlier removal
        if s < pos:
            s = pos   # partial overlap: only the rest is this run's
        if e - s < min_span:
            continue  # conservative: remainder below the minimum is kept
        r_start = starts[s]
        r_end = starts[e]
        if r_end > r_start:
            pieces.append(text[last:r_start])
            removed.append({
                "start": r_start,
                "end": r_end,
                "length": r_end - r_start,
                "text": text[r_start:r_end],
            })
            last = r_end
        pos = e
    pieces.append(text[last:])
    return "".join(pieces), removed
