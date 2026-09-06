from typing import Dict, Optional
from .chunker import split_into_multi_scale_windows
from .metrics import calc_h1_density, calc_h2_structure_similarity, calc_h3_content_similarity
from .models import EvaluationResult, SignalColor
from .tokenizer import tokenize

LUT_RULES: Dict[str, tuple] = {
    "1110": (SignalColor.RED, "EXACT_COPY_AND_FORMAT_MATCH", "共通フォーマットに沿った文章構造および本文内容の完全なコピーが検出されました。"),
    "1100": (SignalColor.YELLOW, "COINCIDENTAL_FORMAT_MATCH", "指定課題のフォーマットや文章構造の型が一致しています(本文内容は独自)。"),
    "1010": (SignalColor.RED, "PARAPHRASE_DETECTED", "構文構造は独自ですが、内容語の高度な一致(パラフレーズ・語彙置換による流用)が検出されました。"),
    "1000": (SignalColor.GREEN, "STANDARD_STRUCTURE_UNIQUE", "標準的な記述密度を持った独自の文章です。"),
    "0110": (SignalColor.RED, "FORMATTED_PARAPHRASE", "特殊構造内での内容流用・言い換えが検出されました。"),
    "0100": (SignalColor.YELLOW, "FORMAT_ONLY_MATCH", "定型構造のみの一致です(内容は独自)。"),
    "0010": (SignalColor.RED, "UNFORMATTED_CONTENT_COPY", "構造化されていないテキスト間での本文直接コピー・流用が検出されました。"),
    "0000": (SignalColor.GREEN, "FULLY_UNIQUE", "構造・内容ともに完全な独自記述です。"),
    "1111": (SignalColor.RED, "CLUSTER_EXACT_COPY", "複数人による集団的な完全コピペネットワークが検出されました。"),
    "1101": (SignalColor.YELLOW, "CLUSTER_FORMAT_SHARING", "複数人で共通テンプレートを使い回しているクラスタです。"),
    "1011": (SignalColor.RED, "CLUSTER_PARAPHRASE_GROUP", "複数人による集団的な言い換え・単語置換グループが検出されました。"),
    "1001": (SignalColor.GREEN, "CLUSTER_DENSE_UNIQUE", "特定グループ内での標準的な記述です。"),
}


class SieveReferee:
    def __init__(self, h1_threshold: float = 0.35, h2_threshold: float = 0.80, h3_threshold: float = 0.45):
        self.h1_th = h1_threshold
        self.h2_th = h2_threshold
        self.h3_th = h3_threshold

    def evaluate_pair(self, item_id: str, doc_a: str, doc_b: str, peer_id: Optional[str] = None) -> EvaluationResult:
        h1_score_a = calc_h1_density(doc_a)
        b1 = 1 if h1_score_a >= self.h1_th else 0

        tokens_a = tokenize(doc_a)
        tokens_b = tokenize(doc_b)
        h2_score = calc_h2_structure_similarity(tokens_a, tokens_b)
        b2 = 1 if h2_score >= self.h2_th else 0

        sentences_a = [s for s in doc_a.split("。") if s.strip()]
        chunks_a = split_into_multi_scale_windows(doc_a, [1, 2])
        chunks_b = split_into_multi_scale_windows(doc_b, [1, 2])

        max_h3 = 0.0
        flagged_sentences = set()
        for ca in chunks_a:
            for cb in chunks_b:
                h3 = calc_h3_content_similarity(ca.text, cb.text)
                if h3 > max_h3:
                    max_h3 = h3
                if h3 >= self.h3_th and ca.window_size == 1:
                    flagged_sentences.add(ca.chunk_id)

        b3 = 1 if max_h3 >= self.h3_th else 0
        coverage = len(flagged_sentences) / len(sentences_a) if sentences_a else 0.0

        b4 = 0
        mask = f"{b1}{b2}{b3}{b4}"
        signal, pattern, reason = LUT_RULES.get(mask, (SignalColor.YELLOW, "UNKNOWN_PATTERN", "未定義パターンの判定です。確認が必要です。"))

        return EvaluationResult(
            item_id=item_id,
            evaluation_signal=signal,
            mask=mask,
            pattern_name=pattern,
            reason=reason,
            structural_density=round(h1_score_a, 4),
            max_structure_similarity=round(h2_score, 4),
            max_content_similarity=round(max_h3, 4),
            coverage=round(coverage, 4),
            matched_peer_id=peer_id,
        )


_default_referee = None


def evaluate_pair(doc_a: str, doc_b: str, id_a: str = "doc_a", id_b: str = "doc_b"):
    global _default_referee
    if _default_referee is None:
        _default_referee = SieveReferee()
    return _default_referee.evaluate_pair(item_id=id_a, doc_a=doc_a, doc_b=doc_b, peer_id=id_b)
