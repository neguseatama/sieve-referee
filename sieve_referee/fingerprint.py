"""Winnowing fingerprints for sieve_referee (v1.6.0, M2 request §3.2).

The M2 request fixes the explanation layer's METHOD: winnowing
fingerprints with k=8 characters, w=5 windows, and a minimum match length
of 16 characters. The same mechanism and the same span output contract are
planned for sieve-scope 1.5.0 (token-normalized, k=5 tokens / w=4 /
minimum 10 tokens there), so Tray's Cohort can treat both engines in one
shape.

Constants (fixed at the red stage, worklog §108):

- ``FINGERPRINT_K = 8``  — k-gram length in characters
- ``FINGERPRINT_W = 5``  — winnowing window width
- ``MIN_FINGERPRINT_SPAN = 16`` — minimum reported/removed match length

Determinism rules (also fixed at the red stage):

- k-gram hashes use **blake2b (digest_size=8)** over the UTF-8 bytes of the
  k consecutive characters; the salted builtin ``hash()`` is never used, so
  output is independent of PYTHONHASHSEED (pinned by RF-T11b).
- Winnowing scans the hash stream with w-wide windows (a stream shorter
  than w is treated as ONE window); each window selects the leftmost
  minimum hash; a position already selected is not selected again; the
  selected fingerprints are returned in ascending position order. A text
  shorter than k characters has no fingerprints.
- Match-span recovery from shared fingerprints: every (a, b) pair of
  selected fingerprints with the SAME hash yields an ``offset = b_pos -
  a_pos``; pairs are grouped by offset (same relative placement), inside
  each group the coverage spans ``[a_pos, a_pos + k)`` are merged when they
  overlap or touch (selected-fingerprint distance is <= w < k, so one
  continuous exact-match region never splits), each merged region is then
  EXTENDED over the surrounding exact match character by character, and
  only regions of length >= ``min_span`` are returned (a shorter shared run
  cannot extend past its own length, so it is never reported — RF-T11c).
  Complete exact matches of >= min_span characters always contain at least
  one shared fingerprint (winnowing guarantee: matches of length >= w+k-1
  = 12 share one), so they are always recovered in full.
- Output positions are into the two texts AS PASSED IN (NFKC space for the
  referee pipeline); mapping back to raw originals is the caller's job via
  ``explain.nfkc_starts``.
"""

import hashlib
from typing import Dict, List, Tuple

__all__ = [
    "FINGERPRINT_K",
    "FINGERPRINT_W",
    "MIN_FINGERPRINT_SPAN",
    "kgram_hashes",
    "winnowing_fingerprints",
    "fingerprint_match_spans",
]

FINGERPRINT_K = 8          # M2 request §3.2
FINGERPRINT_W = 5          # M2 request §3.2
MIN_FINGERPRINT_SPAN = 16  # M2 request §3.2


def kgram_hashes(text: str, k: int = FINGERPRINT_K) -> List[int]:
    """Hash every k-gram of ``text`` with blake2b (digest 8 bytes).

    Returns the list of ``len(text) - k + 1`` integers (big-endian digest);
    empty when ``text`` is shorter than ``k``. Pure and deterministic.
    """
    out: List[int] = []
    for i in range(len(text) - k + 1):
        digest = hashlib.blake2b(
            text[i:i + k].encode("utf-8"), digest_size=8).digest()
        out.append(int.from_bytes(digest, "big"))
    return out


def winnowing_fingerprints(
    text: str,
    k: int = FINGERPRINT_K,
    w: int = FINGERPRINT_W,
) -> List[Tuple[int, int]]:
    """Select the winnowing fingerprints of ``text``.

    Returns ``[(kgram_start_position, hash), ...]`` in ascending position
    order, one selection per window (leftmost minimum, duplicates removed).
    A hash stream shorter than ``w`` is treated as a single window; a text
    shorter than ``k`` characters yields no fingerprints.
    """
    hashes = kgram_hashes(text, k)
    n = len(hashes)
    if n == 0:
        return []
    if n <= w:
        windows = [range(n)]
    else:
        windows = [range(i, i + w) for i in range(n - w + 1)]
    selected: List[Tuple[int, int]] = []
    seen = set()
    for window in windows:
        best = -1
        for pos in window:
            if best < 0 or hashes[pos] < hashes[best]:
                best = pos
        if best >= 0 and best not in seen:
            seen.add(best)
            selected.append((best, hashes[best]))
    selected.sort()
    return selected


def fingerprint_match_spans(
    text_a: str,
    text_b: str,
    k: int = FINGERPRINT_K,
    w: int = FINGERPRINT_W,
    min_span: int = MIN_FINGERPRINT_SPAN,
) -> List[Dict[str, int]]:
    """Shared exact-match spans of two texts, found through fingerprints.

    Returns ``[{"a_start", "a_end", "b_start", "b_end"}, ...]`` with
    positions into ``text_a`` / ``text_b`` as passed in, sorted by
    ``a_start``. Every returned span is a verbatim exact match on both
    sides (the extension step compares characters), its length is
    ``>= min_span``, and shared runs shorter than ``min_span`` never
    appear. Pure and deterministic.
    """
    if not text_a or not text_b:
        return []
    fa = winnowing_fingerprints(text_a, k, w)
    fb = winnowing_fingerprints(text_b, k, w)
    if not fa or not fb:
        return []

    by_hash: Dict[int, List[int]] = {}
    for pos, h in fb:
        by_hash.setdefault(h, []).append(pos)

    groups: Dict[int, List[int]] = {}
    for pa, ha in fa:
        for pb in by_hash.get(ha, ()):
            groups.setdefault(pb - pa, []).append(pa)

    spans: List[Dict[str, int]] = []
    for offset in sorted(groups):
        pas = sorted(set(groups[offset]))
        merged: List[List[int]] = []
        for pa in pas:
            s, e = pa, pa + k
            if merged and s <= merged[-1][1]:
                if e > merged[-1][1]:
                    merged[-1][1] = e
            else:
                merged.append([s, e])
        for s, e in merged:
            while (s > 0 and s + offset > 0
                   and text_a[s - 1] == text_b[s + offset - 1]):
                s -= 1
            while (e < len(text_a) and e + offset < len(text_b)
                   and text_a[e] == text_b[e + offset]):
                e += 1
            if e - s >= min_span:
                spans.append({
                    "a_start": s,
                    "a_end": e,
                    "b_start": s + offset,
                    "b_end": e + offset,
                })
    spans.sort(key=lambda d: (d["a_start"], d["a_end"],
                              d["b_start"], d["b_end"]))
    out: List[Dict[str, int]] = []
    seen = set()
    for sp in spans:
        key = (sp["a_start"], sp["a_end"], sp["b_start"], sp["b_end"])
        if key not in seen:
            seen.add(key)
            out.append(sp)
    return out
