import re
from typing import List, Set
from .models import Token

PATTERN = re.compile(
    r"(https?://\S+|www\.\S+)|"
    r"(\d+)|"
    r"([\u4e00-\u9fff]+)|"
    r"([\u30a0-\u30ff]+)|"
    r"([\u3040-\u309f]+)|"
    r"([a-zA-Z_]+)|"
    r"([^\w\s])"
)


def tokenize(text: str) -> List[Token]:
    tokens = []
    for match in PATTERN.finditer(text):
        url, num, kanji, katakana, hiragana, alpha, symbol = match.groups()
        raw = match.group(0)
        if url:
            tokens.append(Token(raw, "<URL>"))
        elif num:
            tokens.append(Token(raw, "<NUM>"))
        elif kanji or katakana or alpha:
            tokens.append(Token(raw, "<KW>"))
        elif hiragana or symbol:
            tokens.append(Token(raw, raw))
    return tokens


def extract_keywords_with_subgrams(text: str, min_gram: int = 2) -> Set[str]:
    tokens = tokenize(text)
    features = set()
    for t in tokens:
        if t.skeleton_tag == "<KW>":
            raw = t.raw_text
            features.add(raw)
            if len(raw) >= min_gram:
                for i in range(len(raw) - min_gram + 1):
                    features.add(raw[i : i + min_gram])
    return features


def extract_keywords(text: str) -> Set[str]:
    tokens = tokenize(text)
    return {t.raw_text for t in tokens if t.skeleton_tag == "<KW>"}
