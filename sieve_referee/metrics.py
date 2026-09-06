from typing import List, Set
from .models import Token
from .tokenizer import extract_keywords_with_subgrams, tokenize


def calc_h1_density(text: str) -> float:
    if not text:
        return 0.0
    return len(set(text)) / len(text)


def _generate_ngrams(tokens: List[str], n: int) -> Set[str]:
    if len(tokens) < n:
        return {"_".join(tokens)} if tokens else set()
    return {"_".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def calc_h2_structure_similarity(tokens_a: List[Token], tokens_b: List[Token]) -> float:
    skel_a = [t.skeleton_tag for t in tokens_a]
    skel_b = [t.skeleton_tag for t in tokens_b]
    ngrams_a = _generate_ngrams(skel_a, n=5) | _generate_ngrams(skel_a, n=6)
    ngrams_b = _generate_ngrams(skel_b, n=5) | _generate_ngrams(skel_b, n=6)
    if not ngrams_a or not ngrams_b:
        return 0.0
    return len(ngrams_a & ngrams_b) / len(ngrams_a | ngrams_b)


def calc_h3_content_similarity(text_a: str, text_b: str) -> float:
    feats_a = extract_keywords_with_subgrams(text_a)
    feats_b = extract_keywords_with_subgrams(text_b)
    if not feats_a or not feats_b:
        return 0.0
    return len(feats_a & feats_b) / len(feats_a | feats_b)
