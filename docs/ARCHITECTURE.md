# 🏛️ Architecture Specification

## Pipeline overview

```
[ Input documents ]
        │
        ▼
[ NFKC normalization (unicodedata) ]
        │
        ▼
[ Deterministic pre-blocking (inverted index over n-grams) ]
   → discards pairs sharing zero n-grams; ~93% pair reduction
     on a 52-document / 1,326-pair test set (89 candidate pairs)
        │
        ▼
[ Per-candidate-pair evaluation: H1–H3 ]
        │
        ▼
[ Cluster construction over RED/YELLOW edges ]
        │
        ▼
[ H4 safety-gated cluster promotion ]
        │
        ▼
[ 12-state LUT lookup → signal, pattern, reason ]
```

## The four hypotheses

| Bit | Hypothesis | What it measures |
|---|---|---|
| `H1` | Descriptive density | `len(set(text)) / len(text)` — unique-character ratio |
| `H2` | Structural similarity | 5/6-gram Jaccard similarity over a script-boundary token skeleton (hiragana kept literal, kanji/katakana/alphanumerics abstracted to `<KW>`) |
| `H3` | Content similarity | Jaccard similarity over content-word blocks plus their internal character 2-grams |
| `H4` | Cluster membership | Whether the pair belongs to a connected component of size ≥ 3 built from `H2`/`H3`-positive edges |

## Safety invariant: `H4` requires direct evidence

```
H4 = 1  ⟺  cluster_size(pair) ≥ 3  ∧  (H2 = 1 ∨ H3 = 1)
```

`H4` is never set on the strength of cluster membership alone. A pair with
no direct similarity of its own — for example `A <-> C` in a chain where
`A <-> B` and `B <-> C` are both flagged but `A` and `C` were never compared
favorably on their own — keeps its original, unmodified mask. Its
membership in the larger cluster is instead reported separately as a
"transitive chain" (telephone-game) warning.

This distinction matters because 4 of the 16 possible 4-bit states
(`H3 = 0 ∧ H4 = 1`, with `H1`/`H2` free) are structurally unreachable under
this invariant, leaving 12 reachable states in the LUT.

## Known limitation: structural convergence in formal writing

Formal academic Japanese sentences that follow a common grammatical pattern
(e.g. "〜における〜について〜的に分析する") can reach a structural
similarity (`H2`) of up to roughly 0.79 even when their content is entirely
unrelated. The `H2` threshold (0.80) is set with this measured ceiling in
mind, and the resulting margin is intentionally thin rather than eliminated
outright — doing so would require semantic understanding, which this
project deliberately avoids.
