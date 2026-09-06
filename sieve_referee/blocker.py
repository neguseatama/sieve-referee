from typing import Dict, Set, Tuple
from collections import defaultdict
from sieve_referee.tokenizer import tokenize


class DeterministicBlocker:
    def __init__(self, ngram_size: int = 3, min_shared_ngrams: int = 1):
        self.ngram_size = ngram_size
        self.min_shared_ngrams = min_shared_ngrams

    def _extract_ngrams(self, text: str) -> Set[str]:
        tokens = [t.raw_text for t in tokenize(text)]
        if len(tokens) < self.ngram_size:
            return set(tokens) if tokens else {text}
        return {"".join(tokens[i : i + self.ngram_size]) for i in range(len(tokens) - self.ngram_size + 1)}

    def get_candidate_pairs(self, docs: Dict[str, str]) -> Set[Tuple[str, str]]:
        doc_ids = sorted(docs.keys())
        if len(doc_ids) < 10:
            candidates = set()
            for i in range(len(doc_ids)):
                for j in range(i + 1, len(doc_ids)):
                    candidates.add((doc_ids[i], doc_ids[j]))
            return candidates
        inverted_index: Dict[str, Set[str]] = defaultdict(set)
        for doc_id in doc_ids:
            ngrams = self._extract_ngrams(docs[doc_id])
            for ngram in ngrams:
                inverted_index[ngram].add(doc_id)
        shared_counts = defaultdict(int)
        for ngram, sharing_docs in inverted_index.items():
            if len(sharing_docs) < 2:
                continue
            sorted_sharing = sorted(sharing_docs)
            for i in range(len(sorted_sharing)):
                for j in range(i + 1, len(sorted_sharing)):
                    pair = (sorted_sharing[i], sorted_sharing[j])
                    shared_counts[pair] += 1
        return {pair for pair, count in shared_counts.items() if count >= self.min_shared_ngrams}
