"""Explanation layer for sieve_referee (added in v1.6.0, M2 lane).

This module is deliberately SEPARATE from the judgment pipeline:

- ``nfkc_starts`` builds the deterministic NFKC position map
  (normalized position -> original start position) so that any span found in
  the normalized text can be reported against the ORIGINAL text. It handles
  both NFKC shapes measured for the M2 lane: decomposition
  ("か" + U+3099 combining dakuten -> "が", 2 original chars -> 1 normalized
  char) and expansion (U+FB01 ligature -> "fi", 1 -> 2).
- ``explain_results`` re-derives the sentence-level match spans that drive
  the H3 flagging (window_size == 1 chunk pairs with
  ``h3 >= h3_threshold``, the same rule ``SieveReferee.evaluate_pair`` uses)
  and maps them back to original-text positions.

Nothing here mutates an ``EvaluationResult`` or changes any judgment; the
results of the engine are identical with or without the explanation layer
(pinned by tests/test_v1_6_0_m2.py::TestRfT04ExplanationDoesNotTouchJudgments).
"""

import re
import unicodedata
from typing import Dict, List, Tuple

from .chunker import split_into_multi_scale_windows
from .metrics import calc_h3_content_similarity

__all__ = ["nfkc_starts", "explain_results"]

_DELIM = re.compile(r"正?。|！|？|\n")

# Combining marks that NFKC can compose into a preceding base character.
_MARK_CATEGORIES = ("Mn", "Mc", "Me")


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch) in _MARK_CATEGORIES


def _is_jamo(ch: str) -> bool:
    """Hangul jamo (initial/medial/final) that NFKC composes syllable-wise."""
    return 0x1100 <= ord(ch) <= 0x11FF


def _cluster_pieces(original: str) -> List[str]:
    """Per-cluster NFKC pieces: a base character together with any following
    combining marks, or a maximal hangul jamo run, normalized in isolation.

    NFKC only merges characters inside one cluster for the vast majority of
    real text; ``nfkc_starts`` VERIFIES that the piece concatenation equals
    the true normalization and falls back to the exact prefix-length path
    otherwise (e.g. compatibility-decomposed jamo pairs), so the returned
    mapping is exact for every input either way.
    """
    pieces: List[str] = []
    i = 0
    n = len(original)
    while i < n:
        j = i + 1
        if _is_jamo(original[i]):
            while j < n and _is_jamo(original[j]):
                j += 1
        else:
            while j < n and _is_mark(original[j]):
                j += 1
        pieces.append(unicodedata.normalize("NFKC", original[i:j]))
        i = j
    return pieces


def _starts_exact(original: str, norm: str) -> List[int]:
    """Exact mapping via prefix lengths.

    ``fs[j] == len(NFKC(original[:j]))``; the k-th normalized character began
    forming at the smallest ``j`` with ``fs[j + 1] > k`` (the sentinel is
    ``len(original)``). Deterministic and exact for every input; O(n^2) in
    the worst case, so it is only used when the cluster fast path cannot
    reproduce the true normalization.
    """
    fs = [0]
    acc = []
    for ch in original:
        acc.append(ch)
        fs.append(len(unicodedata.normalize("NFKC", "".join(acc))))
    starts: List[int] = []
    j = 0
    for k in range(len(norm)):
        while j < len(original) and fs[j + 1] <= k:
            j += 1
        starts.append(j)
    starts.append(len(original))
    return starts


def nfkc_starts(original: str) -> Tuple[str, List[int]]:
    """Map normalized positions back to original positions.

    Returns ``(norm_text, starts)`` where
    ``norm_text == unicodedata.normalize("NFKC", original)`` and ``starts``
    has ``len(norm_text) + 1`` entries: ``starts[i]`` is the position in
    ``original`` where the i-th normalized character begins forming, and
    ``starts[-1] == len(original)`` is the sentinel. ``starts`` is
    non-decreasing; a normalized RANGE ``[s, e)`` with ``s < e`` recovers the
    original text as ``original[starts[s]:starts[e]]``. Decomposition
    (2 originals -> 1 normalized char) and expansion (1 -> 2) are both
    covered.
    """
    norm = unicodedata.normalize("NFKC", original)
    if not original:
        return norm, [0]

    pieces = _cluster_pieces(original)
    if "".join(pieces) == norm:
        starts: List[int] = []
        oi = 0
        idx = 0
        for end in _cluster_end_offsets(original):
            piece = pieces[idx]
            for _ in piece:
                starts.append(oi)
            idx += 1
            oi = end
        starts.append(len(original))
        return norm, starts
    return norm, _starts_exact(original, norm)


def _cluster_end_offsets(original: str) -> List[int]:
    ends: List[int] = []
    i = 0
    n = len(original)
    while i < n:
        j = i + 1
        if _is_jamo(original[i]):
            while j < n and _is_jamo(original[j]):
                j += 1
        else:
            while j < n and _is_mark(original[j]):
                j += 1
        ends.append(j)
        i = j
    return ends


def _sentence_spans(text: str) -> List[Tuple[int, int]]:
    """Original-sentence spans mirroring chunker.split_into_multi_scale_windows.

    The chunker keeps the non-blank segments of
    ``re.split(r"正?。|！|？|\\n", text)`` in order (stripped, with "。" appended
    to the chunk text); this returns the stripped [start, end) span of each
    kept segment, so kept-segment index == window_size-1 chunk_id.
    """
    spans: List[Tuple[int, int]] = []

    def push(s: int, e: int) -> None:
        seg = text[s:e]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            trail = len(seg) - len(seg.rstrip())
            spans.append((s + lead, e - trail))

    pos = 0
    for m in _DELIM.finditer(text):
        push(pos, m.start())
        pos = m.end()
    push(pos, len(text))
    return spans


def explain_results(documents: Dict[str, str], results, h3_threshold: float = 0.45) -> Dict[str, List[Dict[str, int]]]:
    """Collect the sentence-level match spans behind each pair's H3 flag.

    ``documents`` maps document ids to the SAME texts that were passed to
    ``batch_evaluate``; ``results`` is the engine's output list. For every
    result the returned dict carries the pair key
    ``"{item_id}_vs_{matched_peer_id}"`` (the same key the CLI diff reports
    use) to a list of spans ``{"a_start", "a_end", "b_start", "b_end"}`` with
    positions into the texts as passed in (the caller's originals). A span is
    emitted for every window_size-1 chunk pair whose H3 similarity reaches
    ``h3_threshold`` — the same condition that drives the engine's flagged
    sentences. Pairs with no such sentence pair get an empty list. Judgment
    values are never modified.
    """
    maps = {doc_id: nfkc_starts(text) for doc_id, text in documents.items()}
    sent_spans = {doc_id: _sentence_spans(norm) for doc_id, (norm, _) in maps.items()}

    out: Dict[str, List[Dict[str, int]]] = {}
    for res in results:
        key = "%s_vs_%s" % (res.item_id, res.matched_peer_id)
        spans: List[Dict[str, int]] = []
        if res.item_id in documents and res.matched_peer_id in documents:
            norm_a, starts_a = maps[res.item_id]
            norm_b, starts_b = maps[res.matched_peer_id]
            spans_a = sent_spans[res.item_id]
            spans_b = sent_spans[res.matched_peer_id]
            chunks_a = split_into_multi_scale_windows(norm_a, [1, 2])
            chunks_b = split_into_multi_scale_windows(norm_b, [1, 2])
            for ca in chunks_a:
                if ca.window_size != 1:
                    continue
                for cb in chunks_b:
                    if cb.window_size != 1:
                        continue
                    if calc_h3_content_similarity(ca.text, cb.text) >= h3_threshold:
                        sa = spans_a[ca.chunk_id]
                        sb = spans_b[cb.chunk_id]
                        spans.append({
                            "a_start": starts_a[sa[0]],
                            "a_end": starts_a[sa[1]],
                            "b_start": starts_b[sb[0]],
                            "b_end": starts_b[sb[1]],
                        })
        out[key] = spans
    return out
